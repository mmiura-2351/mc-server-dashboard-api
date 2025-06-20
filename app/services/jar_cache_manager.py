import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiofiles
import aiohttp

from app.core.exceptions import handle_file_error
from app.servers.models import ServerType

logger = logging.getLogger(__name__)


class JarCacheManager:
    """Efficient JAR file caching system to reduce network traffic"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("cache/jars")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache metadata directory
        self.metadata_dir = self.cache_dir / ".metadata"
        self.metadata_dir.mkdir(exist_ok=True)

        # Cache settings
        self.max_cache_age = timedelta(days=30)
        self.max_cache_size_gb = 10
        self.chunk_size = 8192

    async def get_or_download_jar(
        self, server_type: ServerType, version: str, download_url: str
    ) -> Path:
        """Get JAR from cache or download if not cached/invalid"""
        cache_key = self._generate_cache_key(server_type, version)
        cached_jar_path = self.cache_dir / f"{cache_key}.jar"
        metadata_path = self.metadata_dir / f"{cache_key}.json"

        # Check if cached version exists and is valid
        if await self._is_cache_valid(cached_jar_path, metadata_path, download_url):
            logger.info(f"Using cached JAR for {server_type.value} {version}")
            return cached_jar_path

        # Download and cache the JAR
        logger.info(f"Downloading JAR for {server_type.value} {version}")
        return await self._download_and_cache(
            download_url, cached_jar_path, metadata_path, server_type, version
        )

    async def copy_jar_to_server(self, cached_jar_path: Path, server_dir: Path) -> Path:
        """Copy cached JAR to server directory"""
        try:
            server_jar_path = server_dir / "server.jar"

            # Use async file copy for large files
            await self._async_copy_file(cached_jar_path, server_jar_path)

            logger.info(f"Copied JAR from cache to {server_jar_path}")
            return server_jar_path

        except Exception as e:
            handle_file_error("copy jar to server", str(server_dir), e)

    async def cleanup_old_cache(self) -> None:
        """Clean up old cache files and manage cache size"""
        try:
            current_time = datetime.now()
            total_size = 0
            cache_files = []

            # Collect all cache files with their metadata
            for jar_file in self.cache_dir.glob("*.jar"):
                if jar_file.is_file():
                    metadata_file = self.metadata_dir / f"{jar_file.stem}.json"

                    try:
                        stat = jar_file.stat()
                        file_age = current_time - datetime.fromtimestamp(stat.st_mtime)
                        file_size = stat.st_size

                        cache_files.append(
                            {
                                "path": jar_file,
                                "metadata_path": metadata_file,
                                "age": file_age,
                                "size": file_size,
                                "last_modified": stat.st_mtime,
                            }
                        )

                        total_size += file_size

                    except Exception as e:
                        logger.warning(f"Failed to get stats for {jar_file}: {e}")

            # Remove files older than max age
            files_removed = 0
            for file_info in cache_files:
                if file_info["age"] > self.max_cache_age:
                    await self._remove_cached_file(
                        file_info["path"], file_info["metadata_path"]
                    )
                    total_size -= file_info["size"]
                    files_removed += 1

            # If cache is still too large, remove oldest files
            max_size_bytes = self.max_cache_size_gb * 1024 * 1024 * 1024
            if total_size > max_size_bytes:
                # Sort remaining files by last modified (oldest first)
                remaining_files = [
                    f for f in cache_files if f["age"] <= self.max_cache_age
                ]
                remaining_files.sort(key=lambda x: x["last_modified"])

                for file_info in remaining_files:
                    if total_size <= max_size_bytes:
                        break

                    await self._remove_cached_file(
                        file_info["path"], file_info["metadata_path"]
                    )
                    total_size -= file_info["size"]
                    files_removed += 1

            if files_removed > 0:
                logger.info(f"Cleaned up {files_removed} old cache files")

        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")

    async def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        try:
            total_files = 0
            total_size = 0

            for jar_file in self.cache_dir.glob("*.jar"):
                if jar_file.is_file():
                    total_files += 1
                    total_size += jar_file.stat().st_size

            return {
                "total_files": total_files,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "cache_dir": str(self.cache_dir),
                "max_age_days": self.max_cache_age.days,
                "max_size_gb": self.max_cache_size_gb,
            }

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}

    def _generate_cache_key(self, server_type: ServerType, version: str) -> str:
        """Generate a unique cache key for server type and version"""
        key_string = f"{server_type.value}-{version}"
        # Use hash to handle special characters and ensure consistent naming
        return hashlib.md5(key_string.encode()).hexdigest()[:16]

    async def _is_cache_valid(
        self, jar_path: Path, metadata_path: Path, download_url: str
    ) -> bool:
        """Check if cached JAR is valid"""
        try:
            if not jar_path.exists() or not metadata_path.exists():
                return False

            # Check file age
            file_age = datetime.now() - datetime.fromtimestamp(jar_path.stat().st_mtime)
            if file_age > self.max_cache_age:
                return False

            # Check file integrity
            if not await self._verify_jar_integrity(jar_path):
                logger.warning(f"Cache file integrity check failed: {jar_path}")
                return False

            # Load and verify metadata
            try:
                import json

                async with aiofiles.open(metadata_path, "r") as f:
                    metadata = json.loads(await f.read())

                # Verify URL matches (in case download URL changed)
                if metadata.get("download_url") != download_url:
                    logger.info(f"Download URL changed for cached file: {jar_path}")
                    return False

            except Exception as e:
                logger.warning(f"Failed to read cache metadata: {e}")
                return False

            return True

        except Exception as e:
            logger.warning(f"Cache validation failed for {jar_path}: {e}")
            return False

    async def _verify_jar_integrity(self, jar_path: Path) -> bool:
        """Verify JAR file integrity"""
        try:
            # Basic checks
            if jar_path.stat().st_size < 1000:  # Too small to be a valid JAR
                return False

            # Check if it's a valid ZIP file (JAR is a ZIP)
            import zipfile

            try:
                with zipfile.ZipFile(jar_path, "r") as zip_file:
                    # Test the ZIP file integrity
                    zip_file.testzip()
                return True
            except zipfile.BadZipFile:
                return False

        except Exception:
            return False

    async def _download_and_cache(
        self,
        download_url: str,
        jar_path: Path,
        metadata_path: Path,
        server_type: ServerType,
        version: str,
    ) -> Path:
        """Download JAR file and cache it"""
        try:
            # Download to temporary file first
            temp_path = jar_path.with_suffix(".tmp")

            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    response.raise_for_status()

                    # Get content length for progress tracking
                    content_length = response.headers.get("content-length")
                    if content_length:
                        total_size = int(content_length)
                        logger.info(
                            f"Downloading {total_size / (1024 * 1024):.1f}MB JAR file"
                        )

                    # Download with progress tracking
                    downloaded = 0
                    async with aiofiles.open(temp_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(self.chunk_size):
                            await f.write(chunk)
                            downloaded += len(chunk)

                            # Log progress every 10MB
                            if content_length and downloaded % (10 * 1024 * 1024) == 0:
                                progress = (downloaded / total_size) * 100
                                logger.info(f"Download progress: {progress:.1f}%")

            # Verify downloaded file
            if not await self._verify_jar_integrity(temp_path):
                temp_path.unlink()
                raise ValueError("Downloaded JAR file failed integrity check")

            # Move to final location
            temp_path.rename(jar_path)

            # Create metadata
            metadata = {
                "server_type": server_type.value,
                "version": version,
                "download_url": download_url,
                "downloaded_at": datetime.now().isoformat(),
                "file_size": jar_path.stat().st_size,
            }

            import json

            async with aiofiles.open(metadata_path, "w") as f:
                await f.write(json.dumps(metadata, indent=2))

            logger.info(f"Successfully cached JAR: {server_type.value} {version}")
            return jar_path

        except Exception as e:
            # Cleanup on failure
            for path in [temp_path, jar_path, metadata_path]:
                if path.exists():
                    try:
                        path.unlink()
                    except Exception:
                        pass

            handle_file_error("download and cache JAR", download_url, e)

    async def _async_copy_file(self, src: Path, dst: Path) -> None:
        """Async file copy for large files"""
        async with aiofiles.open(src, "rb") as src_file:
            async with aiofiles.open(dst, "wb") as dst_file:
                while True:
                    chunk = await src_file.read(self.chunk_size)
                    if not chunk:
                        break
                    await dst_file.write(chunk)

    async def _remove_cached_file(self, jar_path: Path, metadata_path: Path) -> None:
        """Remove cached file and its metadata"""
        try:
            if jar_path.exists():
                jar_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()
            logger.debug(f"Removed cached file: {jar_path}")
        except Exception as e:
            logger.warning(f"Failed to remove cached file {jar_path}: {e}")


# Global instance
jar_cache_manager = JarCacheManager()
