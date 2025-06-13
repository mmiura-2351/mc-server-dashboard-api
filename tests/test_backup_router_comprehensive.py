"""Comprehensive tests for backup router endpoints"""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from fastapi import status

from app.auth.auth import create_access_token
from app.servers.models import Backup, BackupType, BackupStatus, Server, ServerType
from app.users.models import Role, User
from app.core.exceptions import (
    BackupNotFoundException,
    ServerNotFoundException,
    FileOperationException,
    DatabaseOperationException
)


def get_auth_headers(username: str):
    """Generate authentication headers"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestBackupRouterComprehensive:
    """Comprehensive test backup router endpoints with full functionality"""

    def test_create_backup_success(self, client, test_user, db):
        """Test successful backup creation"""
        # Update test user to operator role
        test_user.role = Role.operator
        db.commit()
        
        # Create a test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.backup_service.backup_service.create_backup"
        ) as mock_create, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_backup = Backup(
                id=1,
                server_id=1,
                name="Test Backup",
                description="Test description",
                backup_type=BackupType.manual,
                status=BackupStatus.completed,
                file_path="/backups/test.tar.gz",
                file_size=1024,
                created_at=datetime.utcnow(),
            )
            mock_create.return_value = mock_backup
            mock_check_access.return_value = None  # No exception means access granted

            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "Test Backup",
                    "description": "Test description",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_201_CREATED
            data = response.json()
            assert data["name"] == "Test Backup"
            assert data["backup_type"] == "manual"
            
            # Verify service calls
            mock_check_access.assert_called_once_with(1, test_user, db)
            mock_create.assert_called_once()

    def test_create_backup_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users cannot create backups"""
        # Ensure user has regular role
        test_user.role = Role.user
        db.commit()
        
        # Create test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            mock_check_access.return_value = None

            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "Test Backup",
                    "description": "Test description",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert "Only operators and admins can create backups" in response.json()["detail"]
            
            # Authorization check should still be called
            mock_check_access.assert_called_once()

    def test_create_backup_server_not_found(self, client, test_user):
        """Test backup creation when server doesn't exist"""
        test_user.role = Role.operator
        
        with patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            mock_check_access.side_effect = ServerNotFoundException("Server not found")

            response = client.post(
                "/api/v1/servers/999/backups",
                json={
                    "name": "Test Backup",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_backup_file_operation_error(self, client, test_user, db):
        """Test backup creation with file operation error"""
        test_user.role = Role.operator
        db.commit()
        
        server = Server(
            id=1,
            name="Test Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.backup_service.backup_service.create_backup"
        ) as mock_create, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = None
            mock_create.side_effect = FileOperationException("create", "backup", "Failed to create backup")

            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "Test Backup",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to create backup" in response.json()["detail"]

    def test_list_server_backups(self, client, test_user, db):
        """Test listing backups for a specific server"""
        # Create test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch("app.services.backup_service.backup_service.list_backups") as mock_list, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = None
            mock_list.return_value = {
                "backups": [
                    Backup(
                        id=1,
                        server_id=1,
                        name="Backup 1",
                        backup_type=BackupType.manual,
                        status=BackupStatus.completed,
                        file_path="/backups/backup1.tar.gz",
                        file_size=1024,
                        created_at=datetime.utcnow(),
                    ),
                    Backup(
                        id=2,
                        server_id=1,
                        name="Backup 2",
                        backup_type=BackupType.scheduled,
                        status=BackupStatus.completed,
                        file_path="/backups/backup2.tar.gz",
                        file_size=2048,
                        created_at=datetime.utcnow(),
                    ),
                ],
                "total": 2,
                "page": 1,
                "size": 50,
            }

            response = client.get(
                "/api/v1/servers/1/backups", 
                headers=get_auth_headers(test_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total"] == 2
            assert len(data["backups"]) == 2
            assert data["backups"][0]["name"] == "Backup 1"
            
            # Verify service calls
            mock_check_access.assert_called_once_with(1, test_user, db)
            mock_list.assert_called_once()

    def test_list_server_backups_with_pagination(self, client, test_user, db):
        """Test listing backups with pagination parameters"""
        server = Server(
            id=1,
            name="Test Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch("app.services.backup_service.backup_service.list_backups") as mock_list, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = None
            mock_list.return_value = {
                "backups": [],
                "total": 0,
                "page": 2,
                "size": 10,
            }

            response = client.get(
                "/api/v1/servers/1/backups?page=2&size=10&backup_type=manual", 
                headers=get_auth_headers(test_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["page"] == 2
            assert data["size"] == 10
            
            # Verify service was called with correct parameters
            mock_list.assert_called_once_with(
                server_id=1,
                backup_type=BackupType.manual,
                page=2,
                size=10,
                db=db
            )

    def test_list_all_backups_admin_only(self, client, admin_user):
        """Test that only admins can list all backups"""
        with patch("app.services.backup_service.backup_service.list_backups") as mock_list:
            mock_list.return_value = {
                "backups": [],
                "total": 0,
                "page": 1,
                "size": 50,
            }

            response = client.get(
                "/api/v1/backups", 
                headers=get_auth_headers(admin_user.username)
            )
            assert response.status_code == status.HTTP_200_OK
            
            # Verify service was called without server_id (for all backups)
            mock_list.assert_called_once()
            call_args = mock_list.call_args
            assert "server_id" not in call_args.kwargs or call_args.kwargs["server_id"] is None

    def test_list_all_backups_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot list all backups"""
        response = client.get(
            "/api/v1/backups", 
            headers=get_auth_headers(test_user.username)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can view all backups" in response.json()["detail"]

    def test_get_backup_by_id(self, client, test_user, db):
        """Test getting backup details by ID"""
        # Create test backup
        backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.utcnow(),
        )
        db.add(backup)
        
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.authorization_service.authorization_service.check_backup_access"
        ) as mock_check_access:
            mock_check_access.return_value = backup

            response = client.get(
                "/api/v1/backups/1", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["id"] == 1
            assert data["name"] == "Test Backup"
            
            # Verify authorization check
            mock_check_access.assert_called_once_with(1, test_user, db)

    def test_get_backup_not_found(self, client, test_user):
        """Test getting backup that doesn't exist"""
        with patch(
            "app.services.authorization_service.authorization_service.check_backup_access"
        ) as mock_check_access:
            mock_check_access.side_effect = BackupNotFoundException("Backup not found")

            response = client.get(
                "/api/v1/backups/999", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_restore_backup_success(self, client, test_user, db):
        """Test successful backup restoration"""
        test_user.role = Role.operator
        db.commit()
        
        backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.utcnow(),
        )
        
        with patch(
            "app.services.backup_service.backup_service.restore_backup"
        ) as mock_restore, \
        patch(
            "app.services.authorization_service.authorization_service.check_backup_access"
        ) as mock_check_backup, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_server:
            
            mock_check_backup.return_value = backup
            mock_check_server.return_value = None
            mock_restore.return_value = True

            response = client.post(
                "/api/v1/backups/1/restore",
                json={"confirm": True},
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert "restored successfully" in data["message"]
            
            # Verify service calls
            mock_check_backup.assert_called_once()
            mock_restore.assert_called_once()

    def test_restore_backup_with_target_server(self, client, test_user, db):
        """Test backup restoration to different target server"""
        test_user.role = Role.operator
        db.commit()
        
        backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.utcnow(),
        )
        
        with patch(
            "app.services.backup_service.backup_service.restore_backup"
        ) as mock_restore, \
        patch(
            "app.services.authorization_service.authorization_service.check_backup_access"
        ) as mock_check_backup, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_server:
            
            mock_check_backup.return_value = backup
            mock_check_server.return_value = None
            mock_restore.return_value = True

            response = client.post(
                "/api/v1/backups/1/restore",
                json={"target_server_id": 2, "confirm": True},
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["details"]["target_server_id"] == 2
            
            # Should check access to target server
            mock_check_server.assert_called_with(2, test_user, db)

    def test_delete_backup(self, client, test_user, db):
        """Test deleting a backup"""
        # Update test user to operator role
        test_user.role = Role.operator
        db.commit()
        
        backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.utcnow(),
        )

        with patch(
            "app.services.backup_service.backup_service.delete_backup"
        ) as mock_delete, \
        patch(
            "app.services.authorization_service.authorization_service.check_backup_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = backup
            mock_delete.return_value = True

            response = client.delete(
                "/api/v1/backups/1", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT
            
            # Verify service calls
            mock_check_access.assert_called_once_with(1, test_user, db)
            mock_delete.assert_called_once_with(1, db)

    def test_delete_backup_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users cannot delete backups"""
        test_user.role = Role.user
        db.commit()
        
        backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.utcnow(),
        )

        with patch(
            "app.services.authorization_service.authorization_service.check_backup_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = backup

            response = client.delete(
                "/api/v1/backups/1", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert "Only operators and admins can delete backups" in response.json()["detail"]

    def test_backup_statistics_server_specific(self, client, test_user, db):
        """Test getting backup statistics for specific server"""
        server = Server(
            id=1,
            name="Test Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch("app.services.backup_service.backup_service.get_backup_statistics") as mock_stats, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = None
            mock_stats.return_value = {
                "total_backups": 5,
                "successful_backups": 4,
                "failed_backups": 1,
                "total_size": 1024000
            }

            response = client.get(
                "/api/v1/servers/1/backups/statistics", 
                headers=get_auth_headers(test_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total_backups"] == 5
            assert data["successful_backups"] == 4
            
            # Verify service calls
            mock_check_access.assert_called_once_with(1, test_user, db)
            mock_stats.assert_called_once_with(server_id=1, db=db)

    def test_global_backup_statistics_admin_only(self, client, admin_user):
        """Test getting global backup statistics (admin only)"""
        with patch("app.services.backup_service.backup_service.get_backup_statistics") as mock_stats:
            mock_stats.return_value = {
                "total_backups": 50,
                "successful_backups": 45,
                "failed_backups": 5,
                "total_size": 10240000
            }

            response = client.get(
                "/api/v1/backups/statistics", 
                headers=get_auth_headers(admin_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total_backups"] == 50
            
            # Should be called without server_id for global stats
            mock_stats.assert_called_once_with(db=pytest.anySQL)

    def test_global_backup_statistics_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot access global backup statistics"""
        response = client.get(
            "/api/v1/backups/statistics", 
            headers=get_auth_headers(test_user.username)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can view global backup statistics" in response.json()["detail"]

    def test_create_scheduled_backups_admin_only(self, client, admin_user):
        """Test creating scheduled backups (admin only)"""
        with patch("app.services.backup_service.backup_service.create_scheduled_backup") as mock_create:
            mock_backup1 = Mock()
            mock_backup1.id = 1
            mock_backup2 = Mock()
            mock_backup2.id = 2
            
            mock_create.side_effect = [mock_backup1, mock_backup2]

            response = client.post(
                "/api/v1/backups/scheduled",
                json={"server_ids": [1, 2]},
                headers=get_auth_headers(admin_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["success"] is True
            assert data["details"]["total_created"] == 2
            assert data["details"]["created_backups"] == [1, 2]

    def test_create_scheduled_backups_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot create scheduled backups"""
        response = client.post(
            "/api/v1/backups/scheduled",
            json={"server_ids": [1, 2]},
            headers=get_auth_headers(test_user.username),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can create scheduled backups" in response.json()["detail"]


class TestBackupRouterErrorHandling:
    """Test error handling scenarios for backup router"""

    def test_database_operation_exception(self, client, test_user, db):
        """Test database operation exception handling"""
        test_user.role = Role.operator
        db.commit()
        
        server = Server(
            id=1,
            name="Test Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.backup_service.backup_service.create_backup"
        ) as mock_create, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = None
            mock_create.side_effect = DatabaseOperationException("Database error")

            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "Test Backup",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Database error" in response.json()["detail"]

    def test_general_exception_handling(self, client, test_user, db):
        """Test general exception handling"""
        test_user.role = Role.operator
        db.commit()
        
        server = Server(
            id=1,
            name="Test Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.backup_service.backup_service.create_backup"
        ) as mock_create, \
        patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            mock_check_access.return_value = None
            mock_create.side_effect = ValueError("Unexpected error")

            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "Test Backup",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to create backup" in response.json()["detail"]

    def test_unauthorized_access(self, client):
        """Test unauthorized access to backup endpoints"""
        # No authentication headers
        response = client.post(
            "/api/v1/servers/1/backups",
            json={
                "name": "Test Backup",
                "backup_type": "manual",
            }
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invalid_backup_type(self, client, test_user):
        """Test creation with invalid backup type"""
        test_user.role = Role.operator
        
        response = client.post(
            "/api/v1/servers/1/backups",
            json={
                "name": "Test Backup",
                "backup_type": "invalid_type",
            },
            headers=get_auth_headers(test_user.username),
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_missing_required_fields(self, client, test_user):
        """Test creation with missing required fields"""
        test_user.role = Role.operator
        
        response = client.post(
            "/api/v1/servers/1/backups",
            json={
                "description": "Missing name and backup_type",
            },
            headers=get_auth_headers(test_user.username),
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY