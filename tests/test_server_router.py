import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import Role


class TestServerRouter:
    """Test cases for Server router endpoints"""

    def test_list_servers_success(self, client, admin_user, db):
        """Test listing servers endpoint"""
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
            owner_id=admin_user.id,
            status=ServerStatus.running,
            directory_path="/test/server2",
        )
        db.add_all([server1, server2])
        db.commit()

        # Mock authentication
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers?page=1&size=10")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "servers" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1

    def test_list_servers_pagination(self, client, admin_user, db):
        """Test servers listing with pagination"""
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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers?page=1&size=10")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 15
        assert len(data["servers"]) == 10
        assert data["pages"] == 2

    def test_get_server_success(self, client, admin_user, db):
        """Test getting single server"""
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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get(f"/api/v1/servers/{server.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "test-server"
        assert data["id"] == server.id

    def test_get_server_not_found(self, client, admin_user):
        """Test getting non-existent server"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_server_forbidden(self, client, test_user, admin_user, db):
        """Test accessing server without permission"""
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

        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.get(f"/api/v1/servers/{server.id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_create_server_success(self, mock_manager, client, admin_user):
        """Test creating new server"""
        mock_manager.create_server.return_value = True

        server_data = {
            "name": "new-server",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla",
            "max_memory": 4096,
            "port": 25565,
            "max_players": 20
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers", json=server_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "new-server"
        assert data["minecraft_version"] == "1.20.1"

    def test_create_server_invalid_data(self, client, admin_user):
        """Test creating server with invalid data"""
        invalid_data = {
            "name": "",  # Empty name
            "minecraft_version": "1.20.1",
            "server_type": "vanilla"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/", json=invalid_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_server_duplicate_name(self, client, admin_user, db):
        """Test creating server with duplicate name"""
        # Create existing server
        existing_server = Server(
            name="existing-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/existing",
        )
        db.add(existing_server)
        db.commit()

        server_data = {
            "name": "existing-server",
            "minecraft_version": "1.20.1",
            "server_type": "vanilla"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers", json=server_data)

        assert response.status_code == status.HTTP_409_CONFLICT

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_update_server_success(self, mock_manager, client, admin_user, db):
        """Test updating server"""
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

        update_data = {
            "max_memory": 8192,
            "max_players": 30
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.put(f"/api/v1/servers/{server.id}", json=update_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["max_memory"] == 8192
        assert data["max_players"] == 30

    def test_update_server_not_found(self, client, admin_user):
        """Test updating non-existent server"""
        update_data = {"max_memory": 8192}

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.put("/api/v1/servers/999", json=update_data)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_start_server_success(self, mock_manager, client, admin_user, db):
        """Test starting server"""
        mock_manager.start_server.return_value = True
        mock_manager.get_server_status.return_value = ServerStatus.stopped

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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post(f"/api/v1/servers/{server.id}/start")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "started successfully" in data["message"]

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_start_server_invalid_status(self, mock_manager, client, admin_user, db):
        """Test starting server with invalid status"""
        mock_manager.get_server_status.return_value = ServerStatus.running

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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post(f"/api/v1/servers/{server.id}/start")

        assert response.status_code == status.HTTP_409_CONFLICT

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_stop_server_success(self, mock_manager, client, admin_user, db):
        """Test stopping server"""
        mock_manager.stop_server.return_value = True
        mock_manager.get_server_status.return_value = ServerStatus.running

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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post(f"/api/v1/servers/{server.id}/stop")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_restart_server_success(self, mock_manager, client, admin_user, db):
        """Test restarting server"""
        mock_manager.restart_server.return_value = True
        mock_manager.get_server_status.return_value = ServerStatus.running

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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post(f"/api/v1/servers/{server.id}/restart")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

    def test_delete_server_success(self, client, admin_user, db):
        """Test deleting server"""
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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete(f"/api/v1/servers/{server.id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_server_running(self, client, admin_user, db):
        """Test deleting running server"""
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

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete(f"/api/v1/servers/{server.id}")

        assert response.status_code == status.HTTP_409_CONFLICT


    def test_unauthorized_access(self, client):
        """Test accessing endpoints without authentication"""
        response = client.get("/api/v1/servers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_role_restrictions(self, client, test_user, admin_user, db):
        """Test that regular users can only see their own servers"""
        # Create servers for both users
        admin_server = Server(
            name="admin-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/admin",
        )
        user_server = Server(
            name="user-server",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=test_user.id,
            status=ServerStatus.running,
            directory_path="/test/user",
        )
        db.add_all([admin_server, user_server])
        db.commit()

        # Test regular user can only see their server
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.get("/api/v1/servers")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["servers"][0]["name"] == "user-server"

        # Test admin can see all servers
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 2

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_server_operation_permissions(self, mock_manager, client, test_user, admin_user, db):
        """Test server operation permissions"""
        # Create server owned by admin
        admin_server = Server(
            name="admin-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/admin",
        )
        db.add(admin_server)
        db.commit()

        mock_manager.get_server_status.return_value = ServerStatus.stopped

        # Test regular user cannot start admin's server
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.post(f"/api/v1/servers/{admin_server.id}/start")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.minecraft_server.minecraft_server_manager')
    def test_server_status_validation(self, mock_manager, client, admin_user, db):
        """Test server status validation for operations"""
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

        # Mock current status as running
        mock_manager.get_server_status.return_value = ServerStatus.running

        # Try to start already running server
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post(f"/api/v1/servers/{server.id}/start")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "Cannot start server in running state" in response.json()["detail"]