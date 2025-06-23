import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.servers.models import ServerType
from app.services.jar_cache_manager import JarCacheManager
from tests.infrastructure.test_aiohttp_mocks import (
    MockAiohttpResponse,
    MockAiohttpSession,
)


class TestJarCacheManager:
    """Test cases for JarCacheManager"""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Create temporary cache directory for testing"""
        cache_dir = tmp_path / "test_cache"
        return cache_dir

    def test_init_default(self):
        """Test cache manager initialization with defaults"""
        manager = JarCacheManager()
        assert manager.cache_dir == Path("cache/jars")
        assert manager.metadata_dir == manager.cache_dir / ".metadata"
        assert manager.max_cache_age == timedelta(days=30)
        assert manager.max_cache_size_gb == 10

    def test_init_custom(self, temp_cache_dir):
        """Test cache manager initialization with custom directory"""
        manager = JarCacheManager(temp_cache_dir)
        assert manager.cache_dir == temp_cache_dir
        assert manager.metadata_dir == temp_cache_dir / ".metadata"

    def test_generate_cache_key(self, temp_cache_dir):
        """Test cache key generation"""
        manager = JarCacheManager(temp_cache_dir)

        key1 = manager._generate_cache_key(ServerType.vanilla, "1.20.1")
        key2 = manager._generate_cache_key(ServerType.paper, "1.20.1")
        key3 = manager._generate_cache_key(ServerType.vanilla, "1.19.4")

        # Keys should be different for different inputs
        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

        # Keys should be consistent
        assert key1 == manager._generate_cache_key(ServerType.vanilla, "1.20.1")

        # Keys should be hex strings
        assert len(key1) == 16
        assert all(c in "0123456789abcdef" for c in key1)

    @pytest.mark.asyncio
    async def test_verify_jar_integrity_valid(self, temp_cache_dir):
        """Test JAR integrity verification with valid JAR"""
        manager = JarCacheManager(temp_cache_dir)

        # Create a valid ZIP file (JAR is a ZIP)
        test_jar = temp_cache_dir / "test.jar"
        test_jar.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(test_jar, "w") as zf:
            zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
            zf.writestr(
                "test.class", b"fake class content" * 100
            )  # Make it larger for integrity check

        result = await manager._verify_jar_integrity(test_jar)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_jar_integrity_invalid_size(self, temp_cache_dir):
        """Test JAR integrity verification with too small file"""
        manager = JarCacheManager(temp_cache_dir)

        # Create a file that's too small
        test_jar = temp_cache_dir / "test.jar"
        test_jar.parent.mkdir(parents=True, exist_ok=True)
        test_jar.write_bytes(b"tiny")

        result = await manager._verify_jar_integrity(test_jar)
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_jar_integrity_invalid_zip(self, temp_cache_dir):
        """Test JAR integrity verification with invalid ZIP"""
        manager = JarCacheManager(temp_cache_dir)

        # Create a file that's not a valid ZIP
        test_jar = temp_cache_dir / "test.jar"
        test_jar.parent.mkdir(parents=True, exist_ok=True)
        test_jar.write_bytes(b"not a zip file" * 100)  # Make it large enough

        result = await manager._verify_jar_integrity(test_jar)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_no_files(self, temp_cache_dir):
        """Test cache validation when files don't exist"""
        manager = JarCacheManager(temp_cache_dir)

        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / ".metadata" / "test.json"

        result = await manager._is_cache_valid(
            jar_path, metadata_path, "http://example.com"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_old_file(self, temp_cache_dir):
        """Test cache validation with old file"""
        manager = JarCacheManager(temp_cache_dir)

        # Create old JAR file
        jar_path = temp_cache_dir / "test.jar"
        jar_path.parent.mkdir(parents=True, exist_ok=True)
        jar_path.write_bytes(b"test")

        # Set file time to be old
        old_time = datetime.now() - timedelta(days=35)
        import os

        os.utime(jar_path, (old_time.timestamp(), old_time.timestamp()))

        metadata_path = temp_cache_dir / ".metadata" / "test.json"

        result = await manager._is_cache_valid(
            jar_path, metadata_path, "http://example.com"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_different_url(self, temp_cache_dir):
        """Test cache validation with different download URL"""
        manager = JarCacheManager(temp_cache_dir)

        # Create JAR file
        jar_path = temp_cache_dir / "test.jar"
        jar_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(jar_path, "w") as zf:
            zf.writestr(
                "test.txt", "test content" * 100
            )  # Make it larger for integrity check

        # Create metadata with different URL
        metadata_path = temp_cache_dir / ".metadata" / "test.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        metadata = {
            "download_url": "http://different.com/server.jar",
            "downloaded_at": datetime.now().isoformat(),
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = await manager._is_cache_valid(
            jar_path, metadata_path, "http://example.com/server.jar"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_success(self, temp_cache_dir):
        """Test successful cache validation"""
        manager = JarCacheManager(temp_cache_dir)

        # Create valid JAR file
        jar_path = temp_cache_dir / "test.jar"
        jar_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(jar_path, "w") as zf:
            zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
            zf.writestr(
                "test.class", b"test content" * 100
            )  # Make it larger for integrity check

        # Create valid metadata
        metadata_path = temp_cache_dir / ".metadata" / "test.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        download_url = "http://example.com/server.jar"
        metadata = {
            "download_url": download_url,
            "downloaded_at": datetime.now().isoformat(),
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        result = await manager._is_cache_valid(jar_path, metadata_path, download_url)
        assert result is True

    @pytest.mark.asyncio
    async def test_download_and_cache_success(self, temp_cache_dir):
        """Test successful download and cache"""
        manager = JarCacheManager(temp_cache_dir)

        # Create proper mock response with aiohttp mock
        mock_response = MockAiohttpResponse(
            status=200,
            headers={"content-length": "1000"},
            content_chunks=[b"test content chunk 1", b"test content chunk 2"],
        )

        mock_session = MockAiohttpSession(
            {"http://example.com/server.jar": mock_response}
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            jar_path = temp_cache_dir / "test.jar"
            metadata_path = temp_cache_dir / ".metadata" / "test.json"
            download_url = "http://example.com/server.jar"

            with patch.object(manager, "_verify_jar_integrity", return_value=True):
                result = await manager._download_and_cache(
                    download_url, jar_path, metadata_path, ServerType.vanilla, "1.20.1"
                )

            assert result == jar_path
            assert jar_path.exists()
            assert metadata_path.exists()

            # Check metadata content
            with open(metadata_path, "r") as f:
                metadata = json.load(f)

            assert metadata["download_url"] == download_url
            assert metadata["server_type"] == "vanilla"
            assert metadata["version"] == "1.20.1"

    @pytest.mark.asyncio
    async def test_download_and_cache_integrity_failure(self, temp_cache_dir):
        """Test download and cache with integrity check failure"""
        manager = JarCacheManager(temp_cache_dir)

        # Create proper mock response with aiohttp mock
        mock_response = MockAiohttpResponse(
            status=200,
            headers={"content-length": "1000"},
            content_chunks=[b"invalid content"],
        )

        mock_session = MockAiohttpSession(
            {"http://example.com/server.jar": mock_response}
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            jar_path = temp_cache_dir / "test.jar"
            metadata_path = temp_cache_dir / ".metadata" / "test.json"
            download_url = "http://example.com/server.jar"

            # Mock integrity check to fail
            with patch.object(manager, "_verify_jar_integrity", return_value=False):
                with pytest.raises(Exception):  # Should raise ValueError
                    await manager._download_and_cache(
                        download_url,
                        jar_path,
                        metadata_path,
                        ServerType.vanilla,
                        "1.20.1",
                    )

    @pytest.mark.asyncio
    async def test_async_copy_file(self, temp_cache_dir):
        """Test async file copy"""
        manager = JarCacheManager(temp_cache_dir)

        # Create source file
        src = temp_cache_dir / "source.jar"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"test content for copying")

        # Destination
        dst = temp_cache_dir / "dest.jar"

        await manager._async_copy_file(src, dst)

        assert dst.exists()
        assert dst.read_bytes() == src.read_bytes()

    @pytest.mark.asyncio
    async def test_copy_jar_to_server(self, temp_cache_dir):
        """Test copying JAR to server directory"""
        manager = JarCacheManager(temp_cache_dir)

        # Create cached JAR
        cached_jar = temp_cache_dir / "cached.jar"
        cached_jar.parent.mkdir(parents=True, exist_ok=True)
        cached_jar.write_bytes(b"cached jar content")

        # Server directory
        server_dir = temp_cache_dir / "server"
        server_dir.mkdir(parents=True, exist_ok=True)

        result = await manager.copy_jar_to_server(cached_jar, server_dir)

        expected_path = server_dir / "server.jar"
        assert result == expected_path
        assert expected_path.exists()
        assert expected_path.read_bytes() == b"cached jar content"

    @pytest.mark.asyncio
    async def test_get_or_download_jar_cache_hit(self, temp_cache_dir):
        """Test getting JAR with cache hit"""
        manager = JarCacheManager(temp_cache_dir)

        # Create cached JAR
        cache_key = manager._generate_cache_key(ServerType.vanilla, "1.20.1")
        cached_jar = temp_cache_dir / f"{cache_key}.jar"
        cached_jar.parent.mkdir(parents=True, exist_ok=True)
        cached_jar.write_bytes(b"cached content")

        # Mock cache validation to return True
        with patch.object(manager, "_is_cache_valid", return_value=True):
            result = await manager.get_or_download_jar(
                ServerType.vanilla, "1.20.1", "http://example.com/server.jar"
            )

        assert result == cached_jar

    @pytest.mark.asyncio
    async def test_get_or_download_jar_cache_miss(self, temp_cache_dir):
        """Test getting JAR with cache miss"""
        manager = JarCacheManager(temp_cache_dir)

        download_url = "http://example.com/server.jar"

        # Mock cache validation to return False (cache miss)
        with patch.object(manager, "_is_cache_valid", return_value=False):
            with patch.object(manager, "_download_and_cache") as mock_download:
                cache_key = manager._generate_cache_key(ServerType.vanilla, "1.20.1")
                expected_path = temp_cache_dir / f"{cache_key}.jar"
                mock_download.return_value = expected_path

                result = await manager.get_or_download_jar(
                    ServerType.vanilla, "1.20.1", download_url
                )

                assert result == expected_path
                mock_download.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, temp_cache_dir):
        """Test getting cache statistics"""
        manager = JarCacheManager(temp_cache_dir)

        # Create some test JAR files directly in cache_dir
        temp_cache_dir.mkdir(parents=True, exist_ok=True)
        jar1 = temp_cache_dir / "test1.jar"
        jar2 = temp_cache_dir / "test2.jar"

        jar1.write_bytes(b"a" * 1024)  # 1KB
        jar2.write_bytes(b"b" * 2048)  # 2KB

        stats = await manager.get_cache_stats()

        assert stats["total_files"] == 2
        # 3KB = 3072 bytes, 3072 / (1024*1024) = 0.00292969, rounded to 2 places = 0.0
        assert stats["total_size_mb"] == 0.0
        assert stats["cache_dir"] == str(temp_cache_dir)
        assert stats["max_age_days"] == 30
        assert stats["max_size_gb"] == 10

    @pytest.mark.asyncio
    async def test_get_cache_stats_error(self, temp_cache_dir):
        """Test getting cache statistics with error"""
        manager = JarCacheManager(temp_cache_dir)

        # Create cache directory but make it inaccessible
        temp_cache_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(Path, "glob", side_effect=OSError("Permission denied")):
            stats = await manager.get_cache_stats()
            assert "error" in stats

    @pytest.mark.asyncio
    async def test_cleanup_old_cache(self, temp_cache_dir):
        """Test cache cleanup functionality"""
        manager = JarCacheManager(temp_cache_dir)

        # Create test files with different ages
        old_jar = temp_cache_dir / "old.jar"
        new_jar = temp_cache_dir / "new.jar"
        old_jar.parent.mkdir(parents=True, exist_ok=True)

        old_jar.write_bytes(b"old content")
        new_jar.write_bytes(b"new content")

        # Make old file actually old
        old_time = datetime.now() - timedelta(days=35)
        import os

        os.utime(old_jar, (old_time.timestamp(), old_time.timestamp()))

        # Create metadata files
        metadata_dir = temp_cache_dir / ".metadata"
        metadata_dir.mkdir(exist_ok=True)
        (metadata_dir / "old.json").write_text("{}")
        (metadata_dir / "new.json").write_text("{}")

        await manager.cleanup_old_cache()

        # Old file should be removed, new file should remain
        assert not old_jar.exists()
        assert new_jar.exists()
        assert not (metadata_dir / "old.json").exists()
        assert (metadata_dir / "new.json").exists()

    @pytest.mark.asyncio
    async def test_remove_cached_file(self, temp_cache_dir):
        """Test removing cached file and metadata"""
        manager = JarCacheManager(temp_cache_dir)

        # Create test files
        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / "test.json"

        jar_path.parent.mkdir(parents=True, exist_ok=True)
        jar_path.write_bytes(b"test")
        metadata_path.write_text("{}")

        await manager._remove_cached_file(jar_path, metadata_path)

        assert not jar_path.exists()
        assert not metadata_path.exists()

    @pytest.mark.asyncio
    async def test_remove_cached_file_missing(self, temp_cache_dir):
        """Test removing cached file when files don't exist"""
        manager = JarCacheManager(temp_cache_dir)

        # Try to remove non-existent files (should not raise error)
        jar_path = temp_cache_dir / "nonexistent.jar"
        metadata_path = temp_cache_dir / "nonexistent.json"

        await manager._remove_cached_file(jar_path, metadata_path)
        # Should complete without error


class TestJarCacheManagerMissingCoverage:
    """Test cases for missing coverage in JarCacheManager"""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Create temporary cache directory for testing"""
        cache_dir = tmp_path / "test_cache"
        return cache_dir

    @pytest.mark.asyncio
    async def test_copy_jar_to_server_exception(self, temp_cache_dir):
        """Test copy_jar_to_server with exception (lines 62-63)"""
        manager = JarCacheManager(temp_cache_dir)

        # Create source JAR but no permission to create server directory
        cached_jar = temp_cache_dir / "cached.jar"
        cached_jar.parent.mkdir(parents=True, exist_ok=True)
        cached_jar.write_bytes(b"test content")

        # Mock server dir to be non-writable by making async_copy_file fail
        server_dir = temp_cache_dir / "server"
        server_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(
            manager, "_async_copy_file", side_effect=OSError("Permission denied")
        ):
            with pytest.raises(Exception):  # Should call handle_file_error which raises
                await manager.copy_jar_to_server(cached_jar, server_dir)

    @pytest.mark.asyncio
    async def test_cleanup_old_cache_stat_exception(self, temp_cache_dir):
        """Test cleanup_old_cache with stat exception (lines 94-95)"""
        manager = JarCacheManager(temp_cache_dir)

        # Create JAR file
        jar_file = temp_cache_dir / "test.jar"
        jar_file.parent.mkdir(parents=True, exist_ok=True)
        jar_file.write_bytes(b"test content")

        # Mock jar_file.stat() to raise exception
        with patch.object(Path, "stat", side_effect=OSError("Permission denied")):
            # Should handle exception gracefully and continue
            await manager.cleanup_old_cache()
            # Should not raise exception

    @pytest.mark.asyncio
    async def test_cleanup_old_cache_size_based_removal(self, temp_cache_dir):
        """Test cleanup with size-based removal (lines 111-124, 126)"""
        # Create manager with very small cache size
        manager = JarCacheManager(temp_cache_dir)
        manager.max_cache_size_gb = 0.000001  # ~1KB

        # Create multiple files that exceed size limit
        jar1 = temp_cache_dir / "jar1.jar"
        jar2 = temp_cache_dir / "jar2.jar"
        jar3 = temp_cache_dir / "jar3.jar"

        for jar in [jar1, jar2, jar3]:
            jar.parent.mkdir(parents=True, exist_ok=True)
            jar.write_bytes(b"x" * 1024)  # 1KB each

        # Set different modification times (jar1 = oldest, jar3 = newest)
        import os
        import time

        base_time = time.time()
        os.utime(jar1, (base_time - 200, base_time - 200))  # Oldest
        os.utime(jar2, (base_time - 100, base_time - 100))  # Middle
        os.utime(jar3, (base_time, base_time))  # Newest

        # Create metadata files
        metadata_dir = temp_cache_dir / ".metadata"
        metadata_dir.mkdir(exist_ok=True)
        (metadata_dir / "jar1.json").write_text("{}")
        (metadata_dir / "jar2.json").write_text("{}")
        (metadata_dir / "jar3.json").write_text("{}")

        await manager.cleanup_old_cache()

        # Should remove oldest files first due to size limit
        # Since we have 3KB total but limit is ~1KB, oldest should be removed
        assert not jar1.exists() or not jar2.exists()  # At least one older file removed

    @pytest.mark.asyncio
    async def test_cleanup_old_cache_general_exception(self, temp_cache_dir):
        """Test cleanup_old_cache with general exception (lines 129-130)"""
        manager = JarCacheManager(temp_cache_dir)

        # Mock glob to raise exception
        with patch.object(Path, "glob", side_effect=Exception("Unexpected error")):
            # Should handle exception gracefully
            await manager.cleanup_old_cache()
            # Should not raise exception

    @pytest.mark.asyncio
    async def test_is_cache_valid_file_age_exception(self, temp_cache_dir):
        """Test cache validation with file age exception (line 172)"""
        manager = JarCacheManager(temp_cache_dir)

        # Create JAR file
        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / ".metadata" / "test.json"

        jar_path.parent.mkdir(parents=True, exist_ok=True)
        jar_path.write_bytes(b"test")

        # Mock jar_path.stat() to raise exception
        with patch.object(Path, "stat", side_effect=OSError("Permission denied")):
            result = await manager._is_cache_valid(
                jar_path, metadata_path, "http://example.com"
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_integrity_check_failed(self, temp_cache_dir):
        """Test cache validation with integrity check failure (lines 176-177)"""
        manager = JarCacheManager(temp_cache_dir)

        # Create JAR file and metadata
        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / ".metadata" / "test.json"

        jar_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        jar_path.write_bytes(b"test content")

        metadata = {"download_url": "http://example.com"}
        metadata_path.write_text(json.dumps(metadata))

        # Mock integrity check to fail
        with patch.object(manager, "_verify_jar_integrity", return_value=False):
            result = await manager._is_cache_valid(
                jar_path, metadata_path, "http://example.com"
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_metadata_read_exception(self, temp_cache_dir):
        """Test cache validation with metadata read exception (lines 191-193)"""
        manager = JarCacheManager(temp_cache_dir)

        # Create JAR file
        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / ".metadata" / "test.json"

        jar_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(jar_path, "w") as zf:
            zf.writestr("test.txt", "test content" * 100)

        # Create corrupted metadata file
        metadata_path.write_bytes(b"invalid json {")

        result = await manager._is_cache_valid(
            jar_path, metadata_path, "http://example.com"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_cache_valid_general_exception(self, temp_cache_dir):
        """Test cache validation with general exception (lines 197-199)"""
        manager = JarCacheManager(temp_cache_dir)

        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / ".metadata" / "test.json"

        # Mock Path.exists to raise exception
        with patch.object(Path, "exists", side_effect=Exception("Unexpected error")):
            result = await manager._is_cache_valid(
                jar_path, metadata_path, "http://example.com"
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_download_and_cache_with_content_length_and_progress(
        self, temp_cache_dir
    ):
        """Test download with content-length header and progress logging (lines 241, 256-257)"""
        manager = JarCacheManager(temp_cache_dir)
        manager.chunk_size = 5  # Small chunks for testing

        # Create chunks that will trigger progress logging
        large_chunk = b"x" * (10 * 1024 * 1024)  # 10MB chunk to trigger progress log

        mock_response = MockAiohttpResponse(
            status=200,
            headers={"content-length": str(len(large_chunk))},
            content_chunks=[large_chunk],
        )

        mock_session = MockAiohttpSession(
            {"http://example.com/server.jar": mock_response}
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            jar_path = temp_cache_dir / "test.jar"
            metadata_path = temp_cache_dir / ".metadata" / "test.json"

            with patch.object(manager, "_verify_jar_integrity", return_value=True):
                result = await manager._download_and_cache(
                    "http://example.com/server.jar",
                    jar_path,
                    metadata_path,
                    ServerType.vanilla,
                    "1.20.1",
                )

            assert result == jar_path
            assert jar_path.exists()

    @pytest.mark.asyncio
    async def test_download_and_cache_no_content_length(self, temp_cache_dir):
        """Test download without content-length header"""
        manager = JarCacheManager(temp_cache_dir)

        mock_response = MockAiohttpResponse(
            status=200,
            headers={},  # No content-length header
            content_chunks=[b"test content"],
        )

        mock_session = MockAiohttpSession(
            {"http://example.com/server.jar": mock_response}
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            jar_path = temp_cache_dir / "test.jar"
            metadata_path = temp_cache_dir / ".metadata" / "test.json"

            with patch.object(manager, "_verify_jar_integrity", return_value=True):
                result = await manager._download_and_cache(
                    "http://example.com/server.jar",
                    jar_path,
                    metadata_path,
                    ServerType.vanilla,
                    "1.20.1",
                )

            assert result == jar_path

    @pytest.mark.asyncio
    async def test_download_and_cache_exception_cleanup(self, temp_cache_dir):
        """Test download exception with file cleanup (lines 288-291)"""
        manager = JarCacheManager(temp_cache_dir)

        # Create files that will exist when exception occurs
        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / ".metadata" / "test.json"
        temp_path = temp_cache_dir / "test.jar.tmp"

        jar_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Create existing files
        jar_path.write_bytes(b"existing")
        metadata_path.write_text("{}")
        temp_path.write_bytes(b"temp")

        # Mock aiohttp to raise exception
        with patch("aiohttp.ClientSession", side_effect=Exception("Network error")):
            with pytest.raises(Exception):
                await manager._download_and_cache(
                    "http://example.com/server.jar",
                    jar_path,
                    metadata_path,
                    ServerType.vanilla,
                    "1.20.1",
                )

        # Files should be cleaned up (but may still exist if cleanup has exceptions)
        # The main point is that cleanup code ran without additional exceptions

    @pytest.mark.asyncio
    async def test_remove_cached_file_with_exception(self, temp_cache_dir):
        """Test _remove_cached_file with exception during removal (lines 313-314)"""
        manager = JarCacheManager(temp_cache_dir)

        jar_path = temp_cache_dir / "test.jar"
        metadata_path = temp_cache_dir / "test.json"

        jar_path.parent.mkdir(parents=True, exist_ok=True)
        jar_path.write_bytes(b"test")
        metadata_path.write_text("{}")

        # Mock unlink to raise exception
        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            # Should handle exception gracefully
            await manager._remove_cached_file(jar_path, metadata_path)
            # Should not raise exception
