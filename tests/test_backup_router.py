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
                "/api/v1/backups/servers/1/backups",
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
                "/api/v1/backups/servers/1/backups",
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
                "/api/v1/backups/servers/1/backups", 
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
                "/api/v1/backups/backups", 
                headers=get_auth_headers(admin_user.username)
            )
            assert response.status_code == status.HTTP_200_OK

    def test_list_all_backups_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot list all backups"""
        response = client.get(
            "/api/v1/backups/backups", 
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
                "/api/v1/backups/backups/1", 
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
                "/api/v1/backups/backups/1", 
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
                "/api/v1/backups/scheduler/status", 
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
                "/api/v1/backups/servers/1/backups",
                json={
                    "name": "Test Backup",
                    "description": "Test description",
                    "backup_type": "manual",
                },
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Failed to create backup" in response.json()["detail"]

    def test_get_server_schedule_success(self, client, test_user, db):
        """Test successful retrieval of server backup schedule"""
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

        mock_schedule = {
            "interval_hours": 24,
            "max_backups": 7,
            "enabled": True,
            "last_backup": datetime(2024, 6, 10, 14, 30, 22),
            "next_backup": datetime(2024, 6, 11, 14, 30, 22),
        }

        with patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule:
            
            mock_check_access.return_value = None
            mock_get_schedule.return_value = mock_schedule

            response = client.get(
                "/api/v1/backups/scheduler/servers/1/schedule",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["server_id"] == 1
            assert data["interval_hours"] == 24
            assert data["max_backups"] == 7
            assert data["enabled"] is True
            assert data["last_backup"] == "2024-06-10T14:30:22"
            assert data["next_backup"] == "2024-06-11T14:30:22"

    def test_get_server_schedule_no_schedule_configured(self, client, test_user, db):
        """Test getting schedule for server with no schedule configured returns 200 with null values"""
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
        ) as mock_check_access, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule:
            
            mock_check_access.return_value = None
            mock_get_schedule.return_value = None  # No schedule found

            response = client.get(
                "/api/v1/backups/scheduler/servers/1/schedule",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["server_id"] == 1
            assert data["interval_hours"] is None
            assert data["max_backups"] is None
            assert data["enabled"] is False
            assert data["last_backup"] is None
            assert data["next_backup"] is None

    def test_get_server_schedule_access_denied(self, client, test_user, db):
        """Test access denied when user doesn't have access to server"""
        # Create test server owned by different user
        other_user = User(
            username="other_user",
            email="other@example.com",
            hashed_password="hashed_password",
            role=Role.user,
            is_active=True,
            is_approved=True,
        )
        db.add(other_user)
        db.commit()

        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=other_user.id,  # Different owner
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        with patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access:
            
            # Mock access denied
            from app.core.exceptions import ServerNotFoundException
            mock_check_access.side_effect = ServerNotFoundException(
                "You don't have access to this server"
            )

            response = client.get(
                "/api/v1/backups/scheduler/servers/1/schedule",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_server_schedule_admin_access(self, client, admin_user, db):
        """Test admin can access any server schedule"""
        # Create test server owned by different user
        other_user = User(
            username="other_user",
            email="other@example.com",
            hashed_password="hashed_password",
            role=Role.user,
            is_active=True,
            is_approved=True,
        )
        db.add(other_user)
        db.commit()

        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=other_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        mock_schedule = {
            "interval_hours": 12,
            "max_backups": 5,
            "enabled": False,
            "last_backup": None,
            "next_backup": datetime(2024, 6, 11, 14, 30, 22),
        }

        with patch(
            "app.services.authorization_service.authorization_service.check_server_access"
        ) as mock_check_access, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule:
            
            mock_check_access.return_value = None  # Admin has access
            mock_get_schedule.return_value = mock_schedule

            response = client.get(
                "/api/v1/backups/scheduler/servers/1/schedule",
                headers=get_auth_headers(admin_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["server_id"] == 1
            assert data["interval_hours"] == 12
            assert data["max_backups"] == 5
            assert data["enabled"] is False
            assert data["last_backup"] is None
            assert data["next_backup"] == "2024-06-11T14:30:22"

    def test_update_server_schedule_existing_schedule(self, client, admin_user, db):
        """Test updating an existing server backup schedule"""
        # Create test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=admin_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        existing_schedule = {
            "interval_hours": 24,
            "max_backups": 7,
            "enabled": True,
            "last_backup": datetime(2024, 6, 10, 14, 30, 22),
            "next_backup": datetime(2024, 6, 11, 14, 30, 22),
        }

        updated_schedule = {
            "interval_hours": 12,
            "max_backups": 5,
            "enabled": False,
            "last_backup": datetime(2024, 6, 10, 14, 30, 22),
            "next_backup": datetime(2024, 6, 11, 2, 30, 22),
        }

        with patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.update_server_schedule"
        ) as mock_update_schedule:
            
            # First call returns existing schedule, second call returns updated schedule
            mock_get_schedule.side_effect = [existing_schedule, updated_schedule]
            mock_update_schedule.return_value = None

            response = client.put(
                "/api/v1/backups/scheduler/servers/1/schedule",
                params={
                    "interval_hours": 12,
                    "max_backups": 5,
                    "enabled": False,
                },
                headers=get_auth_headers(admin_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "Updated backup schedule for server 1" in data["message"]
            assert data["schedule"]["interval_hours"] == 12
            assert data["schedule"]["max_backups"] == 5
            assert data["schedule"]["enabled"] is False

    def test_update_server_schedule_create_new_schedule(self, client, admin_user, db):
        """Test creating a new backup schedule for server with no existing schedule"""
        # Create test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=admin_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        new_schedule = {
            "interval_hours": 48,
            "max_backups": 10,
            "enabled": True,
            "last_backup": None,
            "next_backup": datetime(2024, 6, 12, 14, 30, 22),
        }

        with patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.add_server_schedule"
        ) as mock_add_schedule:
            
            # First call returns None (no existing schedule), second call returns new schedule
            mock_get_schedule.side_effect = [None, new_schedule]
            mock_add_schedule.return_value = None

            response = client.put(
                "/api/v1/backups/scheduler/servers/1/schedule",
                params={
                    "interval_hours": 48,
                    "max_backups": 10,
                    "enabled": True,
                },
                headers=get_auth_headers(admin_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "Created new backup schedule for server 1" in data["message"]
            assert data["schedule"]["interval_hours"] == 48
            assert data["schedule"]["max_backups"] == 10
            assert data["schedule"]["enabled"] is True

    def test_update_server_schedule_create_with_defaults(self, client, admin_user, db):
        """Test creating a new backup schedule with default values when parameters not provided"""
        # Create test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=admin_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        default_schedule = {
            "interval_hours": 24,  # Default
            "max_backups": 7,     # Default
            "enabled": True,      # Default
            "last_backup": None,
            "next_backup": datetime(2024, 6, 12, 14, 30, 22),
        }

        with patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.add_server_schedule"
        ) as mock_add_schedule:
            
            mock_get_schedule.side_effect = [None, default_schedule]
            mock_add_schedule.return_value = None

            response = client.put(
                "/api/v1/backups/scheduler/servers/1/schedule",
                headers=get_auth_headers(admin_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "Created new backup schedule for server 1" in data["message"]
            assert data["schedule"]["interval_hours"] == 24
            assert data["schedule"]["max_backups"] == 7
            assert data["schedule"]["enabled"] is True

            # Verify add_server_schedule was called with defaults
            mock_add_schedule.assert_called_once_with(
                server_id=1,
                interval_hours=24,
                max_backups=7,
                enabled=True,
            )

    def test_update_server_schedule_server_not_found(self, client, admin_user, db):
        """Test updating schedule for non-existent server"""
        response = client.put(
            "/api/v1/backups/scheduler/servers/999/schedule",
            params={"interval_hours": 24},
            headers=get_auth_headers(admin_user.username),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Server not found" in response.json()["detail"]

    def test_update_server_schedule_non_admin_forbidden(self, client, test_user, db):
        """Test that non-admin users cannot update server schedules"""
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

        response = client.put(
            "/api/v1/backups/scheduler/servers/1/schedule",
            params={"interval_hours": 24},
            headers=get_auth_headers(test_user.username),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can manage backup schedules" in response.json()["detail"]

    def test_update_server_schedule_partial_update(self, client, admin_user, db):
        """Test partial update of existing schedule (only some parameters)"""
        # Create test server
        server = Server(
            id=1,
            name="Test Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=admin_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        existing_schedule = {
            "interval_hours": 24,
            "max_backups": 7,
            "enabled": True,
            "last_backup": None,
            "next_backup": datetime(2024, 6, 11, 14, 30, 22),
        }

        updated_schedule = {
            "interval_hours": 24,  # Unchanged
            "max_backups": 10,     # Updated
            "enabled": True,       # Unchanged
            "last_backup": None,
            "next_backup": datetime(2024, 6, 11, 14, 30, 22),
        }

        with patch(
            "app.services.backup_scheduler.backup_scheduler.get_server_schedule"
        ) as mock_get_schedule, \
        patch(
            "app.services.backup_scheduler.backup_scheduler.update_server_schedule"
        ) as mock_update_schedule:
            
            mock_get_schedule.side_effect = [existing_schedule, updated_schedule]
            mock_update_schedule.return_value = None

            response = client.put(
                "/api/v1/backups/scheduler/servers/1/schedule",
                params={"max_backups": 10},  # Only update max_backups
                headers=get_auth_headers(admin_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "Updated backup schedule for server 1" in data["message"]
            assert data["schedule"]["max_backups"] == 10

            # Verify update_server_schedule was called with correct parameters
            mock_update_schedule.assert_called_once_with(
                server_id=1,
                interval_hours=None,
                max_backups=10,
                enabled=None,
            )