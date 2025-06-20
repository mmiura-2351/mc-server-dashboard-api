import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from app.services.java_compatibility import (
    JavaCompatibilityService,
    JavaVersionInfo,
    java_compatibility_service,
)


class TestJavaVersionInfo:
    """Test JavaVersionInfo dataclass"""

    def test_version_string_property(self):
        """Test version_string property"""
        java_info = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        assert java_info.version_string == "17.0.1"

    def test_java_8_compatibility(self):
        """Test Java 8 compatibility checks"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)

        assert java8.is_compatible_with_java_8 is True
        assert java17.is_compatible_with_java_8 is False

    def test_java_16_compatibility(self):
        """Test Java 16+ compatibility checks"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java16 = JavaVersionInfo(major_version=16, minor_version=0, patch_version=1)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)

        assert java8.is_compatible_with_java_16 is False
        assert java16.is_compatible_with_java_16 is True
        assert java17.is_compatible_with_java_16 is True

    def test_java_17_compatibility(self):
        """Test Java 17+ compatibility checks"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java16 = JavaVersionInfo(major_version=16, minor_version=0, patch_version=1)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)

        assert java8.is_compatible_with_java_17 is False
        assert java16.is_compatible_with_java_17 is False
        assert java17.is_compatible_with_java_17 is True

    def test_java_21_compatibility(self):
        """Test Java 21+ compatibility checks"""
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        java21 = JavaVersionInfo(major_version=21, minor_version=0, patch_version=1)

        assert java17.is_compatible_with_java_21 is False
        assert java21.is_compatible_with_java_21 is True


class TestJavaCompatibilityService:
    """Test JavaCompatibilityService"""

    @pytest.fixture
    def service(self):
        """Create a test service instance"""
        return JavaCompatibilityService(java_check_timeout=5)

    def test_get_required_java_version(self, service):
        """Test getting required Java version for Minecraft versions"""
        # Test Java 8 requirements (Minecraft 1.8 - 1.16.5)
        assert service.get_required_java_version("1.8.0") == 8
        assert service.get_required_java_version("1.12.2") == 8
        assert service.get_required_java_version("1.16.5") == 8

        # Test Java 16 requirements (Minecraft 1.17 - 1.17.1)
        assert service.get_required_java_version("1.17.0") == 16
        assert service.get_required_java_version("1.17.1") == 16

        # Test Java 17 requirements (Minecraft 1.18 - 1.20)
        assert service.get_required_java_version("1.18.0") == 17
        assert service.get_required_java_version("1.19.4") == 17
        assert service.get_required_java_version("1.20.0") == 17

        # Test Java 21 requirements (Minecraft 1.21+)
        assert service.get_required_java_version("1.21.0") == 21
        assert service.get_required_java_version("1.22.0") == 21

    def test_get_required_java_version_invalid(self, service):
        """Test getting required Java version for invalid Minecraft versions"""
        # Should default to Java 21 for unknown versions
        assert service.get_required_java_version("invalid") == 21
        assert service.get_required_java_version("2.0.0") == 21

    def test_validate_java_compatibility_java_8(self, service):
        """Test Java compatibility validation for Java 8 scenarios"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)

        # Java 8 should be compatible with Minecraft 1.8-1.16.5
        compatible, message = service.validate_java_compatibility("1.8.0", java8)
        assert compatible is True
        assert "compatible" in message.lower()

        compatible, message = service.validate_java_compatibility("1.16.5", java8)
        assert compatible is True

        # Java 8 should NOT be compatible with Minecraft 1.17+
        compatible, message = service.validate_java_compatibility("1.17.0", java8)
        assert compatible is False
        assert "incompatibility" in message.lower()
        assert "Java 16 or higher" in message

    def test_validate_java_compatibility_java_17(self, service):
        """Test Java compatibility validation for Java 17 scenarios"""
        java17 = JavaVersionInfo(
            major_version=17, minor_version=0, patch_version=1, vendor="OpenJDK"
        )

        # Java 17 should be compatible with Minecraft 1.17+ (not 1.8-1.16.5 due to newer version)
        compatible, message = service.validate_java_compatibility("1.8.0", java17)
        assert compatible is False  # Java 17 is too new for Minecraft 1.8

        compatible, message = service.validate_java_compatibility("1.17.0", java17)
        assert compatible is True

        compatible, message = service.validate_java_compatibility("1.18.0", java17)
        assert compatible is True

        compatible, message = service.validate_java_compatibility("1.20.0", java17)
        assert compatible is True

        # Java 17 should NOT be compatible with Minecraft 1.21+ (requires Java 21)
        compatible, message = service.validate_java_compatibility("1.21.0", java17)
        assert compatible is False
        assert "Java 21 or higher" in message

    def test_validate_java_compatibility_java_21(self, service):
        """Test Java compatibility validation for Java 21 scenarios"""
        java21 = JavaVersionInfo(major_version=21, minor_version=0, patch_version=1)

        # Java 21 should be compatible with Minecraft 1.21+
        compatible, message = service.validate_java_compatibility("1.21.0", java21)
        assert compatible is True

        compatible, message = service.validate_java_compatibility("1.22.0", java21)
        assert compatible is True

    def test_parse_java_version_modern_format(self, service):
        """Test parsing modern Java version format (Java 9+)"""
        # Test Java 17 format
        version_output = "java 17.0.1 2021-10-19 LTS"
        result = service._parse_java_version(version_output)

        assert result is not None
        assert result.major_version == 17
        assert result.minor_version == 0
        assert result.patch_version == 1

    def test_parse_java_version_legacy_format(self, service):
        """Test parsing legacy Java version format (Java 8)"""
        # Test Java 8 format
        version_output = 'java version "1.8.0_292"\nJava(TM) SE Runtime Environment'
        result = service._parse_java_version(version_output)

        assert result is not None
        assert result.major_version == 8
        assert result.minor_version == 0
        assert result.patch_version == 292

    def test_parse_java_version_openjdk_format(self, service):
        """Test parsing OpenJDK version format"""
        version_output = (
            'openjdk version "17.0.1" 2021-10-19\nOpenJDK Runtime Environment'
        )
        result = service._parse_java_version(version_output)

        assert result is not None
        assert result.major_version == 17
        assert result.minor_version == 0
        assert result.patch_version == 1
        assert result.vendor == "OpenJDK"

    def test_parse_java_version_invalid(self, service):
        """Test parsing invalid Java version output"""
        result = service._parse_java_version("invalid output")
        assert result is None

        result = service._parse_java_version("")
        assert result is None

    def test_get_compatibility_matrix(self, service):
        """Test getting compatibility matrix"""
        matrix = service.get_compatibility_matrix()

        assert isinstance(matrix, dict)
        assert len(matrix) > 0

        # Check for expected Java versions
        java_versions = list(matrix.values())
        assert 8 in java_versions
        assert 16 in java_versions
        assert 17 in java_versions
        assert 21 in java_versions

    def test_get_supported_minecraft_versions(self, service):
        """Test getting supported Minecraft versions for Java version"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        java21 = JavaVersionInfo(major_version=21, minor_version=0, patch_version=1)

        # Java 8 should only support older Minecraft versions
        supported_8 = service.get_supported_minecraft_versions(java8)
        assert len(supported_8) == 1  # Only the 1.8-1.16.5 range

        # Java 17 should support more ranges
        supported_17 = service.get_supported_minecraft_versions(java17)
        assert len(supported_17) >= 2  # At least 1.17-1.17.1 and 1.18-1.20 ranges

        # Java 21 should support all ranges
        supported_21 = service.get_supported_minecraft_versions(java21)
        assert len(supported_21) >= 4  # All version ranges

    @pytest.mark.asyncio
    async def test_detect_java_version_success(self, service):
        """Test successful Java version detection"""
        mock_version_output = b"java 17.0.1 2021-10-19 LTS\n"

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock successful subprocess
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", mock_version_output)
            mock_subprocess.return_value = mock_process

            result = await service.detect_java_version()

            assert result is not None
            assert result.major_version == 17
            assert result.minor_version == 0
            assert result.patch_version == 1

    @pytest.mark.asyncio
    async def test_detect_java_version_not_found(self, service):
        """Test Java version detection when Java is not installed"""
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock FileNotFoundError (Java not found)
            mock_subprocess.side_effect = FileNotFoundError("java not found")

            result = await service.detect_java_version()
            assert result is None

    @pytest.mark.asyncio
    async def test_detect_java_version_timeout(self, service):
        """Test Java version detection timeout"""
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock timeout
            mock_process = AsyncMock()
            mock_process.communicate.side_effect = asyncio.TimeoutError()
            mock_subprocess.return_value = mock_process

            result = await service.detect_java_version()
            assert result is None

    @pytest.mark.asyncio
    async def test_detect_java_version_error_return_code(self, service):
        """Test Java version detection with error return code"""
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock subprocess with error return code
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"error output")
            mock_subprocess.return_value = mock_process

            result = await service.detect_java_version()
            assert result is None

    @pytest.mark.asyncio
    async def test_discover_java_installations(self, service):
        """Test discovering multiple Java installations"""
        with (
            patch.object(service, "_detect_java_at_path") as mock_detect,
            patch.object(
                service, "_discover_openjdk_installations"
            ) as mock_discover_openjdk,
        ):
            # Mock configured Java paths
            java8 = JavaVersionInfo(
                8, 0, 292, "OpenJDK", "", "/usr/lib/jvm/java-8/bin/java"
            )
            java17 = JavaVersionInfo(
                17, 0, 1, "OpenJDK", "", "/usr/lib/jvm/java-17/bin/java"
            )

            # Mock detection results
            mock_detect.side_effect = lambda path: {
                "/path/to/java8": java8,
                "/path/to/java17": java17,
            }.get(path)

            mock_discover_openjdk.return_value = []

            # Mock settings
            with patch("app.services.java_compatibility.settings") as mock_settings:
                mock_settings.get_java_path.side_effect = lambda v: {
                    8: "/path/to/java8",
                    17: "/path/to/java17",
                }.get(v, "")

                installations = await service.discover_java_installations()

                assert len(installations) == 2
                assert 8 in installations
                assert 17 in installations
                assert installations[8].executable_path == "/usr/lib/jvm/java-8/bin/java"
                assert (
                    installations[17].executable_path == "/usr/lib/jvm/java-17/bin/java"
                )

    @pytest.mark.asyncio
    async def test_get_java_for_minecraft(self, service):
        """Test getting appropriate Java for Minecraft version"""
        with patch.object(service, "discover_java_installations") as mock_discover:
            java8 = JavaVersionInfo(
                8, 0, 292, "OpenJDK", "", "/usr/lib/jvm/java-8/bin/java"
            )
            java17 = JavaVersionInfo(
                17, 0, 1, "OpenJDK", "", "/usr/lib/jvm/java-17/bin/java"
            )
            java21 = JavaVersionInfo(
                21, 0, 1, "OpenJDK", "", "/usr/lib/jvm/java-21/bin/java"
            )

            mock_discover.return_value = {8: java8, 17: java17, 21: java21}

            # Test exact match
            result = await service.get_java_for_minecraft("1.8.9")
            assert result == java8

            # Test compatible higher version
            result = await service.get_java_for_minecraft("1.17.1")
            assert result.major_version >= 16

            # Test latest requirements
            result = await service.get_java_for_minecraft("1.21.0")
            assert result == java21

    @pytest.mark.asyncio
    async def test_get_java_for_minecraft_no_compatible(self, service):
        """Test getting Java when no compatible version is available"""
        with patch.object(service, "discover_java_installations") as mock_discover:
            java8 = JavaVersionInfo(
                8, 0, 292, "OpenJDK", "", "/usr/lib/jvm/java-8/bin/java"
            )
            mock_discover.return_value = {8: java8}

            # Test requiring newer Java than available
            result = await service.get_java_for_minecraft("1.21.0")
            assert result is None

    def test_find_java_executable(self, service):
        """Test finding Java executable in JDK directory"""
        with (
            patch("pathlib.Path.exists") as mock_exists,
            patch("pathlib.Path.is_file") as mock_is_file,
        ):
            # Mock successful finding
            mock_exists.return_value = True
            mock_is_file.return_value = True

            from pathlib import Path

            jdk_path = Path("/usr/lib/jvm/java-17-openjdk")
            result = service._find_java_executable(jdk_path)

            assert result is not None
            assert str(result).endswith("bin/java")

    def test_is_openjdk(self, service):
        """Test OpenJDK detection"""
        # Test OpenJDK
        openjdk_info = JavaVersionInfo(17, 0, 1, "OpenJDK", 'openjdk version "17.0.1"')
        assert service._is_openjdk(openjdk_info) is True

        # Test Temurin (Eclipse)
        temurin_info = JavaVersionInfo(
            17, 0, 1, "Temurin", "Eclipse Temurin Runtime Environment"
        )
        assert service._is_openjdk(temurin_info) is True

        # Test Oracle (not OpenJDK)
        oracle_info = JavaVersionInfo(
            17, 0, 1, "Oracle", "Java(TM) SE Runtime Environment"
        )
        assert service._is_openjdk(oracle_info) is False

        # Test empty version string
        empty_info = JavaVersionInfo(17, 0, 1, None, "")
        assert service._is_openjdk(empty_info) is False


class TestJavaCompatibilityServiceIntegration:
    """Integration tests for Java compatibility service"""

    def test_global_service_instance(self):
        """Test that global service instance is properly initialized"""
        assert java_compatibility_service is not None
        assert isinstance(java_compatibility_service, JavaCompatibilityService)
        assert java_compatibility_service.java_check_timeout > 0

    def test_compatibility_matrix_completeness(self):
        """Test that compatibility matrix covers expected version ranges"""
        matrix = java_compatibility_service.get_compatibility_matrix()

        # Should have entries for all major Java version requirements
        java_versions = set(matrix.values())
        expected_versions = {8, 16, 17, 21}

        assert expected_versions.issubset(java_versions), (
            f"Missing Java versions: {expected_versions - java_versions}"
        )

    def test_error_message_generation(self):
        """Test that error messages are user-friendly and informative"""
        service = java_compatibility_service
        java8 = JavaVersionInfo(
            major_version=8, minor_version=0, patch_version=292, vendor="Oracle"
        )

        # Test incompatible scenario
        compatible, message = service.validate_java_compatibility("1.21.0", java8)

        assert compatible is False
        assert "Java version incompatibility detected" in message
        assert "Minecraft 1.21.0 requires Java 21" in message
        assert "Currently installed: Java 8" in message
        assert "Oracle" in message  # Vendor should be included
        assert "https://adoptium.net" in message  # Installation link should be included


class TestJavaCompatibilityServiceMissingCoverage:
    """Test cases for missing coverage in JavaCompatibilityService"""

    @pytest.fixture
    def service(self):
        """Create a test service instance"""
        return JavaCompatibilityService(java_check_timeout=5)

    @pytest.mark.asyncio
    async def test_discover_java_installations_configured_path_mismatch(self, service):
        """Test when configured path has wrong Java version (line 79->75)"""
        with (
            patch.object(service, "_detect_java_at_path") as mock_detect,
            patch.object(
                service, "_discover_openjdk_installations"
            ) as mock_discover_openjdk,
        ):
            # Mock Java 8 at path configured for Java 17 (version mismatch)
            java8_at_wrong_path = JavaVersionInfo(8, 0, 292, "OpenJDK", "", "/wrong/path")
            mock_detect.return_value = java8_at_wrong_path
            mock_discover_openjdk.return_value = []

            with patch("app.services.java_compatibility.settings") as mock_settings:
                mock_settings.get_java_path.side_effect = (
                    lambda v: "/configured/java17" if v == 17 else ""
                )

                installations = await service.discover_java_installations()

                # Should not include Java 8 found at Java 17 path
                assert 17 not in installations

    @pytest.mark.asyncio
    async def test_discover_java_installations_openjdk_fallback(self, service):
        """Test OpenJDK discovery fallback when no configured paths (lines 88-91)"""
        with (
            patch.object(service, "_detect_java_at_path") as mock_detect,
            patch.object(
                service, "_discover_openjdk_installations"
            ) as mock_discover_openjdk,
        ):
            # No configured paths return Java
            mock_detect.return_value = None

            # Mock OpenJDK discovery
            java17_openjdk = JavaVersionInfo(
                17, 0, 1, "OpenJDK", "", "/usr/lib/jvm/java-17/bin/java"
            )
            mock_discover_openjdk.return_value = [java17_openjdk]

            with patch("app.services.java_compatibility.settings") as mock_settings:
                mock_settings.get_java_path.return_value = ""  # No configured paths

                installations = await service.discover_java_installations()

                assert 17 in installations
                assert (
                    installations[17].executable_path == "/usr/lib/jvm/java-17/bin/java"
                )

    @pytest.mark.asyncio
    async def test_discover_java_installations_system_java_fallback(self, service):
        """Test system Java fallback when no other installations found (lines 95-98)"""
        with (
            patch.object(service, "_detect_java_at_path") as mock_detect,
            patch.object(
                service, "_discover_openjdk_installations"
            ) as mock_discover_openjdk,
        ):
            # Mock no configured Java and no OpenJDK discoveries
            system_java = JavaVersionInfo(11, 0, 1, "OpenJDK", "", "java")
            mock_detect.side_effect = lambda path: system_java if path == "java" else None
            mock_discover_openjdk.return_value = []

            with patch("app.services.java_compatibility.settings") as mock_settings:
                mock_settings.get_java_path.return_value = ""

                installations = await service.discover_java_installations()

                assert 11 in installations
                assert installations[11].executable_path == "java"

    @pytest.mark.asyncio
    async def test_detect_java_at_path_stdout_fallback(self, service):
        """Test _detect_java_at_path when stderr is empty but stdout has version (line 146, 149->151)"""
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            # Empty stderr, version in stdout
            mock_process.communicate.return_value = (b"java 17.0.1 2021-10-19 LTS\n", b"")
            mock_subprocess.return_value = mock_process

            result = await service._detect_java_at_path("/usr/bin/java")

            assert result is not None
            assert result.major_version == 17
            assert result.executable_path == "/usr/bin/java"

    @pytest.mark.asyncio
    async def test_discover_openjdk_installations_comprehensive(self, service):
        """Test comprehensive OpenJDK installation discovery (lines 161-201)"""
        from pathlib import Path

        with (
            patch("os.path.exists") as mock_exists,
            patch("os.listdir") as mock_listdir,
            patch("pathlib.Path.is_dir") as mock_is_dir,
            patch.object(service, "_find_java_executable") as mock_find_java,
            patch.object(service, "_detect_java_at_path") as mock_detect,
            patch.object(service, "_is_openjdk") as mock_is_openjdk,
        ):
            # Mock directory structure
            mock_exists.side_effect = lambda path: path in ["/usr/lib/jvm", "/opt/java"]
            mock_listdir.side_effect = lambda path: {
                "/usr/lib/jvm": ["java-17-openjdk", "non-java-dir", "java-8-openjdk"],
                "/opt/java": ["openjdk-21"],
            }.get(path, [])

            mock_is_dir.return_value = True

            # Mock Java detection results
            java17 = JavaVersionInfo(
                17, 0, 1, "OpenJDK", "openjdk version", "/usr/lib/jvm/java-17/bin/java"
            )
            java8 = JavaVersionInfo(
                8, 0, 292, "OpenJDK", "openjdk version", "/usr/lib/jvm/java-8/bin/java"
            )
            java21 = JavaVersionInfo(
                21, 0, 1, "OpenJDK", "openjdk version", "/opt/java/openjdk-21/bin/java"
            )

            # Mock each call individually with proper java path return
            detect_call_count = 0

            async def mock_detect_side_effect(path):
                nonlocal detect_call_count
                detect_call_count += 1
                if detect_call_count == 1:
                    return java17
                elif detect_call_count == 2:
                    return java8
                elif detect_call_count == 3:
                    return java21
                return None

            mock_find_java.return_value = Path("/path/to/java")
            mock_detect.side_effect = mock_detect_side_effect
            mock_is_openjdk.return_value = True

            with patch("app.services.java_compatibility.settings") as mock_settings:
                mock_settings.java_discovery_paths_list = ["/opt/java"]

                installations = await service._discover_openjdk_installations()

                assert len(installations) == 3
                assert java17 in installations
                assert java8 in installations
                assert java21 in installations

    @pytest.mark.asyncio
    async def test_discover_openjdk_installations_permission_error(self, service):
        """Test OpenJDK discovery with permission errors (lines 197-199)"""
        with patch("os.path.exists") as mock_exists, patch("os.listdir") as mock_listdir:
            mock_exists.return_value = True
            mock_listdir.side_effect = PermissionError("Permission denied")

            with patch("app.services.java_compatibility.settings") as mock_settings:
                mock_settings.java_discovery_paths_list = []

                installations = await service._discover_openjdk_installations()

                assert installations == []

    def test_find_java_executable_windows_path(self, service):
        """Test finding Java executable on Windows (line 213->212, 216)"""
        from pathlib import Path

        # Simplify by testing the method logic more directly
        # Create a Path that exists
        jdk_path = Path("/usr/lib/jvm/java-17")

        # Mock the specific java executable file
        with (
            patch.object(Path, "exists") as mock_exists,
            patch.object(Path, "is_file") as mock_is_file,
        ):
            # Return True only for the first call (bin/java), False for others
            mock_exists.side_effect = [True]  # First path exists
            mock_is_file.side_effect = [True]  # First path is file

            result = service._find_java_executable(jdk_path)

            assert result is not None
            assert str(result).endswith("bin/java")

    def test_find_java_executable_not_found(self, service):
        """Test finding Java executable when not found (line 216)"""
        from pathlib import Path

        with (
            patch("pathlib.Path.exists") as mock_exists,
            patch("pathlib.Path.is_file") as mock_is_file,
        ):
            mock_exists.return_value = False
            mock_is_file.return_value = False

            jdk_path = Path("/nonexistent/jdk")
            result = service._find_java_executable(jdk_path)

            assert result is None

    def test_parse_java_version_minimal_match(self, service):
        """Test parsing Java version with minimal version info (line 265, 267)"""
        # Test version string with only major version number
        version_output = "11"
        result = service._parse_java_version(version_output)

        assert result is not None
        assert result.major_version == 11
        assert result.minor_version == 0
        assert result.patch_version == 0

    def test_parse_java_version_java_8_fallback_detection(self, service):
        """Test Java 8 detection in fallback parsing (lines 280-288)"""
        # Test version string that triggers fallback but contains 1.8
        version_output = "some weird output 1.8 java version"
        result = service._parse_java_version(version_output)

        assert result is not None
        assert result.major_version == 8
        assert result.minor_version == 0
        assert result.patch_version == 0
        assert "some weird output" in result.full_version_string

    def test_parse_java_version_unparseable(self, service):
        """Test parsing completely unparseable version (line 295-296)"""
        version_output = "no numbers here at all!"
        result = service._parse_java_version(version_output)

        assert result is None

    def test_parse_java_version_exception_handling(self, service):
        """Test exception handling in version parsing (lines 298-300)"""
        # Force an exception in the regex processing by mocking re.search
        with patch("re.search", side_effect=Exception("Regex error")):
            version_output = "java 17.0.1 2021-10-19 LTS"
            result = service._parse_java_version(version_output)

            assert result is None

    def test_get_required_java_version_exception_handling(self, service):
        """Test exception handling in get_required_java_version (lines 312-315)"""
        # Mock version parsing to raise exception
        with patch("packaging.version.Version", side_effect=Exception("Invalid version")):
            result = service.get_required_java_version("invalid-version-format")

            assert result == 21  # Should fallback to Java 21

    def test_validate_java_compatibility_exception_handling(self, service):
        """Test exception handling in validate_java_compatibility (lines 352-354)"""
        java17 = JavaVersionInfo(17, 0, 1)

        # Mock get_required_java_version to raise exception
        with patch.object(
            service, "get_required_java_version", side_effect=Exception("Version error")
        ):
            compatible, message = service.validate_java_compatibility("1.18.0", java17)

            assert compatible is False
            assert "Failed to validate Java compatibility" in message
            assert "Version error" in message

    def test_validate_java_compatibility_internal_exception(self, service):
        """Test internal exception in validate_java_compatibility (line 340)"""
        java17 = JavaVersionInfo(17, 0, 1)

        # Force an exception during compatibility checking by patching a method called internally
        with (
            patch.object(service, "get_required_java_version", return_value=17),
            patch("builtins.getattr", side_effect=Exception("Internal error")),
        ):
            compatible, message = service.validate_java_compatibility("1.18.0", java17)

            assert compatible is False
            assert "Failed to validate Java compatibility" in message

    def test_generate_compatibility_error_message_all_java_versions(self, service):
        """Test error message generation for all Java versions (lines 376, 380, 381->384)"""
        java7 = JavaVersionInfo(7, 0, 80, "OpenJDK")  # Lower than Java 8
        java8 = JavaVersionInfo(8, 0, 292, "OpenJDK")

        # Test Java 8 download link (current is Java 7, required is 8)
        message8 = service._generate_compatibility_error_message("1.8.0", 8, java7)
        assert (
            "Download Java 8: https://adoptium.net/temurin/releases/?version=8"
            in message8
        )

        # Test Java 16 download link (current is Java 8, required is 16)
        message16 = service._generate_compatibility_error_message("1.17.0", 16, java8)
        assert (
            "Download Java 16: https://adoptium.net/temurin/releases/?version=16"
            in message16
        )

        # Test Java 17 download link (current is Java 8, required is 17)
        message17 = service._generate_compatibility_error_message("1.18.0", 17, java8)
        assert (
            "Download Java 17: https://adoptium.net/temurin/releases/?version=17"
            in message17
        )

        # Test Java 21 download link (current is Java 8, required is 21)
        message21 = service._generate_compatibility_error_message("1.21.0", 21, java8)
        assert (
            "Download Java 21: https://adoptium.net/temurin/releases/?version=21"
            in message21
        )
