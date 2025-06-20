import asyncio
import logging
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

    async def get_supported_versions(self, server_type: ServerType) -> List[VersionInfo]:
        """Get supported versions for a server type"""
        cache_key = f"versions_{server_type.value}"

        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        try:
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

        except Exception as e:
            logger.error(f"Failed to get versions for {server_type.value}: {e}")
            # Return fallback versions if API fails
            return self._get_fallback_versions(server_type)

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
        """Get vanilla server versions from Mojang API with parallel processing"""
        async with aiohttp.ClientSession() as session:
            # Get version manifest
            async with session.get(
                "https://piston-meta.mojang.com/mc/game/version_manifest.json"
            ) as response:
                response.raise_for_status()
                manifest = await response.json()

            # Prepare tasks for parallel processing
            release_versions = [
                version_data
                for version_data in manifest["versions"]
                if version_data["type"] == "release"
            ]

            # Create tasks for parallel execution
            tasks = [
                self._fetch_vanilla_version_info(session, version_data)
                for version_data in release_versions
            ]

            # Execute all requests in parallel
            version_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Filter successful results
            versions = []
            for result in version_results:
                if isinstance(result, VersionInfo):
                    versions.append(result)
                elif isinstance(result, Exception):
                    logger.warning(f"Failed to fetch vanilla version: {result}")

            return sorted(
                versions, key=lambda x: version.Version(x.version), reverse=True
            )

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
        """Get Paper server versions from PaperMC API with parallel processing"""
        async with aiohttp.ClientSession() as session:
            # Get available versions
            async with session.get(
                "https://api.papermc.io/v2/projects/paper"
            ) as response:
                response.raise_for_status()
                project_info = await response.json()

            # Create tasks for parallel execution
            tasks = [
                self._fetch_paper_version_info(session, version_id)
                for version_id in project_info["versions"]
            ]

            # Execute all requests in parallel with semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent requests
            limited_tasks = [
                self._fetch_with_semaphore(semaphore, task) for task in tasks
            ]

            version_results = await asyncio.gather(*limited_tasks, return_exceptions=True)

            # Filter successful results
            versions = []
            for result in version_results:
                if isinstance(result, VersionInfo):
                    versions.append(result)
                elif isinstance(result, Exception):
                    logger.warning(f"Failed to fetch paper version: {result}")

            return sorted(
                versions, key=lambda x: version.Version(x.version), reverse=True
            )

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
        except Exception as e:
            logger.warning(f"Failed to get Paper build for version {version_id}: {e}")
            return None

    async def _get_forge_versions(self) -> List[VersionInfo]:
        """Get Forge server versions"""
        # Note: Forge API is more complex, using fallback for now
        # In production, would integrate with Forge's promotion API
        return self._get_fallback_versions(ServerType.forge)

    def _get_fallback_versions(self, server_type: ServerType) -> List[VersionInfo]:
        """Fallback versions when API is unavailable"""
        fallback_data = {
            ServerType.vanilla: [
                (
                    "1.20.4",
                    "https://piston-data.mojang.com/v1/objects/8dd1a28015f51b1803213892b50b7b4fc76e594d/server.jar",
                ),
                (
                    "1.20.1",
                    "https://piston-data.mojang.com/v1/objects/84194a2f286ef7c14ed7ce0090dba59902951553/server.jar",
                ),
                (
                    "1.19.4",
                    "https://piston-data.mojang.com/v1/objects/8f3112a1049751cc472ec13e397eade5336ca7ae/server.jar",
                ),
                (
                    "1.18.2",
                    "https://piston-data.mojang.com/v1/objects/c8f83c5655308435b3dcf03c06d9fe8740a77469/server.jar",
                ),
            ],
            ServerType.paper: [
                (
                    "1.20.4",
                    "https://api.papermc.io/v2/projects/paper/versions/1.20.4/builds/497/downloads/paper-1.20.4-497.jar",
                ),
                (
                    "1.20.1",
                    "https://api.papermc.io/v2/projects/paper/versions/1.20.1/builds/196/downloads/paper-1.20.1-196.jar",
                ),
                (
                    "1.19.4",
                    "https://api.papermc.io/v2/projects/paper/versions/1.19.4/builds/550/downloads/paper-1.19.4-550.jar",
                ),
                (
                    "1.18.2",
                    "https://api.papermc.io/v2/projects/paper/versions/1.18.2/builds/388/downloads/paper-1.18.2-388.jar",
                ),
            ],
            ServerType.forge: [
                (
                    "1.20.1",
                    "https://maven.minecraftforge.net/net/minecraftforge/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0-installer.jar",
                ),
                (
                    "1.19.4",
                    "https://maven.minecraftforge.net/net/minecraftforge/forge/1.19.4-45.2.0/forge-1.19.4-45.2.0-installer.jar",
                ),
                (
                    "1.18.2",
                    "https://maven.minecraftforge.net/net/minecraftforge/forge/1.18.2-40.2.0/forge-1.18.2-40.2.0-installer.jar",
                ),
            ],
        }

        versions = []
        for version_str, url in fallback_data.get(server_type, []):
            versions.append(
                VersionInfo(
                    version=version_str,
                    server_type=server_type,
                    download_url=url,
                    is_stable=True,
                )
            )

        return versions

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
