"""Test coverage for servers management router.

Updated under #228 (PR 2b/?): the `authorization_service` module-level
singleton was removed and replaced with FastAPI DI of an
`AuthorizationService` instance. These tests now construct an
`AsyncMock(spec=AuthorizationService)` and pass it through the
`auth=` kwarg to the router handlers. Boolean helpers
(`can_create_server`, `can_delete_server`) are static, so they are
patched on the class rather than on a mock instance.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.servers.application.authorization import AuthorizationService
from app.servers.models import ServerType


def _make_auth_mock() -> AsyncMock:
    """Build an AsyncMock that satisfies the AuthorizationService interface.

    `spec=AuthorizationService` ensures async methods become AsyncMocks
    automatically and `check_server_access` returns awaitables.
    """
    return AsyncMock(spec=AuthorizationService)


class TestServerManagementRouter:
    """Test cases for server management router endpoints"""

    def test_create_server_authorization_check(self, test_user):
        """Test that regular users pass authorization check for server creation (Phase 1: shared resource model)"""
        from app.services.authorization_service import AuthorizationService

        # Phase 1: Regular users should be able to create servers
        assert AuthorizationService.can_create_server(test_user) is True, (
            "Regular users should be authorized to create servers in Phase 1"
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch(
        "app.servers.application.authorization.AuthorizationService.can_create_server",
        return_value=True,
    )
    async def test_create_server_general_exception(
        self, mock_can_create, mock_server_service, admin_user
    ):
        """Test create server with general exception (lines 69-72)"""
        from app.servers.routers.management import create_server
        from app.servers.schemas import ServerCreateRequest

        mock_server_service.create_server = AsyncMock(
            side_effect=Exception("Database error")
        )

        request = ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20,
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_server(
                request=request,
                background_tasks=BackgroundTasks(),
                current_user=admin_user,
                db=Mock(),
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to create server" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_list_servers_exception(self, mock_server_service, admin_user):
        """Test list servers with exception (lines 99-102)"""
        from app.servers.routers.management import list_servers

        # Mock server service to raise exception
        mock_server_service.list_servers_async = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        with pytest.raises(HTTPException) as exc_info:
            await list_servers(
                page=1,
                size=10,
                current_user=admin_user,
                db=Mock(),
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to list servers" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_get_server_not_found(self, mock_server_service, admin_user):
        """Test get server not found (lines 123-126)"""
        from app.servers.routers.management import get_server

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        # Mock server service to return None (not found)
        mock_server_service.get_server = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_server(
                server_id=999,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_get_server_general_exception(self, mock_server_service, admin_user):
        """Test get server with general exception (lines 132-135)"""
        from app.servers.routers.management import get_server

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        mock_server_service.get_server = AsyncMock(side_effect=Exception("Service error"))

        with pytest.raises(HTTPException) as exc_info:
            await get_server(
                server_id=1,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to get server" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_list_servers_all_users_see_all(
        self, mock_server_service, admin_user, test_user
    ):
        """Test list servers access control - all users see all servers (lines 89-90)"""
        from app.servers.routers.management import list_servers

        mock_result = {"servers": [], "total": 0, "page": 1, "size": 10}
        # `list_servers` endpoint now calls `list_servers_async` (async) via DI.
        mock_server_service.list_servers_async = AsyncMock(return_value=mock_result)

        # Create consistent db mock for both calls
        db_mock = Mock()

        # Test admin access (should see all servers - owner_id=None)
        await list_servers(
            page=1,
            size=10,
            current_user=admin_user,
            db=db_mock,
            server_service=mock_server_service,
        )

        # Verify admin call had owner_id=None
        assert mock_server_service.list_servers_async.call_args[1]["owner_id"] is None
        assert mock_server_service.list_servers_async.call_args[1]["page"] == 1
        assert mock_server_service.list_servers_async.call_args[1]["size"] == 10

        # Reset mock
        mock_server_service.list_servers_async.reset_mock()

        # Test regular user access (should also see all servers - owner_id=None)
        await list_servers(
            page=1,
            size=10,
            current_user=test_user,
            db=db_mock,
            server_service=mock_server_service,
        )

        # Verify user call also had owner_id=None (all users see all servers)
        assert mock_server_service.list_servers_async.call_args[1]["owner_id"] is None
        assert mock_server_service.list_servers_async.call_args[1]["page"] == 1
        assert mock_server_service.list_servers_async.call_args[1]["size"] == 10

    def test_router_configuration(self):
        """Test that router is properly configured"""
        from app.servers.routers.management import router

        assert router.tags == ["servers"]
        assert len(router.routes) > 0

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch(
        "app.servers.application.authorization.AuthorizationService.can_create_server",
        return_value=True,
    )
    async def test_create_server_conflict_exception_passthrough(
        self, mock_can_create, mock_server_service, admin_user
    ):
        """Test create server with ConflictException passthrough (lines 67-68)"""
        from app.core.exceptions import ConflictException
        from app.servers.routers.management import create_server
        from app.servers.schemas import ServerCreateRequest

        # Mock server service to raise ConflictException
        conflict_exception = ConflictException("Port already in use")
        mock_server_service.create_server = AsyncMock(side_effect=conflict_exception)

        request = ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20,
        )

        # ConflictException should be re-raised as-is
        with pytest.raises(ConflictException):
            await create_server(
                request=request,
                background_tasks=BackgroundTasks(),
                current_user=admin_user,
                db=Mock(),
                server_service=mock_server_service,
            )

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_get_server_http_exception_passthrough(
        self, mock_server_service, admin_user
    ):
        """Test get server with HTTPException passthrough (lines 130-131)"""
        from app.servers.routers.management import get_server

        auth = _make_auth_mock()
        # Mock authorization to raise HTTPException
        auth_exception = HTTPException(status_code=403, detail="Access denied")
        auth.check_server_access.side_effect = auth_exception

        # HTTPException should be re-raised as-is
        with pytest.raises(HTTPException) as exc_info:
            await get_server(
                server_id=1,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 403
        assert "Access denied" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_get_server_success(self, mock_server_service, admin_user):
        """Test get server success path (line 128)"""
        from app.servers.routers.management import get_server

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        # Mock server service to return server
        mock_server = {"id": 1, "name": "test-server"}
        mock_server_service.get_server = AsyncMock(return_value=mock_server)

        result = await get_server(
            server_id=1,
            current_user=admin_user,
            db=Mock(),
            auth=auth,
            server_service=mock_server_service,
        )

        assert result == mock_server

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch("app.servers.routers.management.minecraft_server_manager")
    async def test_update_server_success(
        self, mock_minecraft_manager, mock_server_service, admin_user
    ):
        """Test update server success path (lines 152-176)"""
        from app.servers.models import ServerStatus
        from app.servers.routers.management import update_server
        from app.servers.schemas import ServerUpdateRequest

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        mock_minecraft_manager.get_server_status.return_value = ServerStatus.stopped
        mock_server = {"id": 1, "name": "updated-server"}
        mock_server_service.update_server = AsyncMock(return_value=mock_server)

        request = ServerUpdateRequest(name="updated-server", description="Updated")
        result = await update_server(
            server_id=1,
            request=request,
            current_user=admin_user,
            db=Mock(),
            auth=auth,
            server_service=mock_server_service,
        )

        assert result == mock_server

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch("app.servers.routers.management.minecraft_server_manager")
    async def test_update_server_running_memory_change(
        self, mock_minecraft_manager, mock_server_service, admin_user
    ):
        """Test update server with memory change while running (lines 157-163)"""
        from app.servers.models import ServerStatus
        from app.servers.routers.management import update_server
        from app.servers.schemas import ServerUpdateRequest

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        mock_minecraft_manager.get_server_status.return_value = ServerStatus.running

        request = ServerUpdateRequest(max_memory=2048)  # Trying to change memory

        with pytest.raises(HTTPException) as exc_info:
            await update_server(
                server_id=1,
                request=request,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 409
        assert "Server must be stopped" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch("app.servers.routers.management.minecraft_server_manager")
    async def test_update_server_running_non_restricted_change(
        self, mock_minecraft_manager, mock_server_service, admin_user
    ):
        """Test update server while running with non-restricted changes (lines 158-165)"""
        from app.servers.models import ServerStatus
        from app.servers.routers.management import update_server
        from app.servers.schemas import ServerUpdateRequest

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        mock_minecraft_manager.get_server_status.return_value = ServerStatus.running
        mock_server = {"id": 1, "name": "updated-server"}
        mock_server_service.update_server = AsyncMock(return_value=mock_server)

        request = ServerUpdateRequest(
            name="updated-server", description="Updated description"
        )

        result = await update_server(
            server_id=1,
            request=request,
            current_user=admin_user,
            db=Mock(),
            auth=auth,
            server_service=mock_server_service,
        )

        assert result == mock_server
        mock_server_service.update_server.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_update_server_not_found(self, mock_server_service, admin_user):
        """Test update server not found (lines 166-169)"""
        from app.servers.routers.management import update_server
        from app.servers.schemas import ServerUpdateRequest

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        mock_server_service.update_server = AsyncMock(return_value=None)

        request = ServerUpdateRequest(name="updated-server")

        with pytest.raises(HTTPException) as exc_info:
            await update_server(
                server_id=999,
                request=request,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    async def test_update_server_general_exception(self, mock_server_service, admin_user):
        """Test update server with general exception (lines 175-179)"""
        from app.servers.routers.management import update_server
        from app.servers.schemas import ServerUpdateRequest

        auth = _make_auth_mock()
        auth.check_server_access.return_value = None
        mock_server_service.update_server = AsyncMock(
            side_effect=Exception("Update failed")
        )

        request = ServerUpdateRequest(name="updated-server")

        with pytest.raises(HTTPException) as exc_info:
            await update_server(
                server_id=1,
                request=request,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to update server" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch(
        "app.servers.application.authorization.AuthorizationService.can_delete_server",
        return_value=True,
    )
    async def test_delete_server_success(
        self, mock_can_delete, mock_server_service, admin_user
    ):
        """Test delete server success path for admin"""
        from app.servers.routers.management import delete_server

        # Mock server object
        mock_server = Mock()
        mock_server.owner_id = 999  # Different from admin_user.id

        auth = _make_auth_mock()
        auth.check_server_access.return_value = mock_server
        mock_server_service.delete_server = AsyncMock(return_value=True)

        # Should not raise any exception
        await delete_server(
            server_id=1,
            current_user=admin_user,
            db=Mock(),
            auth=auth,
            server_service=mock_server_service,
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch(
        "app.servers.application.authorization.AuthorizationService.can_delete_server",
        return_value=False,
    )
    async def test_delete_server_permission_denied(
        self, mock_can_delete, mock_server_service, test_user
    ):
        """Test delete server permission denied for non-owner regular user"""
        from app.servers.routers.management import delete_server

        # Mock server object owned by different user
        mock_server = Mock()
        mock_server.owner_id = 999  # Different from test_user.id

        auth = _make_auth_mock()
        auth.check_server_access.return_value = mock_server

        with pytest.raises(HTTPException) as exc_info:
            await delete_server(
                server_id=1,
                current_user=test_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 403
        assert "Only admins and server owners can delete servers" in str(
            exc_info.value.detail
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch(
        "app.servers.application.authorization.AuthorizationService.can_delete_server",
        return_value=True,
    )
    async def test_delete_server_not_found(
        self, mock_can_delete, mock_server_service, admin_user
    ):
        """Test delete server not found"""
        from app.servers.routers.management import delete_server

        # Mock server object
        mock_server = Mock()
        mock_server.owner_id = 999

        auth = _make_auth_mock()
        auth.check_server_access.return_value = mock_server
        mock_server_service.delete_server = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await delete_server(
                server_id=999,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("app.servers.routers.management.server_service")
    @patch(
        "app.servers.application.authorization.AuthorizationService.can_delete_server",
        return_value=True,
    )
    async def test_delete_server_general_exception(
        self, mock_can_delete, mock_server_service, admin_user
    ):
        """Test delete server with general exception"""
        from app.servers.routers.management import delete_server

        # Mock server object
        mock_server = Mock()
        mock_server.owner_id = 999

        auth = _make_auth_mock()
        auth.check_server_access.return_value = mock_server
        mock_server_service.delete_server = AsyncMock(
            side_effect=Exception("Delete failed")
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_server(
                server_id=1,
                current_user=admin_user,
                db=Mock(),
                auth=auth,
                server_service=mock_server_service,
            )

        assert exc_info.value.status_code == 500
        assert "Failed to delete server" in str(exc_info.value.detail)
