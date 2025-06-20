import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi import HTTPException

from app.services.server_service import ServerService, server_service
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import User, Role


class TestServerService:
    """Test class for ServerService"""

    @pytest.fixture
    def service(self):
        return ServerService()

    @pytest.fixture
    def mock_db_session(self):
        session = Mock()
        session.query.return_value = session
        session.filter.return_value = session
        session.offset.return_value = session
        session.limit.return_value = session
        session.all.return_value = []
        session.first.return_value = None
        session.count.return_value = 0
        session.commit.return_value = None
        return session

    @pytest.fixture
    def admin_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        return user

    @pytest.fixture
    def regular_user(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        return user

    @pytest.fixture
    def mock_server(self):
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test-server"
        server.owner_id = 2
        server.status = ServerStatus.stopped
        server.server_type = ServerType.vanilla
        server.minecraft_version = "1.19.0"
        server.is_deleted = False
        return server

    def test_service_initialization(self, service):
        """Test ServerService initialization"""
        assert isinstance(service, ServerService)

    def test_global_service_instance(self):
        """Test global server_service instance"""
        assert server_service is not None
        assert isinstance(server_service, ServerService)

    # Test list_servers_for_user
    def test_list_servers_for_user_admin_no_filters(
        self, service, admin_user, mock_db_session
    ):
        """Test listing servers for admin user without filters"""
        # Mock query result
        mock_servers = [Mock(spec=Server) for _ in range(3)]
        mock_db_session.all.return_value = mock_servers
        mock_db_session.count.return_value = 3

        result = service.list_servers_for_user(
            admin_user, page=1, size=10, db=mock_db_session
        )

        # Admin should see all servers
        mock_db_session.query.assert_called_once_with(Server)
        assert result["servers"] == mock_servers
        assert result["total"] == 3
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["pages"] == 1

    def test_list_servers_for_user_regular_user_filtered(
        self, service, regular_user, mock_db_session
    ):
        """Test listing servers for regular user with owner filtering"""
        mock_servers = [Mock(spec=Server)]
        mock_db_session.all.return_value = mock_servers
        mock_db_session.count.return_value = 1

        result = service.list_servers_for_user(
            regular_user, page=1, size=10, db=mock_db_session
        )

        # Regular user should see only their servers
        assert result["servers"] == mock_servers
        assert result["total"] == 1

    def test_list_servers_for_user_pagination(self, service, admin_user, mock_db_session):
        """Test pagination in server listing"""
        mock_db_session.all.return_value = []
        mock_db_session.count.return_value = 25

        result = service.list_servers_for_user(
            admin_user, page=2, size=10, db=mock_db_session
        )

        # Check pagination calculation
        mock_db_session.offset.assert_called_once_with(10)  # (page-1) * size
        mock_db_session.limit.assert_called_once_with(10)
        assert result["page"] == 2
        assert result["pages"] == 3  # ceil(25/10)

    def test_list_servers_for_user_database_error(
        self, service, admin_user, mock_db_session
    ):
        """Test database error handling in server listing"""
        mock_db_session.query.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            service.list_servers_for_user(admin_user, db=mock_db_session)

        assert exc_info.value.status_code == 500
        assert "Failed to list servers" in str(exc_info.value.detail)

    # Test validate_server_operation
    @patch("app.services.server_service.minecraft_server_manager")
    def test_validate_server_operation_success(
        self, mock_manager, service, mock_db_session, mock_server
    ):
        """Test successful server operation validation"""
        mock_db_session.first.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        result = service.validate_server_operation(1, "start", db=mock_db_session)

        assert result is True
        mock_manager.get_server_status.assert_called_once_with(1)

    @patch("app.services.server_service.minecraft_server_manager")
    def test_validate_server_operation_server_not_found(
        self, mock_manager, service, mock_db_session
    ):
        """Test validation when server doesn't exist"""
        mock_db_session.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.validate_server_operation(999, "start", db=mock_db_session)

        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    @patch("app.services.server_service.minecraft_server_manager")
    def test_validate_server_operation_invalid_status(
        self, mock_manager, service, mock_db_session, mock_server
    ):
        """Test validation with invalid status for operation"""
        mock_db_session.first.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running

        with pytest.raises(HTTPException) as exc_info:
            service.validate_server_operation(1, "start", db=mock_db_session)

        assert exc_info.value.status_code == 409
        assert "Cannot start server in running state" in str(exc_info.value.detail)

    @patch("app.services.server_service.minecraft_server_manager")
    def test_validate_server_operation_status_fallback(
        self, mock_manager, service, mock_db_session, mock_server
    ):
        """Test status fallback when manager returns None"""
        mock_db_session.first.return_value = mock_server
        mock_manager.get_server_status.return_value = None

        result = service.validate_server_operation(1, "start", db=mock_db_session)

        # Should fallback to stopped status and allow start
        assert result is True

    @patch("app.services.server_service.minecraft_server_manager")
    def test_validate_server_operation_all_operations(
        self, mock_manager, service, mock_db_session, mock_server
    ):
        """Test all operation types with appropriate statuses"""
        mock_db_session.first.return_value = mock_server

        # Test each operation with valid status
        operations_and_statuses = [
            ("start", ServerStatus.stopped),
            ("stop", ServerStatus.running),
            ("restart", ServerStatus.running),
            ("update", ServerStatus.stopped),
            ("delete", ServerStatus.stopped),
            ("backup", ServerStatus.running),
        ]

        for operation, status in operations_and_statuses:
            mock_manager.get_server_status.return_value = status
            result = service.validate_server_operation(1, operation, db=mock_db_session)
            assert result is True

    @patch("app.services.server_service.minecraft_server_manager")
    def test_validate_server_operation_database_error(
        self, mock_manager, service, mock_db_session
    ):
        """Test database error handling in operation validation"""
        mock_db_session.query.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            service.validate_server_operation(1, "start", db=mock_db_session)

        assert exc_info.value.status_code == 500
        assert "Failed to validate operation" in str(exc_info.value.detail)

    # Test get_server_with_access_check
    def test_get_server_with_access_check_admin(
        self, service, admin_user, mock_db_session, mock_server
    ):
        """Test server access check for admin user"""
        mock_db_session.first.return_value = mock_server

        result = service.get_server_with_access_check(1, admin_user, db=mock_db_session)

        assert result == mock_server

    def test_get_server_with_access_check_owner(
        self, service, regular_user, mock_db_session, mock_server
    ):
        """Test server access check for server owner"""
        mock_server.owner_id = regular_user.id
        mock_db_session.first.return_value = mock_server

        result = service.get_server_with_access_check(1, regular_user, db=mock_db_session)

        assert result == mock_server

    def test_get_server_with_access_check_forbidden(
        self, service, regular_user, mock_db_session, mock_server
    ):
        """Test server access check for unauthorized user"""
        mock_server.owner_id = 999  # Different owner
        mock_db_session.first.return_value = mock_server

        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(1, regular_user, db=mock_db_session)

        assert exc_info.value.status_code == 403
        assert "Not authorized" in str(exc_info.value.detail)

    def test_get_server_with_access_check_not_found(
        self, service, admin_user, mock_db_session
    ):
        """Test server access check when server doesn't exist"""
        mock_db_session.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(999, admin_user, db=mock_db_session)

        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    def test_get_server_with_access_check_database_error(
        self, service, admin_user, mock_db_session
    ):
        """Test database error handling in access check"""
        mock_db_session.query.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(1, admin_user, db=mock_db_session)

        assert exc_info.value.status_code == 500
        assert "Failed to get server" in str(exc_info.value.detail)

    # Test server_exists
    def test_server_exists_true(self, service, mock_db_session, mock_server):
        """Test server existence check returns True"""
        mock_db_session.first.return_value = mock_server

        result = service.server_exists(1, db=mock_db_session)

        assert result is True

    def test_server_exists_false(self, service, mock_db_session):
        """Test server existence check returns False"""
        mock_db_session.first.return_value = None

        result = service.server_exists(999, db=mock_db_session)

        assert result is False

    def test_server_exists_database_error(self, service, mock_db_session):
        """Test server existence check with database error"""
        mock_db_session.query.side_effect = Exception("Database error")

        result = service.server_exists(1, db=mock_db_session)

        # Should return False on error
        assert result is False

    # Test get_server_statistics
    def test_get_server_statistics_admin(self, service, admin_user, mock_db_session):
        """Test server statistics for admin user"""
        # Mock query chain
        mock_db_session.count.return_value = 5
        mock_db_session.with_entities.return_value = mock_db_session
        mock_db_session.group_by.return_value = mock_db_session
        mock_db_session.all.return_value = [("1.19.0", 3), ("1.18.0", 2)]

        result = service.get_server_statistics(admin_user, db=mock_db_session)

        assert result["total_servers"] == 5
        assert "status_distribution" in result
        assert "type_distribution" in result
        assert "version_distribution" in result
        assert result["version_distribution"]["1.19.0"] == 3
        assert "last_updated" in result

    def test_get_server_statistics_regular_user(
        self, service, regular_user, mock_db_session
    ):
        """Test server statistics for regular user with filtering"""
        mock_db_session.count.return_value = 2
        mock_db_session.with_entities.return_value = mock_db_session
        mock_db_session.group_by.return_value = mock_db_session
        mock_db_session.all.return_value = [("1.19.0", 2)]

        result = service.get_server_statistics(regular_user, db=mock_db_session)

        assert result["total_servers"] == 2
        # Should have filtered by owner_id

    def test_get_server_statistics_database_error(
        self, service, admin_user, mock_db_session
    ):
        """Test database error handling in statistics"""
        mock_db_session.query.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            service.get_server_statistics(admin_user, db=mock_db_session)

        assert exc_info.value.status_code == 500
        assert "Failed to get statistics" in str(exc_info.value.detail)

    # Test wait_for_server_status
    @pytest.mark.asyncio
    @patch("app.services.server_service.minecraft_server_manager")
    async def test_wait_for_server_status_success(self, mock_manager, service):
        """Test successful wait for server status"""
        mock_manager.get_server_status.return_value = ServerStatus.running

        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=5)

        assert result is True
        mock_manager.get_server_status.assert_called_with(1)

    @pytest.mark.asyncio
    @patch("app.services.server_service.minecraft_server_manager")
    async def test_wait_for_server_status_timeout(self, mock_manager, service):
        """Test timeout in wait for server status"""
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=1)

        assert result is False

    @pytest.mark.asyncio
    @patch("app.services.server_service.minecraft_server_manager")
    async def test_wait_for_server_status_eventual_success(self, mock_manager, service):
        """Test eventual success in wait for server status"""
        # First call returns wrong status, second call returns correct status
        mock_manager.get_server_status.side_effect = [
            ServerStatus.starting,
            ServerStatus.running,
        ]

        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=5)

        assert result is True
        assert mock_manager.get_server_status.call_count == 2

    @pytest.mark.asyncio
    @patch("app.services.server_service.minecraft_server_manager")
    async def test_wait_for_server_status_error(self, mock_manager, service):
        """Test error handling in wait for server status"""
        mock_manager.get_server_status.side_effect = Exception("Server manager error")

        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=1)

        assert result is False

    # Test update_server_status
    def test_update_server_status_success(self, service, mock_db_session, mock_server):
        """Test successful server status update"""
        mock_db_session.first.return_value = mock_server

        result = service.update_server_status(1, ServerStatus.running, db=mock_db_session)

        assert result is True
        assert mock_server.status == ServerStatus.running
        mock_db_session.commit.assert_called_once()

    def test_update_server_status_server_not_found(self, service, mock_db_session):
        """Test server status update when server doesn't exist"""
        mock_db_session.first.return_value = None

        result = service.update_server_status(
            999, ServerStatus.running, db=mock_db_session
        )

        assert result is False

    def test_update_server_status_database_error(
        self, service, mock_db_session, mock_server
    ):
        """Test database error handling in status update"""
        mock_db_session.first.return_value = mock_server
        mock_db_session.commit.side_effect = Exception("Database error")

        result = service.update_server_status(1, ServerStatus.running, db=mock_db_session)

        assert result is False
