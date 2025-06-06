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


class TestBackupRouter:
    """Test backup router endpoints"""

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

    def test_delete_backup(self, client, test_user, db):
        """Test deleting a backup"""
        # Update test user to operator role
        test_user.role = Role.operator
        db.commit()
        
        # Create test server and backup
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
        db.commit()

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

    def test_get_scheduler_status_admin_only(self, client, admin_user):
        """Test that only admins can get scheduler status"""
        with patch(
            "app.services.backup_scheduler.backup_scheduler.get_scheduler_status"
        ) as mock_status:
            mock_status.return_value = {
                "is_running": True,
                "scheduled_servers": 5,
                "last_run": datetime.utcnow().isoformat(),
            }

            response = client.get(
                "/api/v1/scheduler/status", 
                headers=get_auth_headers(admin_user.username)
            )
            assert response.status_code == status.HTTP_200_OK

    def test_backup_error_handling(self, client, test_user, db):
        """Test error handling for backup operations"""
        # Update test user to operator role
        test_user.role = Role.operator
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
                    "description": "Test description",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to create backup" in response.json()["detail"]