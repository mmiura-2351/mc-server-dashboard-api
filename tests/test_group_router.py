import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.groups.models import Group, GroupType
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import Role


class TestGroupRouter:
    """Test cases for Group router endpoints"""

    def test_create_group_success(self, client, admin_user):
        """Test creating a group successfully"""
        group_data = {
            "name": "test-group",
            "group_type": "op",
            "description": "Test group description"
        }

        with patch('app.services.group_service.GroupService.create_group') as mock_create:
            mock_group = Mock()
            mock_group.id = 1
            mock_group.name = "test-group"
            mock_group.group_type = GroupType.op
            mock_group.description = "Test group description"
            mock_group.owner_id = admin_user.id
            mock_create.return_value = mock_group

            with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
                response = client.post("/api/v1/groups", json=group_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "test-group"
        assert data["group_type"] == "op"

    def test_create_group_user_forbidden(self, client, test_user):
        """Test that regular users cannot create groups"""
        group_data = {
            "name": "test-group",
            "group_type": "op"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.post("/api/v1/groups", json=group_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_create_group_invalid_data(self, client, admin_user):
        """Test creating group with invalid data"""
        invalid_data = {
            "name": "",  # Empty name
            "group_type": "invalid_type"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups", json=invalid_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_groups_success(self, client, admin_user):
        """Test listing groups"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.get_user_groups') as mock_list:
                mock_groups = [
                    Mock(id=1, name="op-group", group_type=GroupType.op),
                    Mock(id=2, name="whitelist-group", group_type=GroupType.whitelist)
                ]
                mock_list.return_value = mock_groups

                response = client.get("/api/v1/groups")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "groups" in data
        assert "total" in data
        assert data["total"] == 2

    def test_list_groups_with_filter(self, client, admin_user):
        """Test listing groups with type filter"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.get_user_groups') as mock_list:
                mock_groups = [Mock(id=1, name="op-group", group_type=GroupType.op)]
                mock_list.return_value = mock_groups

                response = client.get("/api/v1/groups?group_type=op")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1

    def test_get_group_success(self, client, admin_user):
        """Test getting group by ID"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.get_group_by_id') as mock_get:
                mock_group = Mock()
                mock_group.id = 1
                mock_group.name = "test-group"
                mock_group.group_type = GroupType.op
                mock_get.return_value = mock_group

                response = client.get("/api/v1/groups/1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "test-group"

    def test_get_group_not_found(self, client, admin_user):
        """Test getting non-existent group"""
        from fastapi import HTTPException

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.get_group_by_id') as mock_get:
                mock_get.side_effect = HTTPException(status_code=404, detail="Group not found")

                response = client.get("/api/v1/groups/999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_group_success(self, client, admin_user):
        """Test updating group"""
        update_data = {
            "name": "updated-group",
            "description": "Updated description"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.update_group') as mock_update:
                mock_group = Mock()
                mock_group.id = 1
                mock_group.name = "updated-group"
                mock_group.description = "Updated description"
                mock_update.return_value = mock_group

                response = client.put("/api/v1/groups/1", json=update_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "updated-group"

    def test_delete_group_success(self, client, admin_user):
        """Test deleting group"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.delete_group') as mock_delete:
                mock_delete.return_value = True

                response = client.delete("/api/v1/groups/1")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_group_in_use(self, client, admin_user):
        """Test deleting group that's still attached to servers"""
        from fastapi import HTTPException

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.delete_group') as mock_delete:
                mock_delete.side_effect = HTTPException(
                    status_code=409, detail="Group is attached to servers"
                )

                response = client.delete("/api/v1/groups/1")

        assert response.status_code == status.HTTP_409_CONFLICT

    @patch('app.services.group_service.GroupService.add_player_to_group')
    def test_add_player_to_group_success(self, mock_add_player, client, admin_user):
        """Test adding player to group"""
        player_data = {
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "username": "testplayer"
        }

        mock_group = Mock()
        mock_group.id = 1
        mock_add_player.return_value = mock_group

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups/1/players", json=player_data)

        assert response.status_code == status.HTTP_200_OK
        mock_add_player.assert_called_once()

    def test_add_player_invalid_uuid(self, client, admin_user):
        """Test adding player with invalid UUID"""
        player_data = {
            "uuid": "invalid-uuid",
            "username": "testplayer"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups/1/players", json=player_data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.services.group_service.GroupService.remove_player_from_group')
    def test_remove_player_from_group_success(self, mock_remove_player, client, admin_user):
        """Test removing player from group"""
        mock_group = Mock()
        mock_group.id = 1
        mock_remove_player.return_value = mock_group

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete("/api/v1/groups/1/players/123e4567-e89b-12d3-a456-426614174000")

        assert response.status_code == status.HTTP_200_OK
        mock_remove_player.assert_called_once()

    @patch('app.services.group_service.GroupService.attach_group_to_server')
    def test_attach_group_to_server_success(self, mock_attach, client, admin_user):
        """Test attaching group to server"""
        attach_data = {
            "server_id": 1,
            "priority": 10
        }

        mock_attach.return_value = True

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups/1/servers", json=attach_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data
        mock_attach.assert_called_once()

    @patch('app.services.group_service.GroupService.detach_group_from_server')
    def test_detach_group_from_server_success(self, mock_detach, client, admin_user):
        """Test detaching group from server"""
        mock_detach.return_value = True

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete("/api/v1/groups/1/servers/1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "message" in data
        mock_detach.assert_called_once()

    def test_get_group_servers_success(self, client, admin_user):
        """Test getting servers attached to group"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.get_group_servers') as mock_get:
                mock_servers = [
                    {
                        "server_id": 1,
                        "server_name": "test-server",
                        "priority": 10
                    }
                ]
                mock_get.return_value = mock_servers

                response = client.get("/api/v1/groups/1/servers")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "servers" in data
        assert data["group_id"] == 1

    def test_get_server_groups_success(self, client, admin_user):
        """Test getting groups attached to server"""
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.group_service.GroupService.get_server_groups') as mock_get:
                mock_groups = [
                    {
                        "group_id": 1,
                        "group_name": "test-group",
                        "group_type": "op",
                        "priority": 10
                    }
                ]
                mock_get.return_value = mock_groups

                response = client.get("/api/v1/groups/servers/1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "groups" in data
        assert data["server_id"] == 1

    def test_group_access_control(self, client, test_user, admin_user):
        """Test that users can only access their own groups"""
        from fastapi import HTTPException

        # Test that regular user gets access denied for admin's group
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.group_service.GroupService.get_group_by_id') as mock_get:
                mock_get.side_effect = HTTPException(status_code=403, detail="Access denied")

                response = client.get("/api/v1/groups/1")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_group_operations_require_authentication(self, client):
        """Test that group operations require authentication"""
        response = client.get("/api/v1/groups")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/groups", json={"name": "test", "group_type": "op"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_group_validation_errors(self, client, admin_user):
        """Test various validation errors"""
        # Missing required fields
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid group type
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups", json={
                "name": "test",
                "group_type": "invalid"
            })
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.services.group_service.GroupService.add_player_to_group')
    def test_async_operations_error_handling(self, mock_add_player, client, admin_user):
        """Test error handling in async operations"""
        from fastapi import HTTPException

        mock_add_player.side_effect = HTTPException(status_code=400, detail="Player already exists")

        player_data = {
            "uuid": "123e4567-e89b-12d3-a456-426614174000",
            "username": "testplayer"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups/1/players", json=player_data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_server_attachment_validation(self, client, admin_user):
        """Test server attachment validation"""
        # Missing server_id
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups/1/servers", json={})
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid priority (negative)
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/groups/1/servers", json={
                "server_id": 1,
                "priority": -1
            })
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY