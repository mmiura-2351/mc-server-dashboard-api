"""
Essential test coverage for import_export router
Focus on critical edge cases for improved coverage
"""

import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException, UploadFile

from app.users.models import Role, User


class TestImportExportRouter:
    """Essential test cases for import/export router edge cases"""

    @pytest.mark.asyncio
    @patch("app.servers.routers.import_export.server_service")
    async def test_export_server_general_exception(self, mock_server_service, admin_user):
        """Test export server with general exception (140-142 lines)"""
        from app.servers.routers.import_export import export_server

        # Mock server service to raise general exception
        mock_server_service.get_server_by_id.side_effect = Exception(
            "Database connection error"
        )

        with pytest.raises(HTTPException) as exc_info:
            await export_server(server_id=1, current_user=admin_user, db=Mock())

        assert exc_info.value.status_code == 500
        assert "Failed to export server" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_import_server_file_too_large(self, admin_user):
        """Test import server with file size exceeding limit (176 line)"""
        from app.servers.routers.import_export import import_server

        # Create mock file that's too large (over 500MB)
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "large_server.zip"
        mock_file.size = 600 * 1024 * 1024  # 600MB

        with pytest.raises(HTTPException) as exc_info:
            await import_server(
                name="large-server",
                description="Large server test",
                file=mock_file,
                current_user=admin_user,
                db=Mock(),
            )

        assert exc_info.value.status_code == 413
        assert "File too large" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_import_server_invalid_file_extension(self, admin_user):
        """Test import server with invalid file extension"""
        from app.servers.routers.import_export import import_server

        # Create mock file with invalid extension
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "invalid_server.txt"
        mock_file.size = 1000

        with pytest.raises(HTTPException) as exc_info:
            await import_server(
                name="test-server",
                description="Test server",
                file=mock_file,
                current_user=admin_user,
                db=Mock(),
            )

        assert exc_info.value.status_code == 400
        assert "Only ZIP files are supported" in str(exc_info.value.detail)

    def test_import_server_regular_user_authorization_check(self, test_user):
        """Test that regular users pass authorization check for server import (Phase 1: shared resource model)"""
        from app.services.authorization_service import AuthorizationService

        # Phase 1: Regular users should be able to create (import) servers
        assert AuthorizationService.can_create_server(test_user) is True, (
            "Regular users should be authorized to create/import servers in Phase 1"
        )

    def test_router_configuration(self):
        """Test that router is properly configured"""
        from app.servers.routers.import_export import router

        assert router.tags == ["servers"]
        assert len(router.routes) > 0
