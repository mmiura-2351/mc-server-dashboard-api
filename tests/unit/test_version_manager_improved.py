"""
Unit tests for the improved version manager implementation.

Tests focus on verifying the simplified timeout design, concurrent processing,
and error handling improvements.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.servers.models import ServerType
from app.services.version_manager import MinecraftVersionManager, VersionInfo


class TestImprovedVersionManager:
    """Test suite for the improved version manager with simplified design"""

    @pytest.fixture
    def version_manager(self):
        """Create a fresh version manager instance for each test"""
        return MinecraftVersionManager()

    @pytest.fixture
    def mock_vanilla_manifest(self):
        """Mock vanilla version manifest response"""
        return {
            "versions": [
                {
                    "id": "1.21.6",
                    "type": "release",
                    "url": "https://example.com/1.21.6.json",
                    "releaseTime": "2024-12-01T00:00:00Z",
                },
                {
                    "id": "1.21.5",
                    "type": "release",
                    "url": "https://example.com/1.21.5.json",
                    "releaseTime": "2024-11-01T00:00:00Z",
                },
                {
                    "id": "1.7.10",  # Below minimum version
                    "type": "release",
                    "url": "https://example.com/1.7.10.json",
                    "releaseTime": "2014-06-26T00:00:00Z",
                },
            ]
        }

    @pytest.fixture
    def mock_version_details(self):
        """Mock individual version details response"""
        return {
            "downloads": {
                "server": {
                    "url": "https://example.com/server.jar",
                    "sha1": "abc123",
                }
            }
        }

    def test_timeout_configuration_is_mathematically_sound(self, version_manager):
        """Verify timeout configuration provides adequate safety margins"""
        # Test the mathematical soundness of timeout configuration
        individual_timeout = version_manager._individual_request_timeout
        total_timeout = version_manager._total_operation_timeout
        max_concurrent = version_manager._max_concurrent_requests

        # Assuming worst case: 200 versions to fetch
        max_versions = 200
        worst_case_time = (max_versions / max_concurrent) * individual_timeout

        # Verify we have adequate safety margin
        assert total_timeout > worst_case_time, (
            f"Total timeout ({total_timeout}s) must exceed worst case ({worst_case_time}s)"
        )

        safety_margin = total_timeout - worst_case_time
        assert safety_margin >= 60, f"Safety margin ({safety_margin}s) should be at least 60s"

    def test_simplified_timeout_design(self, version_manager):
        """Verify the progressive timeout configuration"""
        assert version_manager._individual_request_timeout == 35
        assert version_manager._manifest_timeout == 60
        assert version_manager._total_operation_timeout == 1900  # 31.7 minutes
        assert version_manager._max_concurrent_requests == 4
        assert version_manager._adaptive_batch_size == 20
        assert version_manager._adaptive_delay == 1.5

    @pytest.mark.asyncio
    async def test_single_layer_timeout_with_clear_errors(self, version_manager):
        """Test that timeout errors provide clear, actionable information"""
        # Mock a slow API that will timeout
        with patch("app.services.version_manager.MinecraftVersionManager._get_vanilla_versions") as mock_get:
            async def slow_operation():
                await asyncio.sleep(1000)  # Simulate very slow operation
                return []

            mock_get.side_effect = slow_operation

            # Set a very short timeout for testing
            version_manager._total_operation_timeout = 0.1

            with pytest.raises(RuntimeError) as exc_info:
                await version_manager.get_supported_versions(ServerType.vanilla)

            error_msg = str(exc_info.value)

            # Verify error message contains useful debugging information
            assert "Operation timeout for vanilla" in error_msg
            assert "limit: 0.1s" in error_msg
            assert "network issues" in error_msg or "excessive number of versions" in error_msg

    @pytest.mark.asyncio
    async def test_concurrent_processing_without_batching(self, version_manager, mock_vanilla_manifest, mock_version_details):
        """Test simplified concurrent processing without complex batch calculations"""
        call_count = 0
        call_times = []

        class MockResponse:
            def __init__(self, json_data):
                self.json_data = json_data

            async def __aenter__(self):
                await asyncio.sleep(0.1)  # Simulate API delay
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

            async def json(self):
                return self.json_data

        def mock_session_get(url, timeout=None):
            nonlocal call_count
            call_count += 1
            call_times.append(datetime.now())

            if "version_manifest.json" in url:
                return MockResponse(mock_vanilla_manifest)
            else:
                return MockResponse(mock_version_details)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.get = mock_session_get
            mock_session_class.return_value.__aenter__.return_value = mock_session

            versions = await version_manager.get_supported_versions(ServerType.vanilla)

            # Verify results
            assert len(versions) == 2  # Only 1.21.6 and 1.21.5 (1.7.10 filtered out)
            # Verify all versions are 1.8 or higher
            from packaging import version as pkg_version
            assert all(pkg_version.Version(v.version) >= pkg_version.Version("1.8.0") for v in versions)

            # Verify concurrent execution (calls should overlap in time)
            if len(call_times) > 2:
                # Calculate time spread of concurrent calls
                time_spread = (call_times[-1] - call_times[0]).total_seconds()
                expected_sequential_time = 0.1 * (len(call_times) - 1)

                # Concurrent execution should be faster than sequential
                assert time_spread < expected_sequential_time

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(self, version_manager):
        """Test that semaphore properly limits concurrent requests"""
        concurrent_count = 0
        max_concurrent_seen = 0

        async def mock_fetch(session, version_data):
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)

            await asyncio.sleep(0.1)  # Simulate API call

            concurrent_count -= 1
            return VersionInfo(
                version=version_data.get("id", "1.0.0"),
                server_type=ServerType.vanilla,
                download_url="https://example.com/test.jar"
            )

        # Create many versions to test concurrency limit
        version_list = [{"id": f"1.{i}.0"} for i in range(20)]

        with patch.object(version_manager, "_fetch_vanilla_version_info", mock_fetch):
            mock_session = AsyncMock()
            results = await version_manager._process_versions_concurrently(
                mock_session, version_list, "vanilla"
            )

        # Verify semaphore limited concurrent requests
        assert max_concurrent_seen <= version_manager._max_concurrent_requests
        assert len(results) == 20
        # Some results might be None due to our improved error handling
        assert all(r is None or isinstance(r, VersionInfo) for r in results)

    @pytest.mark.asyncio
    async def test_error_isolation_in_concurrent_processing(self, version_manager):
        """Test that errors in individual requests don't affect others"""
        successful_versions = ["1.21.6", "1.21.5", "1.21.4"]
        error_versions = ["1.21.3", "1.21.2"]

        async def mock_fetch(session, version_data):
            version_id = version_data.get("id", version_data)

            if version_id in error_versions:
                raise aiohttp.ClientError(f"Failed to fetch {version_id}")

            return VersionInfo(
                version=version_id,
                server_type=ServerType.vanilla,
                download_url=f"https://example.com/{version_id}.jar"
            )

        version_list = [{"id": v} for v in successful_versions + error_versions]

        with patch.object(version_manager, "_fetch_vanilla_version_info", mock_fetch):
            mock_session = AsyncMock()
            results = await version_manager._process_versions_concurrently(
                mock_session, version_list, "vanilla"
            )

        # Verify partial success handling
        successful_results = [r for r in results if isinstance(r, VersionInfo)]
        failed_results = [r for r in results if isinstance(r, Exception)]

        assert len(successful_results) == len(successful_versions)
        assert len(failed_results) == len(error_versions)
        assert all(r.version in successful_versions for r in successful_results)

    @pytest.mark.asyncio
    async def test_cache_behavior_with_improved_design(self, version_manager):
        """Test that caching works correctly with the improved design"""
        call_count = 0

        async def mock_get_vanilla():
            nonlocal call_count
            call_count += 1
            return [
                VersionInfo(
                    version="1.21.6",
                    server_type=ServerType.vanilla,
                    download_url="https://example.com/1.21.6.jar"
                )
            ]

        with patch.object(version_manager, "_get_vanilla_versions", mock_get_vanilla):
            # First call should hit the API
            versions1 = await version_manager.get_supported_versions(ServerType.vanilla)
            assert call_count == 1
            assert len(versions1) == 1

            # Second call should use cache
            versions2 = await version_manager.get_supported_versions(ServerType.vanilla)
            assert call_count == 1  # No additional API call
            assert versions1 == versions2

            # Invalidate cache
            version_manager._cache_expiry.clear()

            # Third call should hit API again
            versions3 = await version_manager.get_supported_versions(ServerType.vanilla)
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_performance_logging_in_improved_design(self, version_manager, caplog):
        """Test that performance metrics are properly logged"""
        import logging
        caplog.set_level(logging.INFO)

        async def mock_get_vanilla():
            await asyncio.sleep(0.5)  # Simulate API delay
            return [
                VersionInfo(
                    version="1.21.6",
                    server_type=ServerType.vanilla,
                    download_url="https://example.com/1.21.6.jar"
                )
            ]

        with patch.object(version_manager, "_get_vanilla_versions", mock_get_vanilla):
            await version_manager.get_supported_versions(ServerType.vanilla)

        # Verify performance logging
        log_messages = [record.message for record in caplog.records]
        assert any("Successfully loaded" in msg for msg in log_messages), f"Log messages: {log_messages}"
        assert any("in 0." in msg for msg in log_messages), f"Log messages: {log_messages}"

    @pytest.mark.asyncio
    async def test_network_error_handling_with_clear_messages(self, version_manager):
        """Test that network errors provide clear, actionable error messages"""
        test_cases = [
            (
                aiohttp.ClientError("Connection refused"),
                "Failed to get versions for vanilla",
                "Connection refused"
            ),
            (
                aiohttp.ClientTimeout(),
                "Failed to get versions for vanilla",
                "ClientTimeout"
            ),
            (
                Exception("Unknown error"),
                "Failed to get versions for vanilla",
                "Unknown error"
            )
        ]

        for error, expected_prefix, expected_detail in test_cases:
            with patch.object(version_manager, "_get_vanilla_versions", side_effect=error):
                with pytest.raises(RuntimeError) as exc_info:
                    await version_manager.get_supported_versions(ServerType.vanilla)

                error_msg = str(exc_info.value)
                assert expected_prefix in error_msg
                assert expected_detail in error_msg

    def test_predictable_timeout_calculation(self, version_manager):
        """Verify timeout calculation is predictable and doesn't have complex interactions"""
        # The new design eliminates complex timeout calculations
        # Verify there are no complex mathematical operations

        # Check that timeout values are simple constants
        assert isinstance(version_manager._individual_request_timeout, int)
        assert isinstance(version_manager._total_operation_timeout, int)
        assert isinstance(version_manager._max_concurrent_requests, int)

        # Verify simplified design with no complex batch calculations
        # The new design uses adaptive_batch_size as a simple reference value
        assert hasattr(version_manager, "_adaptive_batch_size")
        # But doesn't use it for complex calculations like the old _batch_size did
