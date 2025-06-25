import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import aiohttp
from packaging import version

from app.servers.models import ServerType

logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """Minecraft version information"""

    version: str
    server_type: ServerType
    download_url: str
    release_date: Optional[datetime] = None
    is_stable: bool = True
    build_number: Optional[int] = None


class MinecraftVersionManager:
    """Dynamic version management with API integration"""

    def __init__(self):
        self._cache = {}
        self._cache_expiry = {}
        self._cache_duration = timedelta(hours=6)  # Cache for 6 hours
        self.minimum_version = version.Version("1.8.0")

        # Simple timeout configuration
        self._request_timeout = 30  # Individual request timeout in seconds
        self._total_timeout = 60  # Total operation timeout in seconds
        self._client_timeout = aiohttp.ClientTimeout(
            total=self._request_timeout, connect=10, sock_read=10
        )

    async def get_supported_versions(self, server_type: ServerType) -> List[VersionInfo]:
        """Get supported versions for a server type"""
        cache_key = f"versions_{server_type.value}"

        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        try:
            # Wrap the entire API operation with overall timeout
            async with asyncio.timeout(self._total_timeout):
                if server_type == ServerType.vanilla:
                    versions = await self._get_vanilla_versions()
                elif server_type == ServerType.paper:
                    versions = await self._get_paper_versions()
                elif server_type == ServerType.forge:
                    versions = await self._get_forge_versions()
                else:
                    raise ValueError(f"Unsupported server type: {server_type}")

                # Filter versions >= 1.8
                filtered_versions = [
                    v for v in versions if self._is_version_supported(v.version)
                ]

                self._cache[cache_key] = filtered_versions
                self._cache_expiry[cache_key] = datetime.now() + self._cache_duration

                logger.info(
                    f"Loaded {len(filtered_versions)} supported versions for {server_type.value}"
                )
                return filtered_versions

        except asyncio.TimeoutError as e:
            error_msg = f"Timeout getting versions for {server_type.value} after {self._total_timeout}s"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to get versions for {server_type.value}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def get_download_url(
        self, server_type: ServerType, minecraft_version: str
    ) -> str:
        """Get download URL for specific version"""
        versions = await self.get_supported_versions(server_type)

        for version_info in versions:
            if version_info.version == minecraft_version:
                return version_info.download_url

        raise ValueError(f"Version {minecraft_version} not found for {server_type.value}")

    def is_version_supported(
        self, server_type: ServerType, minecraft_version: str
    ) -> bool:
        """Check if version is supported (1.8+)"""
        try:
            return self._is_version_supported(minecraft_version)
        except Exception:
            return False

    async def _get_vanilla_versions(self) -> List[VersionInfo]:
        """Get vanilla server versions from Mojang API"""
        async with aiohttp.ClientSession(timeout=self._client_timeout) as session:
            try:
                # Get version manifest
                async with session.get(
                    "https://piston-meta.mojang.com/mc/game/version_manifest.json"
                ) as response:
                    response.raise_for_status()
                    manifest = await response.json()

                # Process release versions
                release_versions = [
                    version_data
                    for version_data in manifest["versions"]
                    if version_data["type"] == "release"
                ]

                logger.debug(f"Found {len(release_versions)} vanilla release versions")

                # Create tasks for parallel execution
                tasks = [
                    self._fetch_vanilla_version_info(session, version_data)
                    for version_data in release_versions
                ]

                # Execute requests with semaphore for rate limiting
                semaphore = asyncio.Semaphore(10)
                limited_tasks = [
                    self._fetch_with_semaphore(semaphore, task) for task in tasks
                ]

                try:
                    version_results = await asyncio.wait_for(
                        asyncio.gather(*limited_tasks, return_exceptions=True),
                        timeout=self._total_timeout - 5,  # Reserve 5s for manifest fetch
                    )
                except asyncio.TimeoutError:
                    logger.error("Timeout during vanilla version parallel processing")
                    raise

                # Filter successful results
                versions = []
                for result in version_results:
                    if isinstance(result, VersionInfo):
                        versions.append(result)
                    elif isinstance(result, Exception):
                        logger.warning(f"Failed to fetch vanilla version: {result}")

                logger.info(f"Successfully processed {len(versions)} vanilla versions")
                return sorted(
                    versions, key=lambda x: version.Version(x.version), reverse=True
                )

            except aiohttp.ClientError as e:
                logger.error(f"HTTP client error fetching vanilla versions: {e}")
                raise
            except asyncio.TimeoutError:
                logger.error("Timeout fetching vanilla version manifest")
                raise
            except Exception as e:
                logger.error(f"Error fetching vanilla versions: {e}")
                raise

    async def _fetch_vanilla_version_info(
        self, session: aiohttp.ClientSession, version_data: dict
    ) -> Optional[VersionInfo]:
        """Fetch individual vanilla version info"""
        try:
            version_id = version_data["id"]

            # Get specific version info for download URL
            async with session.get(version_data["url"]) as version_response:
                version_response.raise_for_status()
                version_info = await version_response.json()

                if "downloads" in version_info and "server" in version_info["downloads"]:
                    download_url = version_info["downloads"]["server"]["url"]
                    release_date = datetime.fromisoformat(
                        version_data["releaseTime"].replace("Z", "+00:00")
                    )

                    return VersionInfo(
                        version=version_id,
                        server_type=ServerType.vanilla,
                        download_url=download_url,
                        release_date=release_date,
                        is_stable=True,
                    )
        except Exception as e:
            logger.warning(
                f"Failed to fetch vanilla version {version_data.get('id', 'unknown')}: {e}"
            )
            return None

    async def _get_paper_versions(self) -> List[VersionInfo]:
        """Get Paper server versions from PaperMC API"""
        async with aiohttp.ClientSession(timeout=self._client_timeout) as session:
            try:
                # Get available versions
                async with session.get(
                    "https://api.papermc.io/v2/projects/paper"
                ) as response:
                    response.raise_for_status()
                    project_info = await response.json()

                logger.debug(f"Found {len(project_info['versions'])} paper versions")

                # Create tasks for parallel execution
                tasks = [
                    self._fetch_paper_version_info(session, version_id)
                    for version_id in project_info["versions"]
                ]

                # Execute requests with semaphore for rate limiting
                semaphore = asyncio.Semaphore(10)
                limited_tasks = [
                    self._fetch_with_semaphore(semaphore, task) for task in tasks
                ]

                try:
                    version_results = await asyncio.wait_for(
                        asyncio.gather(*limited_tasks, return_exceptions=True),
                        timeout=self._total_timeout
                        - 5,  # Reserve 5s for project info fetch
                    )
                except asyncio.TimeoutError:
                    logger.error("Timeout during paper version parallel processing")
                    raise

                # Filter successful results
                versions = []
                for result in version_results:
                    if isinstance(result, VersionInfo):
                        versions.append(result)
                    elif isinstance(result, Exception):
                        logger.warning(f"Failed to fetch paper version: {result}")

                logger.info(f"Successfully processed {len(versions)} paper versions")
                return sorted(
                    versions, key=lambda x: version.Version(x.version), reverse=True
                )

            except aiohttp.ClientError as e:
                logger.error(f"HTTP client error fetching paper versions: {e}")
                raise
            except asyncio.TimeoutError:
                logger.error("Timeout fetching paper project info")
                raise
            except Exception as e:
                logger.error(f"Error fetching paper versions: {e}")
                raise

    async def _fetch_with_semaphore(self, semaphore: asyncio.Semaphore, task):
        """Execute task with semaphore to limit concurrent requests"""
        async with semaphore:
            return await task

    async def _fetch_paper_version_info(
        self, session: aiohttp.ClientSession, version_id: str
    ) -> Optional[VersionInfo]:
        """Fetch individual Paper version info"""
        try:
            # Get builds for this version
            builds_url = (
                f"https://api.papermc.io/v2/projects/paper/versions/{version_id}/builds"
            )
            async with session.get(builds_url) as builds_response:
                builds_response.raise_for_status()
                builds_data = await builds_response.json()

            if builds_data["builds"]:
                # Get latest stable build
                latest_build = max(builds_data["builds"], key=lambda x: x["build"])

                download_url = (
                    f"https://api.papermc.io/v2/projects/paper/versions/{version_id}/"
                    f"builds/{latest_build['build']}/downloads/"
                    f"paper-{version_id}-{latest_build['build']}.jar"
                )

                return VersionInfo(
                    version=version_id,
                    server_type=ServerType.paper,
                    download_url=download_url,
                    release_date=datetime.fromisoformat(latest_build["time"]),
                    is_stable=True,
                    build_number=latest_build["build"],
                )
        except aiohttp.ClientError as e:
            logger.warning(
                f"HTTP error fetching Paper build for version {version_id}: {e}"
            )
            return None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching Paper build for version {version_id}")
            return None
        except Exception as e:
            logger.warning(f"Failed to get Paper build for version {version_id}: {e}")
            return None

    async def _get_forge_versions(self) -> List[VersionInfo]:
        """Get Forge server versions from Maven metadata"""
        headers = {
            "User-Agent": "MinecraftServerManager/1.0",
            "Accept-Encoding": "gzip, deflate",
        }
        async with aiohttp.ClientSession(
            timeout=self._client_timeout, headers=headers
        ) as session:
            try:
                # Get Forge Maven metadata
                url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
                async with session.get(url) as response:
                    response.raise_for_status()
                    xml_content = await response.text()

                # Parse XML
                root = ET.fromstring(xml_content)

                # Extract versions
                versions = []
                for version_elem in root.findall(".//version"):
                    version_text = version_elem.text
                    if version_text and "-" in version_text:
                        # Forge versions are in format like '1.20.1-47.2.0'
                        mc_version = version_text.split("-")[0]

                        # Only include versions >= 1.8
                        if self._is_version_supported(mc_version):
                            download_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{version_text}/forge-{version_text}-installer.jar"

                            try:
                                build_number = int(
                                    version_text.split("-")[1].split(".")[0]
                                )
                            except (IndexError, ValueError):
                                build_number = None

                            version_info = VersionInfo(
                                version=mc_version,
                                server_type=ServerType.forge,
                                download_url=download_url,
                                release_date=datetime.now(),
                                is_stable=True,
                                build_number=build_number,
                            )
                            versions.append(version_info)

                # Remove duplicates and keep the highest build number for each MC version
                unique_versions = {}
                for v in versions:
                    if v.version not in unique_versions:
                        unique_versions[v.version] = v
                    else:
                        # Keep the one with higher build number
                        if v.build_number and (
                            not unique_versions[v.version].build_number
                            or v.build_number > unique_versions[v.version].build_number
                        ):
                            unique_versions[v.version] = v

                final_versions = sorted(
                    unique_versions.values(),
                    key=lambda x: version.Version(x.version),
                    reverse=True,
                )

                logger.info(f"Found {len(final_versions)} forge versions")
                return final_versions

            except aiohttp.ClientError as e:
                error_msg = f"HTTP client error fetching forge versions: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e
            except ET.ParseError as e:
                error_msg = f"XML parsing error for forge versions: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e
            except Exception as e:
                error_msg = f"Error processing forge versions: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

    def _is_version_supported(self, minecraft_version: str) -> bool:
        """Check if version meets minimum requirement (1.8+)"""
        try:
            parsed_version = version.Version(minecraft_version)
            return parsed_version >= self.minimum_version
        except Exception:
            return False

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache is still valid"""
        if cache_key not in self._cache_expiry:
            return False
        return datetime.now() < self._cache_expiry[cache_key]

    def _parse_version_tuple(self, version_str: str) -> Tuple[int, int, int]:
        """Parse version string to tuple for comparison"""
        try:
            parsed = version.Version(version_str)
            parts = parsed.release
            return (
                parts[0],
                parts[1] if len(parts) > 1 else 0,
                parts[2] if len(parts) > 2 else 0,
            )
        except Exception:
            return (0, 0, 0)


# Global instance
minecraft_version_manager = MinecraftVersionManager()
