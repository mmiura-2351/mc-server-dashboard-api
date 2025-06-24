from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.servers.models import ServerType
from app.services.version_manager import MinecraftVersionManager, VersionInfo
from tests.infrastructure.test_aiohttp_mocks import (
    MockAiohttpResponse,
    MockAiohttpSession,
)


class TestMinecraftVersionManager:
    """Test cases for MinecraftVersionManager"""

    def test_init(self):
        """Test version manager initialization"""
        manager = MinecraftVersionManager()
        assert manager._cache == {}
        assert manager._cache_expiry == {}
        assert manager.minimum_version.base_version == "1.8.0"

    def test_is_version_supported_valid(self):
        """Test version support validation with valid versions"""
        manager = MinecraftVersionManager()

        assert manager.is_version_supported(ServerType.vanilla, "1.20.1") is True
        assert manager.is_version_supported(ServerType.paper, "1.19.4") is True
        assert manager.is_version_supported(ServerType.forge, "1.18.2") is True
        assert manager.is_version_supported(ServerType.vanilla, "1.8.0") is True

    def test_is_version_supported_invalid(self):
        """Test version support validation with invalid versions"""
        manager = MinecraftVersionManager()

        assert manager.is_version_supported(ServerType.vanilla, "1.7.10") is False
        assert manager.is_version_supported(ServerType.paper, "1.6.4") is False
        assert manager.is_version_supported(ServerType.forge, "invalid") is False

    def test_is_cache_valid_no_cache(self):
        """Test cache validation with no cache"""
        manager = MinecraftVersionManager()
        assert manager._is_cache_valid("test_key") is False

    def test_is_cache_valid_expired(self):
        """Test cache validation with expired cache"""
        manager = MinecraftVersionManager()
        manager._cache_expiry["test_key"] = datetime.now() - timedelta(hours=1)
        assert manager._is_cache_valid("test_key") is False

    def test_is_cache_valid_current(self):
        """Test cache validation with current cache"""
        manager = MinecraftVersionManager()
        manager._cache_expiry["test_key"] = datetime.now() + timedelta(hours=1)
        assert manager._is_cache_valid("test_key") is True

    @pytest.mark.asyncio
    async def test_get_vanilla_versions_success(self):
        """Test getting vanilla versions successfully"""
        manager = MinecraftVersionManager()

        # Mock version manifest
        manifest_data = {
            "versions": [
                {
                    "id": "1.20.1",
                    "type": "release",
                    "url": "https://example.com/1.20.1.json",
                    "releaseTime": "2023-06-12T10:30:00Z",
                }
            ]
        }

        # Mock version specific data
        version_data = {
            "downloads": {"server": {"url": "https://example.com/server.jar"}}
        }

        # Create proper mock responses
        manifest_response = MockAiohttpResponse(status=200, json_data=manifest_data)
        version_response = MockAiohttpResponse(status=200, json_data=version_data)

        mock_session = MockAiohttpSession(
            {
                "https://piston-meta.mojang.com/mc/game/version_manifest.json": manifest_response,
                "https://example.com/1.20.1.json": version_response,
            }
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            versions = await manager._get_vanilla_versions()

            assert len(versions) == 1
            assert versions[0].version == "1.20.1"
            assert versions[0].server_type == ServerType.vanilla
            assert versions[0].download_url == "https://example.com/server.jar"

    @pytest.mark.asyncio
    async def test_get_paper_versions_success(self):
        """Test getting Paper versions successfully"""
        manager = MinecraftVersionManager()

        # Mock project info
        project_data = {"versions": ["1.20.1", "1.19.4"]}

        # Mock builds data
        builds_data = {"builds": [{"build": 196, "time": "2023-06-12T10:30:00Z"}]}

        # Create proper mock responses
        project_response = MockAiohttpResponse(status=200, json_data=project_data)
        builds_response = MockAiohttpResponse(status=200, json_data=builds_data)

        mock_session = MockAiohttpSession(
            {
                "https://api.papermc.io/v2/projects/paper": project_response,
                "https://api.papermc.io/v2/projects/paper/versions/1.20.1/builds": builds_response,
                "https://api.papermc.io/v2/projects/paper/versions/1.19.4/builds": builds_response,
            }
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            versions = await manager._get_paper_versions()

            assert len(versions) == 2
            assert all(v.server_type == ServerType.paper for v in versions)
            assert versions[0].build_number == 196


    @pytest.mark.asyncio
    async def test_get_supported_versions_with_cache(self):
        """Test getting supported versions with cache hit"""
        manager = MinecraftVersionManager()

        # Populate cache
        cached_versions = [
            VersionInfo(
                version="1.20.1",
                server_type=ServerType.vanilla,
                download_url="https://example.com/server.jar",
            )
        ]
        cache_key = f"versions_{ServerType.vanilla.value}"
        manager._cache[cache_key] = cached_versions
        manager._cache_expiry[cache_key] = datetime.now() + timedelta(hours=1)

        result = await manager.get_supported_versions(ServerType.vanilla)

        assert result == cached_versions

    @pytest.mark.asyncio
    async def test_get_supported_versions_api_failure_raises_exception(self):
        """Test getting supported versions when API fails, should raise exception"""
        manager = MinecraftVersionManager()

        with patch.object(
            manager, "_get_vanilla_versions", side_effect=Exception("API Error")
        ):
            with pytest.raises(RuntimeError, match="Failed to get versions for vanilla"):
                await manager.get_supported_versions(ServerType.vanilla)

    @pytest.mark.asyncio
    async def test_get_download_url_success(self):
        """Test getting download URL successfully"""
        manager = MinecraftVersionManager()

        # Mock cache with versions
        versions = [
            VersionInfo(
                version="1.20.1",
                server_type=ServerType.vanilla,
                download_url="https://example.com/server.jar",
            )
        ]

        with patch.object(manager, "get_supported_versions", return_value=versions):
            url = await manager.get_download_url(ServerType.vanilla, "1.20.1")
            assert url == "https://example.com/server.jar"

    @pytest.mark.asyncio
    async def test_get_download_url_not_found(self):
        """Test getting download URL for non-existent version"""
        manager = MinecraftVersionManager()

        # Mock empty versions list
        with patch.object(manager, "get_supported_versions", return_value=[]):
            with pytest.raises(ValueError, match="Version .* not found"):
                await manager.get_download_url(ServerType.vanilla, "1.20.1")

    def test_is_version_supported_internal_valid(self):
        """Test internal version support check with valid versions"""
        manager = MinecraftVersionManager()

        assert manager._is_version_supported("1.20.1") is True
        assert manager._is_version_supported("1.8.0") is True
        assert manager._is_version_supported("1.19.4") is True

    def test_is_version_supported_internal_invalid(self):
        """Test internal version support check with invalid versions"""
        manager = MinecraftVersionManager()

        assert manager._is_version_supported("1.7.10") is False
        assert manager._is_version_supported("invalid") is False
        assert manager._is_version_supported("") is False

    def test_parse_version_tuple_valid(self):
        """Test version tuple parsing with valid versions"""
        manager = MinecraftVersionManager()

        assert manager._parse_version_tuple("1.20.1") == (1, 20, 1)
        assert manager._parse_version_tuple("1.19") == (1, 19, 0)
        assert manager._parse_version_tuple("2.0.0") == (2, 0, 0)

    def test_parse_version_tuple_invalid(self):
        """Test version tuple parsing with invalid versions"""
        manager = MinecraftVersionManager()

        assert manager._parse_version_tuple("invalid") == (0, 0, 0)
        assert manager._parse_version_tuple("") == (0, 0, 0)
        assert manager._parse_version_tuple("1.x.y") == (0, 0, 0)


class TestVersionInfo:
    """Test cases for VersionInfo dataclass"""

    def test_version_info_creation(self):
        """Test VersionInfo creation"""
        version_info = VersionInfo(
            version="1.20.1",
            server_type=ServerType.vanilla,
            download_url="https://example.com/server.jar",
            release_date=datetime.now(),
            is_stable=True,
            build_number=196,
        )

        assert version_info.version == "1.20.1"
        assert version_info.server_type == ServerType.vanilla
        assert version_info.download_url == "https://example.com/server.jar"
        assert version_info.is_stable is True
        assert version_info.build_number == 196

    def test_version_info_minimal(self):
        """Test VersionInfo with minimal required fields"""
        version_info = VersionInfo(
            version="1.20.1",
            server_type=ServerType.vanilla,
            download_url="https://example.com/server.jar",
        )

        assert version_info.version == "1.20.1"
        assert version_info.server_type == ServerType.vanilla
        assert version_info.download_url == "https://example.com/server.jar"
        assert version_info.release_date is None
        assert version_info.is_stable is True  # Default value
        assert version_info.build_number is None


class TestMinecraftVersionManagerMissingCoverage:
    """Test cases for missing coverage in MinecraftVersionManager"""

    @pytest.fixture
    def manager(self):
        """Create a test manager instance"""
        return MinecraftVersionManager()

    @pytest.mark.asyncio
    async def test_get_supported_versions_forge_type(self, manager):
        """Test get_supported_versions with forge server type (lines 48-49)"""
        # Mock _get_forge_versions to return test data
        with patch.object(manager, "_get_forge_versions") as mock_forge:
            forge_versions = [
                VersionInfo(
                    "1.20.1", ServerType.forge, "http://forge.url", is_stable=True
                ),
                VersionInfo(
                    "1.19.4", ServerType.forge, "http://forge.url2", is_stable=True
                ),
            ]
            mock_forge.return_value = forge_versions

            result = await manager.get_supported_versions(ServerType.forge)

            assert len(result) == 2
            assert all(v.server_type == ServerType.forge for v in result)
            mock_forge.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_supported_versions_unsupported_type(self, manager):
        """Test get_supported_versions with unsupported server type (line 51)"""

        # Create a mock ServerType that's not handled - directly call with invalid type
        class FakeServerType:
            def __init__(self, value):
                self.value = value

            def __eq__(self, other):
                return False  # Won't match any of vanilla, paper, forge

        unknown_type = FakeServerType("unknown")

        # Should raise RuntimeError due to ValueError in get_supported_versions
        with pytest.raises(RuntimeError, match="Failed to get versions for unknown"):
            await manager.get_supported_versions(unknown_type)

    @pytest.mark.asyncio
    async def test_get_supported_versions_exception_raises_error(self, manager):
        """Test get_supported_versions exception handling raises RuntimeError"""
        with patch.object(
            manager, "_get_vanilla_versions", side_effect=Exception("API Error")
        ):
            with pytest.raises(RuntimeError, match="Failed to get versions for vanilla"):
                await manager.get_supported_versions(ServerType.vanilla)

    @pytest.mark.asyncio
    async def test_get_download_url_version_not_found(self, manager):
        """Test get_download_url when version not found (lines 78->81)"""
        # Mock get_supported_versions to return versions without the requested one
        with patch.object(manager, "get_supported_versions") as mock_get_versions:
            available_versions = [
                VersionInfo(
                    "1.20.1", ServerType.vanilla, "http://example.com/1.20.1.jar"
                ),
                VersionInfo(
                    "1.19.4", ServerType.vanilla, "http://example.com/1.19.4.jar"
                ),
            ]
            mock_get_versions.return_value = available_versions

            with pytest.raises(ValueError) as exc_info:
                await manager.get_download_url(ServerType.vanilla, "1.18.2")

            assert "Version 1.18.2 not found for vanilla" in str(exc_info.value)

    def test_is_version_supported_exception_handling(self, manager):
        """Test is_version_supported exception handling (lines 89-90)"""
        # Mock _is_version_supported to raise exception
        with patch.object(
            manager, "_is_version_supported", side_effect=Exception("Version error")
        ):
            result = manager.is_version_supported(ServerType.vanilla, "1.20.1")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_vanilla_versions_exception_in_parallel_processing(self, manager):
        """Test _get_vanilla_versions with exception in parallel processing (lines 123-124)"""
        # Use the existing test infrastructure
        mock_response = MockAiohttpResponse(
            status=200,
            json_data={
                "versions": [
                    {"id": "1.20.1", "type": "release", "url": "http://test.url"}
                ]
            },
        )

        mock_session = MockAiohttpSession(
            {
                "https://piston-meta.mojang.com/mc/game/version_manifest.json": mock_response
            }
        )

        # Mock gather to return an exception using AsyncMock
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
                mock_gather.return_value = [Exception("Network error")]
                result = await manager._get_vanilla_versions()

                # Should return empty list when all tasks fail
                assert result == []

    @pytest.mark.asyncio
    async def test_fetch_vanilla_version_info_no_server_download(self, manager):
        """Test _fetch_vanilla_version_info when no server download available (lines 142->exit)"""
        version_data = {
            "id": "1.20.1",
            "url": "http://test.url",
            "releaseTime": "2023-01-01T00:00:00Z",
        }

        # Mock version response without server downloads
        mock_response = MockAiohttpResponse(
            status=200, json_data={"downloads": {"client": {"url": "http://client.jar"}}}
        )

        mock_session = MockAiohttpSession({"http://test.url": mock_response})

        result = await manager._fetch_vanilla_version_info(mock_session, version_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_vanilla_version_info_exception_handling(self, manager):
        """Test _fetch_vanilla_version_info exception handling (lines 155-159)"""
        version_data = {"id": "1.20.1", "url": "http://test.url"}

        # Mock session to raise exception on get
        mock_session = MockAiohttpSession({})
        mock_session.get = Mock(side_effect=Exception("Network error"))

        result = await manager._fetch_vanilla_version_info(mock_session, version_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_paper_versions_exception_in_parallel_processing(self, manager):
        """Test _get_paper_versions with exception in parallel processing (lines 190-191)"""
        # Mock project info response
        mock_response = MockAiohttpResponse(
            status=200, json_data={"versions": ["1.20.1", "1.19.4"]}
        )

        mock_session = MockAiohttpSession(
            {"https://api.papermc.io/v2/projects/paper": mock_response}
        )

        # Mock gather to return exceptions using AsyncMock
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
                mock_gather.return_value = [
                    Exception("Network error"),
                    Exception("Another error"),
                ]
                result = await manager._get_paper_versions()

                # Should return empty list when all tasks fail
                assert result == []

    @pytest.mark.asyncio
    async def test_fetch_paper_version_info_no_builds(self, manager):
        """Test _fetch_paper_version_info when no builds available (lines 215->exit)"""
        version_id = "1.20.1"

        # Mock builds response with empty builds
        mock_response = MockAiohttpResponse(status=200, json_data={"builds": []})

        mock_session = MockAiohttpSession(
            {
                f"https://api.papermc.io/v2/projects/paper/versions/{version_id}/builds": mock_response
            }
        )

        result = await manager._fetch_paper_version_info(mock_session, version_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_paper_version_info_exception_handling(self, manager):
        """Test _fetch_paper_version_info exception handling (lines 233-235)"""
        version_id = "1.20.1"

        # Mock session to raise exception on get
        mock_session = MockAiohttpSession({})
        mock_session.get = Mock(side_effect=Exception("Network error"))

        result = await manager._fetch_paper_version_info(mock_session, version_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_forge_versions_success(self, manager):
        """Test _get_forge_versions returns real API versions"""
        result = await manager._get_forge_versions()

        # Should return real versions from Forge API, not fallback
        assert len(result) > 3  # More than the 3 fallback versions
        assert all(v.server_type == ServerType.forge for v in result)
        assert all(v.download_url.startswith("https://maven.minecraftforge.net") for v in result)

    @pytest.mark.asyncio
    async def test_get_forge_versions_raises_error_on_failure(self, manager):
        """Test _get_forge_versions raises RuntimeError when API fails"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            # Create a mock session that raises an exception during get()
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session

            # Make session.get() raise an aiohttp.ClientError
            from aiohttp import ClientError
            mock_session.get.side_effect = ClientError("API Error")

            with pytest.raises(RuntimeError, match="Error parsing forge versions"):
                await manager._get_forge_versions()
