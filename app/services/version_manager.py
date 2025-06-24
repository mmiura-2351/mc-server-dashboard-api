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

        # Progressive timeout configuration for different request types
        self._manifest_timeout = 60  # Manifest/main API calls need more time
        self._individual_request_timeout = 35  # Individual version requests (reduced)
        self._total_operation_timeout = (
            1900  # Total operation timeout (31.7 minutes) - with safety margin
        )
        self._client_timeout = aiohttp.ClientTimeout(
            total=self._individual_request_timeout,
            connect=10,  # Connection timeout
            sock_read=30,  # Socket read timeout
        )

        # Reduced concurrency and retry configuration
        self._max_concurrent_requests = 4  # Reduced to avoid rate limiting
        self._max_retries = 3  # Retry failed requests
        self._retry_delay = 2.0  # Base delay between retries
        self._adaptive_batch_size = 20  # Smaller batches
        self._adaptive_delay = 1.5  # Longer delay between batches

    async def get_supported_versions(self, server_type: ServerType) -> List[VersionInfo]:
        """Get supported versions for a server type"""
        cache_key = f"versions_{server_type.value}"

        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]

        try:
            # Single-layer timeout with clear error reporting
            start_time = datetime.now()

            # Execute version fetching with progressive timeout and retry
            if server_type == ServerType.vanilla:
                versions = await self._execute_with_retry(
                    self._get_vanilla_versions, timeout=self._total_operation_timeout
                )
            elif server_type == ServerType.paper:
                versions = await self._execute_with_retry(
                    self._get_paper_versions, timeout=self._total_operation_timeout
                )
            elif server_type == ServerType.forge:
                versions = await self._execute_with_retry(
                    self._get_forge_versions, timeout=self._total_operation_timeout
                )
            else:
                raise ValueError(f"Unsupported server type: {server_type}")

            # Filter versions >= 1.8
            filtered_versions = [
                v for v in versions if self._is_version_supported(v.version)
            ]

            self._cache[cache_key] = filtered_versions
            self._cache_expiry[cache_key] = datetime.now() + self._cache_duration

            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"Successfully loaded {len(filtered_versions)} supported versions for {server_type.value} "
                f"in {execution_time:.1f}s"
            )
            return filtered_versions

        except asyncio.TimeoutError as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = (
                f"Operation timeout for {server_type.value} after {execution_time:.1f}s "
                f"(limit: {self._total_operation_timeout}s). This may indicate network issues, "
                f"API rate limiting, or temporary external service unavailability."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = f"Failed to get versions for {server_type.value} after {execution_time:.1f}s: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def _execute_with_retry(self, func, timeout: int, max_retries: int = 2):
        """Execute function with retry logic and timeout"""
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return await asyncio.wait_for(func(), timeout=timeout)
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                last_exception = e
                if attempt < max_retries:
                    delay = self._retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"All {max_retries + 1} attempts failed. Last error: {e}"
                    )
                    raise last_exception

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
        # Create optimized connector with better connection pooling
        connector = aiohttp.TCPConnector(
            limit=self._max_concurrent_requests + 3,  # Fewer extra connections
            limit_per_host=self._max_concurrent_requests,
            ttl_dns_cache=600,  # 10 minutes DNS cache
            use_dns_cache=True,
            keepalive_timeout=60,  # Keep connections alive longer
            enable_cleanup_closed=True,  # Clean up closed connections
        )

        async with aiohttp.ClientSession(
            timeout=self._client_timeout, connector=connector
        ) as session:
            try:
                # Get version manifest with extended timeout for main API call
                manifest_timeout = aiohttp.ClientTimeout(total=self._manifest_timeout)
                async with session.get(
                    "https://piston-meta.mojang.com/mc/game/version_manifest.json",
                    timeout=manifest_timeout,
                ) as response:
                    response.raise_for_status()
                    manifest = await response.json()

                # Prepare tasks for parallel processing
                release_versions = [
                    version_data
                    for version_data in manifest["versions"]
                    if version_data["type"] == "release"
                ]

                logger.info(
                    f"Found {len(release_versions)} vanilla release versions to process"
                )

                # Process versions with simplified concurrent processing
                version_results = await self._process_versions_concurrently(
                    session, release_versions, "vanilla"
                )

                # Filter successful results with improved error tolerance
                versions = []
                failed_count = 0
                for result in version_results:
                    if isinstance(result, VersionInfo):
                        versions.append(result)
                    elif result is not None:  # Count non-None failures
                        failed_count += 1
                        logger.debug(f"Failed to fetch vanilla version: {result}")

                # Log success with failure tolerance
                success_rate = (
                    len(versions) / len(release_versions) * 100 if release_versions else 0
                )
                logger.info(
                    f"Processed {len(versions)} vanilla versions ({success_rate:.1f}% success rate), "
                    f"{failed_count} failed - continuing with available versions"
                )
                return sorted(
                    versions, key=lambda x: version.Version(x.version), reverse=True
                )

            except aiohttp.ClientError as e:
                logger.error(
                    f"HTTP client error fetching vanilla manifest from Mojang API: {e}"
                )
                raise RuntimeError(
                    f"Failed to fetch vanilla version manifest: {e}"
                ) from e
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout during vanilla version processing - some requests may have been slow"
                )
                # Return partial results if available, rather than complete failure
                return []  # Graceful degradation

    async def _fetch_vanilla_version_info(
        self, session: aiohttp.ClientSession, version_data: dict
    ) -> Optional[VersionInfo]:
        """Fetch individual vanilla version info"""
        try:
            version_id = version_data["id"]

            # Get specific version info for download URL with timeout
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
        except aiohttp.ClientError as e:
            logger.warning(
                f"HTTP error fetching vanilla version {version_data.get('id', 'unknown')}: {e}"
            )
            return None
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout fetching vanilla version {version_data.get('id', 'unknown')}"
            )
            return None
        except Exception as e:
            logger.warning(
                f"Failed to fetch vanilla version {version_data.get('id', 'unknown')}: {e}"
            )
            return None

    async def _get_paper_versions(self) -> List[VersionInfo]:
        """Get Paper server versions from PaperMC API with parallel processing"""
        # Create optimized connector with better connection pooling
        connector = aiohttp.TCPConnector(
            limit=self._max_concurrent_requests + 3,  # Fewer extra connections
            limit_per_host=self._max_concurrent_requests,
            ttl_dns_cache=600,  # 10 minutes DNS cache
            use_dns_cache=True,
            keepalive_timeout=60,  # Keep connections alive longer
            enable_cleanup_closed=True,  # Clean up closed connections
        )

        async with aiohttp.ClientSession(
            timeout=self._client_timeout, connector=connector
        ) as session:
            try:
                # Get available versions with extended timeout for main API call
                manifest_timeout = aiohttp.ClientTimeout(total=self._manifest_timeout)
                async with session.get(
                    "https://api.papermc.io/v2/projects/paper", timeout=manifest_timeout
                ) as response:
                    response.raise_for_status()
                    project_info = await response.json()

                logger.info(
                    f"Found {len(project_info['versions'])} paper versions to process"
                )

                # Process versions with simplified concurrent processing
                version_results = await self._process_versions_concurrently(
                    session, project_info["versions"], "paper"
                )

                # Filter successful results with improved error tolerance
                versions = []
                failed_count = 0
                for result in version_results:
                    if isinstance(result, VersionInfo):
                        versions.append(result)
                    elif result is not None:  # Count non-None failures
                        failed_count += 1
                        logger.debug(f"Failed to fetch paper version: {result}")

                # Log success with failure tolerance
                success_rate = (
                    len(versions) / len(project_info["versions"]) * 100
                    if project_info["versions"]
                    else 0
                )
                logger.info(
                    f"Processed {len(versions)} paper versions ({success_rate:.1f}% success rate), "
                    f"{failed_count} failed - continuing with available versions"
                )
                return sorted(
                    versions, key=lambda x: version.Version(x.version), reverse=True
                )

            except aiohttp.ClientError as e:
                logger.error(
                    f"HTTP client error fetching paper project info from PaperMC API: {e}"
                )
                raise RuntimeError(
                    f"Failed to fetch paper version project info: {e}"
                ) from e
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout during paper version processing - some requests may have been slow"
                )
                # Return partial results if available, rather than complete failure
                return []  # Graceful degradation

    async def _fetch_with_semaphore(self, semaphore: asyncio.Semaphore, task):
        """Execute task with semaphore to limit concurrent requests"""
        async with semaphore:
            return await task

    async def _process_versions_concurrently(
        self,
        session: aiohttp.ClientSession,
        version_data_list: list,
        server_type_name: str,
    ) -> list:
        """
        Process versions with simplified concurrent control and transparent error handling.

        Uses a straightforward semaphore-based approach without complex batch calculations.

        Args:
            session: aiohttp session for making requests
            version_data_list: List of version data to process
            server_type_name: Name of server type for logging

        Returns:
            List of results (VersionInfo objects or exceptions)
        """
        if not version_data_list:
            return []

        logger.info(
            f"Processing {len(version_data_list)} {server_type_name} versions "
            f"with max {self._max_concurrent_requests} concurrent requests"
        )

        # Create tasks based on server type
        if server_type_name == "vanilla":
            tasks = [
                self._fetch_vanilla_version_info(session, version_data)
                for version_data in version_data_list
            ]
        elif server_type_name == "paper":
            tasks = [
                self._fetch_paper_version_info(session, version_id)
                for version_id in version_data_list
            ]
        else:
            logger.error(f"Unknown server type for processing: {server_type_name}")
            return []

        # Use semaphore to limit concurrent requests (no complex batching)
        semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        limited_tasks = [self._fetch_with_semaphore(semaphore, task) for task in tasks]

        try:
            # Execute all tasks concurrently with semaphore control
            # No complex timeout calculations - just use the individual request timeouts
            logger.debug(
                f"Starting concurrent execution of {len(limited_tasks)} {server_type_name} tasks"
            )

            results = await asyncio.gather(*limited_tasks, return_exceptions=True)

            # Log results summary
            successful_count = sum(1 for r in results if isinstance(r, VersionInfo))
            failed_count = len(results) - successful_count

            logger.info(
                f"Completed {server_type_name} processing: "
                f"{successful_count} successful, {failed_count} failed"
            )

            return results

        except Exception as e:
            logger.error(
                f"Critical error during {server_type_name} concurrent processing: {e}"
            )
            # Return exceptions for all items to maintain structure
            return [e] * len(version_data_list)

    async def _fetch_paper_version_info(
        self, session: aiohttp.ClientSession, version_id: str
    ) -> Optional[VersionInfo]:
        """Fetch individual Paper version info"""
        try:
            # Get builds for this version with timeout
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
        async with aiohttp.ClientSession(timeout=self._client_timeout) as session:
            try:
                # Get Forge Maven metadata with extended timeout
                url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
                manifest_timeout = aiohttp.ClientTimeout(total=self._manifest_timeout)
                async with session.get(url, timeout=manifest_timeout) as response:
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

                        # Only include versions >= 1.8 (matching our minimum requirement)
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

                logger.info(f"Found {len(final_versions)} forge versions to process")
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
                error_msg = (
                    f"Unexpected error processing forge versions: {type(e).__name__}: {e}"
                )
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
