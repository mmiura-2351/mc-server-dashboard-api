import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta

from app.services.version_manager import MinecraftVersionManager, VersionInfo
from app.servers.models import ServerType
from tests.infrastructure.test_aiohttp_mocks import MockAiohttpResponse, MockAiohttpSession


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
                    "releaseTime": "2023-06-12T10:30:00Z"
                }
            ]
        }
        
        # Mock version specific data
        version_data = {
            "downloads": {
                "server": {
                    "url": "https://example.com/server.jar"
                }
            }
        }
        
        # Create proper mock responses
        manifest_response = MockAiohttpResponse(status=200, json_data=manifest_data)
        version_response = MockAiohttpResponse(status=200, json_data=version_data)
        
        mock_session = MockAiohttpSession({
            'https://piston-meta.mojang.com/mc/game/version_manifest.json': manifest_response,
            'https://example.com/1.20.1.json': version_response
        })
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
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
        project_data = {
            "versions": ["1.20.1", "1.19.4"]
        }
        
        # Mock builds data
        builds_data = {
            "builds": [
                {
                    "build": 196,
                    "time": "2023-06-12T10:30:00Z"
                }
            ]
        }
        
        # Create proper mock responses
        project_response = MockAiohttpResponse(status=200, json_data=project_data)
        builds_response = MockAiohttpResponse(status=200, json_data=builds_data)
        
        mock_session = MockAiohttpSession({
            'https://api.papermc.io/v2/projects/paper': project_response,
            'https://api.papermc.io/v2/projects/paper/versions/1.20.1/builds': builds_response,
            'https://api.papermc.io/v2/projects/paper/versions/1.19.4/builds': builds_response
        })
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            versions = await manager._get_paper_versions()
            
            assert len(versions) == 2
            assert all(v.server_type == ServerType.paper for v in versions)
            assert versions[0].build_number == 196

    def test_get_fallback_versions_vanilla(self):
        """Test getting fallback versions for vanilla"""
        manager = MinecraftVersionManager()
        versions = manager._get_fallback_versions(ServerType.vanilla)
        
        assert len(versions) > 0
        assert all(v.server_type == ServerType.vanilla for v in versions)
        assert all(v.version and v.download_url for v in versions)

    def test_get_fallback_versions_paper(self):
        """Test getting fallback versions for Paper"""
        manager = MinecraftVersionManager()
        versions = manager._get_fallback_versions(ServerType.paper)
        
        assert len(versions) > 0
        assert all(v.server_type == ServerType.paper for v in versions)
        assert all(v.version and v.download_url for v in versions)

    def test_get_fallback_versions_forge(self):
        """Test getting fallback versions for Forge"""
        manager = MinecraftVersionManager()
        versions = manager._get_fallback_versions(ServerType.forge)
        
        assert len(versions) > 0
        assert all(v.server_type == ServerType.forge for v in versions)
        assert all(v.version and v.download_url for v in versions)

    @pytest.mark.asyncio
    async def test_get_supported_versions_with_cache(self):
        """Test getting supported versions with cache hit"""
        manager = MinecraftVersionManager()
        
        # Populate cache
        cached_versions = [
            VersionInfo(
                version="1.20.1",
                server_type=ServerType.vanilla,
                download_url="https://example.com/server.jar"
            )
        ]
        cache_key = f"versions_{ServerType.vanilla.value}"
        manager._cache[cache_key] = cached_versions
        manager._cache_expiry[cache_key] = datetime.now() + timedelta(hours=1)
        
        result = await manager.get_supported_versions(ServerType.vanilla)
        
        assert result == cached_versions

    @pytest.mark.asyncio
    async def test_get_supported_versions_api_failure_fallback(self):
        """Test getting supported versions when API fails, using fallback"""
        manager = MinecraftVersionManager()
        
        with patch.object(manager, '_get_vanilla_versions', side_effect=Exception("API Error")):
            versions = await manager.get_supported_versions(ServerType.vanilla)
            
            # Should return fallback versions
            assert len(versions) > 0
            assert all(v.server_type == ServerType.vanilla for v in versions)

    @pytest.mark.asyncio
    async def test_get_download_url_success(self):
        """Test getting download URL successfully"""
        manager = MinecraftVersionManager()
        
        # Mock cache with versions
        versions = [
            VersionInfo(
                version="1.20.1",
                server_type=ServerType.vanilla,
                download_url="https://example.com/server.jar"
            )
        ]
        
        with patch.object(manager, 'get_supported_versions', return_value=versions):
            url = await manager.get_download_url(ServerType.vanilla, "1.20.1")
            assert url == "https://example.com/server.jar"

    @pytest.mark.asyncio
    async def test_get_download_url_not_found(self):
        """Test getting download URL for non-existent version"""
        manager = MinecraftVersionManager()
        
        # Mock empty versions list
        with patch.object(manager, 'get_supported_versions', return_value=[]):
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
            build_number=196
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
            download_url="https://example.com/server.jar"
        )
        
        assert version_info.version == "1.20.1"
        assert version_info.server_type == ServerType.vanilla
        assert version_info.download_url == "https://example.com/server.jar"
        assert version_info.release_date is None
        assert version_info.is_stable is True  # Default value
        assert version_info.build_number is None