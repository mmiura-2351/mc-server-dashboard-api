import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException
from datetime import datetime

from app.services.server_service import ServerService, server_service
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import Role, User


class TestServerService:
    """Test cases for app.services.server_service.ServerService"""

    def test_init(self):
        """Test ServerService initialization"""
        service = ServerService()
        assert service is not None

    def test_list_servers_for_user_admin(self, db, admin_user):
        """Test listing servers for admin user"""
        # Create test servers
        server1 = Server(
            name="admin-server-1",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server1",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        server2 = Server(
            name="other-server",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=999,  # Different owner
            status=ServerStatus.running,
            directory_path="/test/server2",
            port=25566,
            max_memory=2048,
            max_players=30,
        )
        db.add_all([server1, server2])
        db.commit()

        service = ServerService()
        result = service.list_servers_for_user(admin_user, page=1, size=10, db=db)

        # Admin should see all servers
        assert result["total"] == 2
        assert len(result["servers"]) == 2
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["pages"] == 1

    def test_list_servers_for_user_regular(self, db, test_user, admin_user):
        """Test listing servers for regular user"""
        # Create test servers
        server1 = Server(
            name="user-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/user-server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        server2 = Server(
            name="admin-server",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=admin_user.id,
            status=ServerStatus.running,
            directory_path="/test/admin-server",
            port=25566,
            max_memory=2048,
            max_players=30,
        )
        db.add_all([server1, server2])
        db.commit()

        service = ServerService()
        result = service.list_servers_for_user(test_user, page=1, size=10, db=db)

        # Regular user should only see their own servers
        assert result["total"] == 1
        assert len(result["servers"]) == 1
        assert result["servers"][0].name == "user-server"
        assert result["servers"][0].owner_id == test_user.id

    def test_list_servers_for_user_pagination(self, db, admin_user):
        """Test server listing pagination"""
        # Create multiple servers
        servers = []
        for i in range(15):
            server = Server(
                name=f"server-{i}",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=admin_user.id,
                status=ServerStatus.stopped,
                directory_path=f"/test/server{i}",
                port=25565 + i,
                max_memory=1024,
                max_players=20,
            )
            servers.append(server)
        db.add_all(servers)
        db.commit()

        service = ServerService()
        
        # Test first page
        result = service.list_servers_for_user(admin_user, page=1, size=10, db=db)
        assert result["total"] == 15
        assert len(result["servers"]) == 10
        assert result["page"] == 1
        assert result["pages"] == 2

        # Test second page
        result = service.list_servers_for_user(admin_user, page=2, size=10, db=db)
        assert result["total"] == 15
        assert len(result["servers"]) == 5
        assert result["page"] == 2

    def test_list_servers_for_user_exclude_deleted(self, db, admin_user):
        """Test that deleted servers are excluded from listing"""
        # Create servers including deleted one
        server1 = Server(
            name="active-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/active",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        server2 = Server(
            name="deleted-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/deleted",
            port=25566,
            max_memory=1024,
            max_players=20,
            is_deleted=True,
        )
        db.add_all([server1, server2])
        db.commit()

        service = ServerService()
        result = service.list_servers_for_user(admin_user, page=1, size=10, db=db)

        # Should only see active server
        assert result["total"] == 1
        assert len(result["servers"]) == 1
        assert result["servers"][0].name == "active-server"

    def test_list_servers_for_user_database_error(self, admin_user):
        """Test list servers handles database errors"""
        service = ServerService()
        
        # Mock database session that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")
        
        with pytest.raises(HTTPException) as exc_info:
            service.list_servers_for_user(admin_user, db=mock_db)
        
        assert exc_info.value.status_code == 500
        assert "Failed to list servers" in str(exc_info.value.detail)

    @patch('app.services.server_service.minecraft_server_manager')
    def test_validate_server_operation_success(self, mock_manager, db, admin_user):
        """Test successful server operation validation"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        # Mock server status
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        service = ServerService()
        result = service.validate_server_operation(server.id, "start", db=db)
        
        assert result is True

    @patch('app.services.server_service.minecraft_server_manager')
    def test_validate_server_operation_invalid_state(self, mock_manager, db, admin_user):
        """Test server operation validation with invalid state"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.running,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        # Mock server status as running (can't start when already running)
        mock_manager.get_server_status.return_value = ServerStatus.running

        service = ServerService()
        
        with pytest.raises(HTTPException) as exc_info:
            service.validate_server_operation(server.id, "start", db=db)
        
        assert exc_info.value.status_code == 409
        assert "Cannot start server in running state" in str(exc_info.value.detail)

    def test_validate_server_operation_server_not_found(self, db):
        """Test server operation validation with nonexistent server"""
        service = ServerService()
        
        with pytest.raises(HTTPException) as exc_info:
            service.validate_server_operation(999, "start", db=db)
        
        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    @patch('app.services.server_service.minecraft_server_manager')
    def test_validate_server_operation_no_status(self, mock_manager, db, admin_user):
        """Test server operation validation when status is None"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        # Mock server status as None (defaults to stopped)
        mock_manager.get_server_status.return_value = None

        service = ServerService()
        result = service.validate_server_operation(server.id, "start", db=db)
        
        assert result is True

    def test_validate_server_operation_database_error(self):
        """Test validate server operation handles database errors"""
        service = ServerService()
        
        # Mock database session that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")
        
        with pytest.raises(HTTPException) as exc_info:
            service.validate_server_operation(1, "start", db=mock_db)
        
        assert exc_info.value.status_code == 500
        assert "Failed to validate operation" in str(exc_info.value.detail)

    def test_get_server_with_access_check_success(self, db, admin_user):
        """Test successful server retrieval with access check"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        result = service.get_server_with_access_check(server.id, admin_user, db=db)
        
        assert result.id == server.id
        assert result.name == "test-server"

    def test_get_server_with_access_check_not_found(self, db, admin_user):
        """Test server retrieval with nonexistent server"""
        service = ServerService()
        
        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(999, admin_user, db=db)
        
        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    def test_get_server_with_access_check_deleted_server(self, db, admin_user):
        """Test server retrieval with deleted server"""
        # Create deleted server
        server = Server(
            name="deleted-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
            is_deleted=True,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        
        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(server.id, admin_user, db=db)
        
        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    def test_get_server_with_access_check_forbidden(self, db, test_user, admin_user):
        """Test server retrieval with insufficient permissions"""
        # Create server owned by admin
        server = Server(
            name="admin-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        
        # Regular user trying to access admin's server
        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(server.id, test_user, db=db)
        
        assert exc_info.value.status_code == 403
        assert "Not authorized to access this server" in str(exc_info.value.detail)

    def test_get_server_with_access_check_admin_access(self, db, test_user, admin_user):
        """Test admin can access any server"""
        # Create server owned by regular user
        server = Server(
            name="user-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        result = service.get_server_with_access_check(server.id, admin_user, db=db)
        
        # Admin should be able to access user's server
        assert result.id == server.id
        assert result.owner_id == test_user.id

    def test_get_server_with_access_check_database_error(self, admin_user):
        """Test get server with access check handles database errors"""
        service = ServerService()
        
        # Mock database session that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")
        
        with pytest.raises(HTTPException) as exc_info:
            service.get_server_with_access_check(1, admin_user, db=mock_db)
        
        assert exc_info.value.status_code == 500
        assert "Failed to get server" in str(exc_info.value.detail)

    def test_server_exists_true(self, db, admin_user):
        """Test server_exists returns True for existing server"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        result = service.server_exists(server.id, db=db)
        
        assert result is True

    def test_server_exists_false(self, db):
        """Test server_exists returns False for nonexistent server"""
        service = ServerService()
        result = service.server_exists(999, db=db)
        
        assert result is False

    def test_server_exists_deleted_server(self, db, admin_user):
        """Test server_exists returns False for deleted server"""
        # Create deleted server
        server = Server(
            name="deleted-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
            is_deleted=True,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        result = service.server_exists(server.id, db=db)
        
        assert result is False

    def test_server_exists_database_error(self):
        """Test server_exists handles database errors gracefully"""
        service = ServerService()
        
        # Mock database session that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")
        
        result = service.server_exists(1, db=mock_db)
        
        # Should return False on error, not raise exception
        assert result is False

    def test_get_server_statistics_admin(self, db, admin_user, test_user):
        """Test get server statistics for admin user"""
        # Create servers of different types and statuses
        servers = [
            Server(
                name="vanilla-server",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=admin_user.id,
                status=ServerStatus.running,
                directory_path="/test/vanilla",
                port=25565,
                max_memory=1024,
                max_players=20,
            ),
            Server(
                name="paper-server",
                minecraft_version="1.19.4",
                server_type=ServerType.paper,
                owner_id=test_user.id,
                status=ServerStatus.stopped,
                directory_path="/test/paper",
                port=25566,
                max_memory=2048,
                max_players=30,
            ),
            Server(
                name="forge-server",
                minecraft_version="1.18.2",
                server_type=ServerType.forge,
                owner_id=admin_user.id,
                status=ServerStatus.error,
                directory_path="/test/forge",
                port=25567,
                max_memory=4096,
                max_players=50,
            ),
        ]
        db.add_all(servers)
        db.commit()

        service = ServerService()
        result = service.get_server_statistics(admin_user, db=db)

        # Admin should see all servers
        assert result["total_servers"] == 3
        assert result["status_distribution"]["running"] == 1
        assert result["status_distribution"]["stopped"] == 1
        assert result["status_distribution"]["error"] == 1
        assert result["type_distribution"]["vanilla"] == 1
        assert result["type_distribution"]["paper"] == 1
        assert result["type_distribution"]["forge"] == 1
        assert result["version_distribution"]["1.20.1"] == 1
        assert result["version_distribution"]["1.19.4"] == 1
        assert result["version_distribution"]["1.18.2"] == 1
        assert "last_updated" in result

    def test_get_server_statistics_regular_user(self, db, admin_user, test_user):
        """Test get server statistics for regular user"""
        # Create servers owned by different users
        servers = [
            Server(
                name="user-server-1",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=test_user.id,
                status=ServerStatus.running,
                directory_path="/test/user1",
                port=25565,
                max_memory=1024,
                max_players=20,
            ),
            Server(
                name="user-server-2",
                minecraft_version="1.20.1",
                server_type=ServerType.paper,
                owner_id=test_user.id,
                status=ServerStatus.stopped,
                directory_path="/test/user2",
                port=25566,
                max_memory=2048,
                max_players=30,
            ),
            Server(
                name="admin-server",
                minecraft_version="1.19.4",
                server_type=ServerType.forge,
                owner_id=admin_user.id,
                status=ServerStatus.error,
                directory_path="/test/admin",
                port=25567,
                max_memory=4096,
                max_players=50,
            ),
        ]
        db.add_all(servers)
        db.commit()

        service = ServerService()
        result = service.get_server_statistics(test_user, db=db)

        # Regular user should only see their own servers
        assert result["total_servers"] == 2
        assert result["status_distribution"]["running"] == 1
        assert result["status_distribution"]["stopped"] == 1
        assert result["status_distribution"]["error"] == 0
        assert result["type_distribution"]["vanilla"] == 1
        assert result["type_distribution"]["paper"] == 1
        assert result["type_distribution"]["forge"] == 0
        assert result["version_distribution"]["1.20.1"] == 2
        assert "1.19.4" not in result["version_distribution"]

    def test_get_server_statistics_exclude_deleted(self, db, admin_user):
        """Test get server statistics excludes deleted servers"""
        # Create servers including deleted one
        servers = [
            Server(
                name="active-server",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=admin_user.id,
                status=ServerStatus.running,
                directory_path="/test/active",
                port=25565,
                max_memory=1024,
                max_players=20,
            ),
            Server(
                name="deleted-server",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=admin_user.id,
                status=ServerStatus.stopped,
                directory_path="/test/deleted",
                port=25566,
                max_memory=1024,
                max_players=20,
                is_deleted=True,
            ),
        ]
        db.add_all(servers)
        db.commit()

        service = ServerService()
        result = service.get_server_statistics(admin_user, db=db)

        # Should only count active server
        assert result["total_servers"] == 1
        assert result["status_distribution"]["running"] == 1
        assert result["status_distribution"]["stopped"] == 0

    def test_get_server_statistics_database_error(self, admin_user):
        """Test get server statistics handles database errors"""
        service = ServerService()
        
        # Mock database session that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")
        
        with pytest.raises(HTTPException) as exc_info:
            service.get_server_statistics(admin_user, db=mock_db)
        
        assert exc_info.value.status_code == 500
        assert "Failed to get statistics" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch('app.services.server_service.minecraft_server_manager')
    async def test_wait_for_server_status_success(self, mock_manager):
        """Test successful wait for server status"""
        # Mock server status to return target status immediately
        mock_manager.get_server_status.return_value = ServerStatus.running

        service = ServerService()
        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=5)
        
        assert result is True

    @pytest.mark.asyncio
    @patch('app.services.server_service.minecraft_server_manager')
    async def test_wait_for_server_status_timeout(self, mock_manager):
        """Test wait for server status timeout"""
        # Mock server status to never reach target status
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        service = ServerService()
        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=2)
        
        assert result is False

    @pytest.mark.asyncio
    @patch('app.services.server_service.minecraft_server_manager')
    async def test_wait_for_server_status_eventually_reaches_target(self, mock_manager):
        """Test wait for server status that eventually reaches target"""
        # Mock server status to change after a few calls
        call_count = 0
        def mock_status_side_effect(server_id):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return ServerStatus.running
            return ServerStatus.starting
        
        mock_manager.get_server_status.side_effect = mock_status_side_effect

        service = ServerService()
        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=10)
        
        assert result is True
        assert call_count >= 3

    @pytest.mark.asyncio
    @patch('app.services.server_service.minecraft_server_manager')
    async def test_wait_for_server_status_exception(self, mock_manager):
        """Test wait for server status handles exceptions"""
        # Mock server status to raise exception
        mock_manager.get_server_status.side_effect = Exception("Manager error")

        service = ServerService()
        result = await service.wait_for_server_status(1, ServerStatus.running, timeout=2)
        
        # Should return False on exception, not raise
        assert result is False

    def test_update_server_status_success(self, db, admin_user):
        """Test successful server status update"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        service = ServerService()
        result = service.update_server_status(server.id, ServerStatus.running, db=db)
        
        assert result is True
        
        # Verify status was updated
        db.refresh(server)
        assert server.status == ServerStatus.running

    def test_update_server_status_server_not_found(self, db):
        """Test update server status with nonexistent server"""
        service = ServerService()
        result = service.update_server_status(999, ServerStatus.running, db=db)
        
        assert result is False

    def test_update_server_status_database_error(self, admin_user):
        """Test update server status handles database errors"""
        service = ServerService()
        
        # Mock database session that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")
        
        result = service.update_server_status(1, ServerStatus.running, db=mock_db)
        
        # Should return False on error, not raise exception
        assert result is False

    def test_global_server_service_instance(self):
        """Test global server_service instance exists"""
        from app.services.server_service import server_service
        assert server_service is not None
        assert isinstance(server_service, ServerService)