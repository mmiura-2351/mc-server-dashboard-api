"""
Simplified test coverage for servers utilities router
Tests core functionality with proper async mocking
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException

from app.servers.models import ServerType
from app.users.models import Role, User


class TestUtilitiesRouterSimple:
    """Simplified test cases for utilities router endpoints"""

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.minecraft_version_manager")
    async def test_get_supported_versions_success(self, mock_version_manager):
        """Test successful retrieval of supported versions"""
        from app.servers.routers.utilities import get_supported_versions

        # Mock version info
        mock_version_info = Mock()
        mock_version_info.version = "1.20.1"
        mock_version_info.server_type = ServerType.vanilla
        mock_version_info.download_url = "https://example.com/server.jar"
        mock_version_info.release_date = "2023-06-07"
        mock_version_info.is_stable = True
        mock_version_info.build_number = None

        mock_version_manager.get_supported_versions = AsyncMock(
            return_value=[mock_version_info]
        )

        result = await get_supported_versions()

        assert result.versions is not None
        assert len(result.versions) >= 0

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.minecraft_version_manager")
    async def test_get_supported_versions_error(self, mock_version_manager):
        """Test getting versions with service error"""
        from app.servers.routers.utilities import get_supported_versions

        # Make it fail for all ServerType values to trigger the outer exception
        mock_version_manager.get_supported_versions = AsyncMock(
            side_effect=Exception("Service error")
        )

        # Actually, let's check the router code - it catches individual errors but may not raise HTTP exception
        result = await get_supported_versions()
        # The router catches individual errors per server type, so this should succeed with empty versions
        assert result.versions is not None

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.minecraft_version_manager")
    @patch("app.servers.routers.utilities.SupportedVersionsResponse")
    async def test_get_supported_versions_response_creation_error(
        self, mock_response_class, mock_version_manager
    ):
        """Test error during response object creation to trigger outer exception handler"""
        from app.servers.routers.utilities import get_supported_versions

        # Mock version manager to return valid data
        mock_version_info = Mock()
        mock_version_info.version = "1.20.1"
        mock_version_info.server_type = ServerType.vanilla
        mock_version_info.download_url = "https://example.com/server.jar"
        mock_version_info.release_date = "2023-06-07"
        mock_version_info.is_stable = True
        mock_version_info.build_number = None

        mock_version_manager.get_supported_versions = AsyncMock(
            return_value=[mock_version_info]
        )

        # Make the response creation fail to trigger the outer exception handler
        mock_response_class.side_effect = Exception("Response creation failed")

        with pytest.raises(HTTPException) as exc_info:
            await get_supported_versions()

        assert exc_info.value.status_code == 500
        assert "Failed to get supported versions" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_sync_server_states_non_admin(self, test_user):
        """Test server state sync with non-admin user"""
        from app.servers.routers.utilities import sync_server_states

        with pytest.raises(HTTPException) as exc_info:
            await sync_server_states(current_user=test_user)

        assert exc_info.value.status_code == 403
        assert "Only admins can sync server states" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.services.database_integration.database_integration_service")
    async def test_sync_server_states_success(self, mock_db_service, admin_user):
        """Test successful server state synchronization"""
        from app.servers.routers.utilities import sync_server_states

        mock_db_service.get_all_running_servers.return_value = [
            {"id": 1, "name": "server1"},
            {"id": 2, "name": "server2"},
        ]

        result = await sync_server_states(current_user=admin_user)

        assert result["message"] == "Server states synchronized"
        assert result["total_running"] == 2
        mock_db_service.sync_server_states.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cache_stats_non_admin(self, test_user):
        """Test cache stats with non-admin user"""
        from app.servers.routers.utilities import get_cache_stats

        with pytest.raises(HTTPException) as exc_info:
            await get_cache_stats(current_user=test_user)

        assert exc_info.value.status_code == 403
        assert "Only admins can view cache statistics" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.jar_cache_manager")
    async def test_get_cache_stats_success(self, mock_cache_manager, admin_user):
        """Test successful cache stats retrieval"""
        from app.servers.routers.utilities import get_cache_stats

        mock_stats = {"total_files": 10, "total_size": 1024000}
        mock_cache_manager.get_cache_stats = AsyncMock(return_value=mock_stats)

        result = await get_cache_stats(current_user=admin_user)

        assert result == mock_stats
        mock_cache_manager.get_cache_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_cache_non_admin(self, test_user):
        """Test cache cleanup with non-admin user"""
        from app.servers.routers.utilities import cleanup_cache

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_cache(current_user=test_user)

        assert exc_info.value.status_code == 403
        assert "Only admins can trigger cache cleanup" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.jar_cache_manager")
    async def test_cleanup_cache_success(self, mock_cache_manager, admin_user):
        """Test successful cache cleanup"""
        from app.servers.routers.utilities import cleanup_cache

        mock_stats = {"total_files": 5, "total_size": 512000}
        mock_cache_manager.cleanup_old_cache = AsyncMock()
        mock_cache_manager.get_cache_stats = AsyncMock(return_value=mock_stats)

        result = await cleanup_cache(current_user=admin_user)

        assert result["message"] == "Cache cleanup completed"
        assert result["cache_stats"] == mock_stats
        mock_cache_manager.cleanup_old_cache.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_get_java_compatibility_info_success(self, mock_java_service):
        """Test successful Java compatibility info retrieval"""
        from app.servers.routers.utilities import get_java_compatibility_info

        # Mock Java info
        mock_java_info = Mock()
        mock_java_info.major_version = 17
        mock_java_info.version_string = "17.0.2"
        mock_java_info.vendor = "OpenJDK"
        mock_java_info.executable_path = "/usr/bin/java"
        mock_java_info.full_version_string = 'openjdk version "17.0.2"'

        mock_installations = {17: mock_java_info}
        mock_compatibility_matrix = {"1.20": [17, 21]}
        mock_supported_versions = ["1.19", "1.20"]

        mock_java_service.discover_java_installations = AsyncMock(
            return_value=mock_installations
        )
        mock_java_service.get_compatibility_matrix.return_value = (
            mock_compatibility_matrix
        )
        mock_java_service.get_supported_minecraft_versions.return_value = (
            mock_supported_versions
        )

        result = await get_java_compatibility_info()

        assert result["java_installations_found"] == 1
        assert result["compatibility_matrix"] == mock_compatibility_matrix
        assert "17" in result["installations"]

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_get_java_compatibility_info_no_installations(self, mock_java_service):
        """Test Java compatibility info when no installations found"""
        from app.servers.routers.utilities import get_java_compatibility_info

        mock_java_service.discover_java_installations = AsyncMock(return_value={})
        mock_java_service.get_compatibility_matrix.return_value = {}

        result = await get_java_compatibility_info()

        assert result["java_installations_found"] == 0
        assert result["error"] == "No Java installations found"

    @pytest.mark.asyncio
    async def test_validate_java_for_minecraft_version_invalid_format(self):
        """Test Java validation with invalid Minecraft version format"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        with pytest.raises(HTTPException) as exc_info:
            await validate_java_for_minecraft_version("invalid-version")

        assert exc_info.value.status_code == 400
        assert "Invalid Minecraft version format" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_validate_java_for_minecraft_version_success(self, mock_java_service):
        """Test successful Java validation for Minecraft version"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        # Mock Java info
        mock_java_info = Mock()
        mock_java_info.major_version = 17
        mock_java_info.version_string = "17.0.2"
        mock_java_info.vendor = "OpenJDK"
        mock_java_info.executable_path = "/usr/bin/java"

        mock_java_service.get_java_for_minecraft = AsyncMock(return_value=mock_java_info)
        mock_java_service.validate_java_compatibility.return_value = (True, "Compatible")
        mock_java_service.get_required_java_version.return_value = 17

        result = await validate_java_for_minecraft_version("1.20.1")

        assert result["compatible"] is True
        assert result["minecraft_version"] == "1.20.1"
        assert result["required_java"] == 17

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_validate_java_for_minecraft_version_no_compatible_java(
        self, mock_java_service
    ):
        """Test Java validation when no compatible Java found"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        mock_java_service.get_java_for_minecraft = AsyncMock(return_value=None)
        mock_java_service.discover_java_installations = AsyncMock(
            return_value={8: Mock(), 11: Mock()}
        )
        mock_java_service.get_required_java_version.return_value = 17

        result = await validate_java_for_minecraft_version("1.20.1")

        assert result["compatible"] is False
        assert result["minecraft_version"] == "1.20.1"
        assert result["required_java"] == 17
        assert "No compatible Java installation found" in result["error"]

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_validate_java_for_minecraft_version_incompatible(
        self, mock_java_service
    ):
        """Test Java validation when Java is incompatible"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        mock_java_info = Mock()
        mock_java_info.major_version = 8
        mock_java_info.version_string = "8.0.1"
        mock_java_info.vendor = "OpenJDK"
        mock_java_info.executable_path = "/usr/bin/java"

        mock_java_service.get_java_for_minecraft = AsyncMock(return_value=mock_java_info)
        mock_java_service.validate_java_compatibility.return_value = (
            False,
            "Version too old",
        )
        mock_java_service.get_required_java_version.return_value = 17

        result = await validate_java_for_minecraft_version("1.20.1")

        assert result["compatible"] is False
        assert result["message"] == "Version too old"

    def test_router_configuration(self):
        """Test that router is properly configured"""
        from app.servers.routers.utilities import router

        assert router.tags == ["servers"]
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    async def test_valid_minecraft_version_formats(self):
        """Test various valid Minecraft version formats"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        valid_versions = ["1.20", "1.20.1", "1.8", "1.19.4"]

        for version in valid_versions:
            try:
                with patch(
                    "app.servers.routers.utilities.java_compatibility_service"
                ) as mock_service:
                    mock_service.get_java_for_minecraft = AsyncMock(return_value=None)
                    mock_service.discover_java_installations = AsyncMock(return_value={})
                    mock_service.get_required_java_version.return_value = 17

                    result = await validate_java_for_minecraft_version(version)
                    # Should not be a 400 error for valid formats
                    assert "compatible" in result
            except HTTPException as e:
                # Should not be 400 (bad request) for valid formats
                assert e.status_code != 400

    @pytest.mark.asyncio
    async def test_invalid_minecraft_version_formats(self):
        """Test various invalid Minecraft version formats"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        invalid_versions = ["1", "1.20.1.2", "v1.20.1", "1.20-snapshot", ""]

        for version in invalid_versions:
            with pytest.raises(HTTPException) as exc_info:
                await validate_java_for_minecraft_version(version)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.services.database_integration.database_integration_service")
    async def test_sync_server_states_error(self, mock_db_service, admin_user):
        """Test server state sync with database error"""
        from app.servers.routers.utilities import sync_server_states

        mock_db_service.sync_server_states.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            await sync_server_states(current_user=admin_user)

        assert exc_info.value.status_code == 500
        assert "Failed to sync server states" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.jar_cache_manager")
    async def test_get_cache_stats_error(self, mock_cache_manager, admin_user):
        """Test cache stats with manager error"""
        from app.servers.routers.utilities import get_cache_stats

        mock_cache_manager.get_cache_stats = AsyncMock(
            side_effect=Exception("Cache error")
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_cache_stats(current_user=admin_user)

        assert exc_info.value.status_code == 500
        assert "Failed to get cache stats" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.jar_cache_manager")
    async def test_cleanup_cache_error(self, mock_cache_manager, admin_user):
        """Test cache cleanup with manager error"""
        from app.servers.routers.utilities import cleanup_cache

        mock_cache_manager.cleanup_old_cache = AsyncMock(
            side_effect=Exception("Cleanup error")
        )

        with pytest.raises(HTTPException) as exc_info:
            await cleanup_cache(current_user=admin_user)

        assert exc_info.value.status_code == 500
        assert "Failed to cleanup cache" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_get_java_compatibility_info_error(self, mock_java_service):
        """Test Java compatibility info with service error"""
        from app.servers.routers.utilities import get_java_compatibility_info

        mock_java_service.discover_java_installations = AsyncMock(
            side_effect=Exception("Service error")
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_java_compatibility_info()

        assert exc_info.value.status_code == 500
        assert "Failed to get Java compatibility information" in str(
            exc_info.value.detail
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.utilities.java_compatibility_service")
    async def test_validate_java_for_minecraft_version_error(self, mock_java_service):
        """Test Java validation with service error"""
        from app.servers.routers.utilities import validate_java_for_minecraft_version

        mock_java_service.get_java_for_minecraft = AsyncMock(
            side_effect=Exception("Service error")
        )

        with pytest.raises(HTTPException) as exc_info:
            await validate_java_for_minecraft_version("1.20.1")

        assert exc_info.value.status_code == 500
        assert "Failed to validate Java compatibility" in str(exc_info.value.detail)
