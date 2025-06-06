import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException

from app.services.server_service import ServerService, server_service
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import Role


class TestServerService:
    """Test cases for ServerService"""

    def test_list_servers_for_user_admin(self, db, admin_user):
        """Test listing servers for admin user"""
        # Create test servers
        server1 = Server(
            name="test-server-1",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server1",
        )
        server2 = Server(
            name="test-server-2",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=999,  # Different owner
            status=ServerStatus.running,
            directory_path="/test/server2",
        )
        db.add_all([server1, server2])
        db.commit()

        # Test admin can see all servers
        result = server_service.list_servers_for_user(admin_user, page=1, size=10, db=db)

        assert result["total"] == 2
        assert len(result["servers"]) == 2
        assert result["page"] == 1
        assert result["size"] == 10
        assert result["pages"] == 1

    def test_list_servers_for_user_regular_user(self, db, test_user, admin_user):
        """Test listing servers for regular user"""
        # Create test servers
        server1 = Server(
            name="user-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/user-server",
        )
        server2 = Server(
            name="admin-server",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=admin_user.id,
            status=ServerStatus.running,
            directory_path="/test/admin-server",
        )
        db.add_all([server1, server2])
        db.commit()

        # Test regular user can only see their own servers
        result = server_service.list_servers_for_user(test_user, page=1, size=10, db=db)

        assert result["total"] == 1
        assert len(result["servers"]) == 1
        assert result["servers"][0].name == "user-server"
        assert result["servers"][0].owner_id == test_user.id

    def test_list_servers_pagination(self, db, admin_user):
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
            )
            servers.append(server)
        db.add_all(servers)
        db.commit()

        # Test first page
        result = server_service.list_servers_for_user(admin_user, page=1, size=10, db=db)
        assert result["total"] == 15
        assert len(result["servers"]) == 10
        assert result["page"] == 1
        assert result["pages"] == 2

        # Test second page
        result = server_service.list_servers_for_user(admin_user, page=2, size=10, db=db)
        assert result["total"] == 15
        assert len(result["servers"]) == 5
        assert result["page"] == 2

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
        )
        db.add(server)
        db.commit()

        # Mock server status
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        # Test valid operation
        result = server_service.validate_server_operation(server.id, "start", db=db)
        assert result is True

    @patch('app.services.server_service.minecraft_server_manager')
    def test_validate_server_operation_invalid_status(self, mock_manager, db, admin_user):
        """Test server operation validation with invalid status"""
        # Create test server
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.running,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        # Mock server status
        mock_manager.get_server_status.return_value = ServerStatus.running

        # Test invalid operation (trying to start running server)
        with pytest.raises(HTTPException) as exc_info:
            server_service.validate_server_operation(server.id, "start", db=db)
        
        assert exc_info.value.status_code == 409
        assert "Cannot start server in running state" in str(exc_info.value.detail)

    def test_validate_server_operation_nonexistent_server(self, db):
        """Test server operation validation with nonexistent server"""
        with pytest.raises(HTTPException) as exc_info:
            server_service.validate_server_operation(999, "start", db=db)
        
        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    def test_get_server_with_access_check_admin(self, db, admin_user, test_user):
        """Test getting server with admin access"""
        # Create server owned by test_user
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        # Admin should be able to access any server
        result = server_service.get_server_with_access_check(server.id, admin_user, db=db)
        assert result.id == server.id
        assert result.name == "test-server"

    def test_get_server_with_access_check_owner(self, db, test_user):
        """Test getting server as owner"""
        # Create server owned by test_user
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        # Owner should be able to access their server
        result = server_service.get_server_with_access_check(server.id, test_user, db=db)
        assert result.id == server.id
        assert result.name == "test-server"

    def test_get_server_with_access_check_forbidden(self, db, test_user, admin_user):
        """Test getting server with forbidden access"""
        # Create server owned by admin
        server = Server(
            name="admin-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        # Regular user should not be able to access admin's server
        with pytest.raises(HTTPException) as exc_info:
            server_service.get_server_with_access_check(server.id, test_user, db=db)
        
        assert exc_info.value.status_code == 403
        assert "Not authorized to access this server" in str(exc_info.value.detail)

    def test_get_server_with_access_check_not_found(self, db, test_user):
        """Test getting nonexistent server"""
        with pytest.raises(HTTPException) as exc_info:
            server_service.get_server_with_access_check(999, test_user, db=db)
        
        assert exc_info.value.status_code == 404
        assert "Server not found" in str(exc_info.value.detail)

    def test_server_exists_true(self, db, admin_user):
        """Test server existence check when server exists"""
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        result = server_service.server_exists(server.id, db=db)
        assert result is True

    def test_server_exists_false(self, db):
        """Test server existence check when server doesn't exist"""
        result = server_service.server_exists(999, db=db)
        assert result is False

    def test_server_exists_deleted_server(self, db, admin_user):
        """Test server existence check for deleted server"""
        server = Server(
            name="deleted-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            is_deleted=True,
        )
        db.add(server)
        db.commit()

        result = server_service.server_exists(server.id, db=db)
        assert result is False

    def test_get_server_statistics_admin(self, db, admin_user, test_user):
        """Test getting server statistics for admin"""
        # Create test servers with different types and statuses
        servers = [
            Server(
                name="vanilla-stopped",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=admin_user.id,
                status=ServerStatus.stopped,
                directory_path="/test/vanilla1",
            ),
            Server(
                name="paper-running",
                minecraft_version="1.19.4",
                server_type=ServerType.paper,
                owner_id=test_user.id,
                status=ServerStatus.running,
                directory_path="/test/paper1",
            ),
            Server(
                name="forge-error",
                minecraft_version="1.18.2",
                server_type=ServerType.forge,
                owner_id=admin_user.id,
                status=ServerStatus.error,
                directory_path="/test/forge1",
            ),
        ]
        db.add_all(servers)
        db.commit()

        result = server_service.get_server_statistics(admin_user, db=db)

        assert result["total_servers"] == 3
        assert result["status_distribution"]["stopped"] == 1
        assert result["status_distribution"]["running"] == 1
        assert result["status_distribution"]["error"] == 1
        assert result["type_distribution"]["vanilla"] == 1
        assert result["type_distribution"]["paper"] == 1
        assert result["type_distribution"]["forge"] == 1
        assert result["version_distribution"]["1.20.1"] == 1
        assert result["version_distribution"]["1.19.4"] == 1
        assert result["version_distribution"]["1.18.2"] == 1

    def test_get_server_statistics_regular_user(self, db, admin_user, test_user):
        """Test getting server statistics for regular user"""
        # Create servers for both users
        servers = [
            Server(
                name="user-server",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=test_user.id,
                status=ServerStatus.stopped,
                directory_path="/test/user-server",
            ),
            Server(
                name="admin-server",
                minecraft_version="1.19.4",
                server_type=ServerType.paper,
                owner_id=admin_user.id,
                status=ServerStatus.running,
                directory_path="/test/admin-server",
            ),
        ]
        db.add_all(servers)
        db.commit()

        result = server_service.get_server_statistics(test_user, db=db)

        # Regular user should only see their own server's statistics
        assert result["total_servers"] == 1
        assert result["status_distribution"]["stopped"] == 1
        assert result["status_distribution"]["running"] == 0
        assert result["type_distribution"]["vanilla"] == 1
        assert result["type_distribution"]["paper"] == 0

    @patch('app.services.server_service.minecraft_server_manager')
    @pytest.mark.asyncio
    async def test_wait_for_server_status_success(self, mock_manager):
        """Test waiting for server status successfully"""
        # Mock status changing from starting to running
        mock_manager.get_server_status.side_effect = [
            ServerStatus.starting,
            ServerStatus.starting,
            ServerStatus.running
        ]

        result = await server_service.wait_for_server_status(1, ServerStatus.running, timeout=5)
        assert result is True

    @patch('app.services.server_service.minecraft_server_manager')
    @pytest.mark.asyncio
    async def test_wait_for_server_status_timeout(self, mock_manager):
        """Test waiting for server status with timeout"""
        # Mock status never changing
        mock_manager.get_server_status.return_value = ServerStatus.starting

        result = await server_service.wait_for_server_status(1, ServerStatus.running, timeout=2)
        assert result is False

    def test_update_server_status_success(self, db, admin_user):
        """Test updating server status successfully"""
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        result = server_service.update_server_status(server.id, ServerStatus.running, db=db)
        assert result is True

        # Verify status was updated
        db.refresh(server)
        assert server.status == ServerStatus.running

    def test_update_server_status_nonexistent(self, db):
        """Test updating status for nonexistent server"""
        result = server_service.update_server_status(999, ServerStatus.running, db=db)
        assert result is False