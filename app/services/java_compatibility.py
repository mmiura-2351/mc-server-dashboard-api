import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from packaging import version

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class JavaVersionInfo:
    """Java version information"""

    major_version: int
    minor_version: int
    patch_version: int
    vendor: Optional[str] = None
    full_version_string: str = ""
    executable_path: str = "java"  # Path to Java executable

    @property
    def version_string(self) -> str:
        """Get version as string (e.g., '17.0.1')"""
        return f"{self.major_version}.{self.minor_version}.{self.patch_version}"

    @property
    def is_compatible_with_java_8(self) -> bool:
        """Check if this version is compatible with Java 8 requirements"""
        return self.major_version == 8

    @property
    def is_compatible_with_java_16(self) -> bool:
        """Check if this version is compatible with Java 16 requirements"""
        return self.major_version >= 16

    @property
    def is_compatible_with_java_17(self) -> bool:
        """Check if this version is compatible with Java 17 requirements"""
        return self.major_version >= 17

    @property
    def is_compatible_with_java_21(self) -> bool:
        """Check if this version is compatible with Java 21 requirements"""
        return self.major_version >= 21


class JavaCompatibilityService:
    """Service for Java version detection and Minecraft compatibility validation"""

    def __init__(self, java_check_timeout: int = 10):
        self.java_check_timeout = java_check_timeout
        # Java-Minecraft compatibility matrix based on official requirements
        self._compatibility_matrix = {
            # Minecraft 1.8 - 1.16.5: Java 8
            (version.Version("1.8.0"), version.Version("1.16.5")): 8,
            # Minecraft 1.17 - 1.17.1: Java 16
            (version.Version("1.17.0"), version.Version("1.17.1")): 16,
            # Minecraft 1.18 - 1.20: Java 17
            (version.Version("1.18.0"), version.Version("1.20.9")): 17,
            # Minecraft 1.21+: Java 21
            (version.Version("1.21.0"), version.Version("9999.99.99")): 21,
        }

    async def discover_java_installations(self) -> Dict[int, JavaVersionInfo]:
        """Discover available Java installations by major version"""
        java_installations = {}

        # Check configured paths first
        for major_version in [8, 16, 17, 21]:
            configured_path = settings.get_java_path(major_version)
            if configured_path:
                java_info = await self._detect_java_at_path(configured_path)
                if java_info and java_info.major_version == major_version:
                    java_installations[major_version] = java_info
                    logger.info(
                        f"Found configured Java {major_version} at {configured_path}"
                    )

        # Discover OpenJDK installations in common paths
        discovered = await self._discover_openjdk_installations()
        for java_info in discovered:
            major = java_info.major_version
            if major not in java_installations:  # Don't override configured paths
                java_installations[major] = java_info
                logger.info(f"Discovered OpenJDK {major} at {java_info.executable_path}")

        # Fallback to system PATH java
        if not java_installations:
            system_java = await self._detect_java_at_path("java")
            if system_java:
                java_installations[system_java.major_version] = system_java
                logger.info(f"Using system Java {system_java.major_version}")

        return java_installations

    async def detect_java_version(self) -> Optional[JavaVersionInfo]:
        """Detect default Java version (for backward compatibility)"""
        return await self._detect_java_at_path("java")

    async def get_java_for_minecraft(
        self, minecraft_version: str
    ) -> Optional[JavaVersionInfo]:
        """Get appropriate Java installation for Minecraft version"""
        required_java = self.get_required_java_version(minecraft_version)
        installations = await self.discover_java_installations()

        # Try exact match first
        if required_java in installations:
            return installations[required_java]

        # Try compatible higher versions
        compatible_versions = sorted(
            [v for v in installations.keys() if v >= required_java]
        )
        if compatible_versions:
            return installations[compatible_versions[0]]

        return None

    async def _detect_java_at_path(self, java_path: str) -> Optional[JavaVersionInfo]:
        """Detect Java version at specific path"""
        try:
            process = await asyncio.create_subprocess_exec(
                java_path,
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.java_check_timeout
            )

            if process.returncode != 0:
                logger.debug(f"Java version command failed for {java_path}")
                return None

            # Java version info is typically in stderr
            version_output = stderr.decode("utf-8") if stderr else ""
            if not version_output and stdout:
                version_output = stdout.decode("utf-8")

            java_info = self._parse_java_version(version_output)
            if java_info:
                java_info.executable_path = java_path
            return java_info

        except (asyncio.TimeoutError, FileNotFoundError, OSError) as e:
            logger.debug(
                f"Java detection failed for {java_path}: {type(e).__name__}: {e}"
            )
            return None

    async def _discover_openjdk_installations(self) -> List[JavaVersionInfo]:
        """Discover OpenJDK installations in common locations"""
        installations = []

        # Common OpenJDK installation paths
        search_paths = [
            "/usr/lib/jvm",  # Linux
            "/usr/java",  # Linux alternative
            "/opt/java",  # Linux alternative
            "/Library/Java/JavaVirtualMachines",  # macOS
            "C:\\Program Files\\Java",  # Windows
            "C:\\Program Files (x86)\\Java",  # Windows 32-bit
        ]

        # Add configured discovery paths
        search_paths.extend(settings.java_discovery_paths_list)

        for search_path in search_paths:
            if not os.path.exists(search_path):
                continue

            try:
                for item in os.listdir(search_path):
                    item_path = Path(search_path) / item
                    if not item_path.is_dir():
                        continue

                    # Look for OpenJDK directories
                    if "openjdk" not in item.lower() and "jdk" not in item.lower():
                        continue

                    # Try to find java executable
                    java_executable = self._find_java_executable(item_path)
                    if java_executable:
                        java_info = await self._detect_java_at_path(str(java_executable))
                        if java_info and self._is_openjdk(java_info):
                            installations.append(java_info)

            except (OSError, PermissionError) as e:
                logger.debug(f"Cannot access {search_path}: {e}")
                continue

        return installations

    def _find_java_executable(self, jdk_path: Path) -> Optional[Path]:
        """Find java executable in JDK directory"""
        # Common locations for java executable within JDK
        possible_paths = [
            jdk_path / "bin" / "java",
            jdk_path / "bin" / "java.exe",  # Windows
            jdk_path / "Contents" / "Home" / "bin" / "java",  # macOS bundle
        ]

        for java_path in possible_paths:
            if java_path.exists() and java_path.is_file():
                return java_path

        return None

    def _is_openjdk(self, java_info: JavaVersionInfo) -> bool:
        """Check if Java installation is OpenJDK-based"""
        if not java_info.full_version_string:
            return False

        version_text = java_info.full_version_string.lower()
        openjdk_indicators = ["openjdk", "temurin", "adoptopenjdk", "liberica", "zulu"]

        return any(indicator in version_text for indicator in openjdk_indicators)

    def _parse_java_version(self, version_output: str) -> Optional[JavaVersionInfo]:
        """Parse Java version output into structured information"""
        try:
            logger.debug(f"Parsing Java version output: {version_output}")

            # Common patterns for Java version output
            patterns = [
                # Modern Java (9+): java 17.0.1 2021-10-19 LTS
                r"java\s+(\d+)\.(\d+)\.(\d+)",
                # Legacy Java (8): java version "1.8.0_292"
                r'java version "1\.(\d+)\.(\d+)_(\d+)"',
                # OpenJDK: openjdk version "17.0.1" 2021-10-19
                r'openjdk version "(\d+)\.(\d+)\.(\d+)"',
                # Alternative format: version "17.0.1"
                r'version "(\d+)\.(\d+)\.(\d+)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, version_output)
                if match:
                    groups = match.groups()

                    # Handle Java 8 legacy format (1.8.0_xxx)
                    if len(groups) == 3 and "1.8.0" in version_output:
                        major_version = 8
                        minor_version = int(groups[1])
                        patch_version = int(groups[2])
                    else:
                        major_version = int(groups[0])
                        minor_version = int(groups[1]) if len(groups) > 1 else 0
                        patch_version = int(groups[2]) if len(groups) > 2 else 0

                    # Extract vendor information
                    vendor = None
                    if "OpenJDK" in version_output:
                        vendor = "OpenJDK"
                    elif "Oracle" in version_output:
                        vendor = "Oracle"
                    elif "Temurin" in version_output:
                        vendor = "Eclipse Temurin"

                    return JavaVersionInfo(
                        major_version=major_version,
                        minor_version=minor_version,
                        patch_version=patch_version,
                        vendor=vendor,
                        full_version_string=version_output.strip(),
                    )

            # Fallback: try to extract just the major version
            major_match = re.search(r"(\d+)", version_output)
            if major_match:
                major_version = int(major_match.group(1))
                # Special handling for Java 8 detection
                if "1.8" in version_output:
                    major_version = 8

                logger.warning(
                    f"Using fallback Java version parsing: major={major_version}"
                )
                return JavaVersionInfo(
                    major_version=major_version,
                    minor_version=0,
                    patch_version=0,
                    full_version_string=version_output.strip(),
                )

            logger.error(f"Unable to parse Java version from: {version_output}")
            return None

        except Exception as e:
            logger.error(f"Error parsing Java version: {e}")
            return None

    def get_required_java_version(self, minecraft_version: str) -> int:
        """Get required Java major version for a Minecraft version"""
        try:
            mc_version = version.Version(minecraft_version)

            for (min_mc, max_mc), required_java in self._compatibility_matrix.items():
                if min_mc <= mc_version <= max_mc:
                    return required_java

            # Default fallback for unknown versions
            logger.warning(
                f"Unknown Minecraft version {minecraft_version}, defaulting to Java 21"
            )
            return 21

        except Exception as e:
            logger.error(
                f"Error determining required Java version for {minecraft_version}: {e}"
            )
            return 21

    def validate_java_compatibility(
        self, minecraft_version: str, java_version: JavaVersionInfo
    ) -> Tuple[bool, str]:
        """Validate Java version compatibility with Minecraft version"""
        try:
            required_java = self.get_required_java_version(minecraft_version)

            # Check if installed Java meets requirements
            if required_java == 8:
                compatible = java_version.is_compatible_with_java_8
            elif required_java == 16:
                compatible = java_version.is_compatible_with_java_16
            elif required_java == 17:
                compatible = java_version.is_compatible_with_java_17
            elif required_java == 21:
                compatible = java_version.is_compatible_with_java_21
            else:
                compatible = False

            if compatible:
                return (
                    True,
                    f"Java {java_version.major_version} is compatible with Minecraft {minecraft_version}",
                )
            else:
                return False, self._generate_compatibility_error_message(
                    minecraft_version, required_java, java_version
                )

        except Exception as e:
            logger.error(f"Error validating Java compatibility: {e}")
            return False, f"Failed to validate Java compatibility: {e}"

    def _generate_compatibility_error_message(
        self, minecraft_version: str, required_java: int, java_version: JavaVersionInfo
    ) -> str:
        """Generate user-friendly error message for compatibility issues"""
        message = (
            f"Java version incompatibility detected:\n"
            f"  • Minecraft {minecraft_version} requires Java {required_java} or higher\n"
            f"  • Currently installed: Java {java_version.major_version} "
            f"({java_version.version_string})"
        )

        if java_version.vendor:
            message += f" [{java_version.vendor}]"

        # Add specific guidance based on the version gap
        if java_version.major_version < required_java:
            message += f"\n\nPlease install Java {required_java} or higher to run this Minecraft version."

            # Add helpful links for Java installation
            if required_java == 8:
                message += "\n\nDownload Java 8: https://adoptium.net/temurin/releases/?version=8"
            elif required_java == 16:
                message += "\n\nDownload Java 16: https://adoptium.net/temurin/releases/?version=16"
            elif required_java == 17:
                message += "\n\nDownload Java 17: https://adoptium.net/temurin/releases/?version=17"
            elif required_java == 21:
                message += "\n\nDownload Java 21: https://adoptium.net/temurin/releases/?version=21"

        return message

    def get_compatibility_matrix(self) -> Dict[str, int]:
        """Get human-readable compatibility matrix"""
        matrix = {}
        for (
            min_version,
            max_version,
        ), java_version in self._compatibility_matrix.items():
            version_range = f"{min_version} - {max_version}"
            if max_version.major >= 9999:  # Handle open-ended ranges
                version_range = f"{min_version}+"
            matrix[version_range] = java_version

        return matrix

    def get_supported_minecraft_versions(
        self, java_version: JavaVersionInfo
    ) -> List[str]:
        """Get list of Minecraft versions supported by a Java version"""
        supported_versions = []

        for (min_mc, max_mc), required_java in self._compatibility_matrix.items():
            if java_version.major_version >= required_java:
                if max_mc.major >= 9999:
                    supported_versions.append(f"{min_mc}+")
                else:
                    supported_versions.append(f"{min_mc} - {max_mc}")

        return supported_versions


# Global instance
java_compatibility_service = JavaCompatibilityService()
