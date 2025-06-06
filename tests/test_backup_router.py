import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.servers.models import BackupType, Server, ServerStatus, ServerType
from app.users.models import Role


class TestBackupRouter:
    """Test cases for Backup router endpoints"""

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.backup_service.backup_service.create_backup')
    def test_create_backup_success(self, mock_create_backup, mock_check_access, client, admin_user):
        """Test creating backup successfully"""
        mock_server = Mock()
        mock_server.id = 1
        mock_check_access.return_value = mock_server

        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.name = "test-backup"
        mock_backup.backup_type = BackupType.manual
        mock_create_backup.return_value = mock_backup

        backup_data = {
            "name": "test-backup",
            "description": "Test backup",
            "backup_type": "manual"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/backups", json=backup_data)

        assert response.status_code == status.HTTP_201_CREATED
        mock_create_backup.assert_called_once()

    def test_create_backup_user_forbidden(self, client, test_user):
        """Test that regular users cannot create backups"""
        backup_data = {
            "name": "test-backup",
            "backup_type": "manual"
        }

        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                response = client.post("/api/v1/servers/1/backups", json=backup_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.backup_service.backup_service.list_backups')
    def test_list_server_backups_success(self, mock_list_backups, mock_check_access, client, admin_user):
        """Test listing server backups"""
        mock_check_access.return_value = Mock()

        mock_backups = [
            Mock(id=1, name="backup-1", backup_type=BackupType.manual),
            Mock(id=2, name="backup-2", backup_type=BackupType.scheduled)
        ]

        mock_list_backups.return_value = {
            "backups": mock_backups,
            "total": 2,
            "page": 1,
            "size": 50
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/backups")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "backups" in data
        assert data["total"] == 2

    @patch('app.services.backup_service.backup_service.list_backups')
    def test_list_all_backups_admin_only(self, mock_list_backups, client, admin_user, test_user):
        """Test that only admins can list all backups"""
        mock_list_backups.return_value = {
            "backups": [],
            "total": 0,
            "page": 1,
            "size": 50
        }

        # Test admin access
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/backups")
        assert response.status_code == status.HTTP_200_OK

        # Test regular user forbidden
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.get("/api/v1/backups")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_backup_access')
    def test_get_backup_success(self, mock_check_backup, client, admin_user):
        """Test getting backup by ID"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.name = "test-backup"
        mock_check_backup.return_value = mock_backup

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/backups/1")

        assert response.status_code == status.HTTP_200_OK

    @patch('app.services.authorization_service.authorization_service.check_backup_access')
    @patch('app.services.backup_service.backup_service.restore_backup')
    def test_restore_backup_success(self, mock_restore, mock_check_backup, client, admin_user):
        """Test restoring backup"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.server_id = 1
        mock_check_backup.return_value = mock_backup

        mock_restore.return_value = True

        restore_data = {
            "target_server_id": 1,
            "confirm": True
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                response = client.post("/api/v1/backups/1/restore", json=restore_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

    def test_restore_backup_user_forbidden(self, client, test_user):
        """Test that regular users cannot restore backups"""
        restore_data = {
            "confirm": True
        }

        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.authorization_service.authorization_service.check_backup_access'):
                response = client.post("/api/v1/backups/1/restore", json=restore_data)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_backup_access')
    @patch('app.services.backup_service.backup_service.restore_backup_and_create_template')
    def test_restore_backup_with_template_success(self, mock_restore_template, mock_check_backup, client, admin_user):
        """Test restoring backup and creating template"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.server_id = 1
        mock_check_backup.return_value = mock_backup

        mock_restore_template.return_value = {
            "backup_restored": True,
            "template_created": True,
            "template_id": 1,
            "template_name": "test-template"
        }

        restore_data = {
            "template_name": "test-template",
            "template_description": "Test template",
            "is_public": False,
            "confirm": True
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_server_access'):
                response = client.post("/api/v1/backups/1/restore-with-template", json=restore_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["backup_restored"] is True
        assert data["template_created"] is True

    @patch('app.services.authorization_service.authorization_service.check_backup_access')
    @patch('app.services.backup_service.backup_service.delete_backup')
    def test_delete_backup_success(self, mock_delete, mock_check_backup, client, admin_user):
        """Test deleting backup"""
        mock_check_backup.return_value = Mock()
        mock_delete.return_value = True

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.delete("/api/v1/backups/1")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_backup_user_forbidden(self, client, test_user):
        """Test that regular users cannot delete backups"""
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            with patch('app.services.authorization_service.authorization_service.check_backup_access'):
                response = client.delete("/api/v1/backups/1")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.authorization_service.authorization_service.check_server_access')
    @patch('app.services.backup_service.backup_service.get_backup_statistics')
    def test_get_server_backup_statistics(self, mock_get_stats, mock_check_access, client, admin_user):
        """Test getting backup statistics for server"""
        mock_check_access.return_value = Mock()
        mock_get_stats.return_value = {
            "total_backups": 5,
            "successful_backups": 4,
            "failed_backups": 1,
            "total_size_bytes": 1024000
        }

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/servers/1/backups/statistics")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_backups"] == 5

    @patch('app.services.backup_service.backup_service.get_backup_statistics')
    def test_get_global_backup_statistics_admin_only(self, mock_get_stats, client, admin_user, test_user):
        """Test global backup statistics admin only access"""
        mock_get_stats.return_value = {
            "total_backups": 10,
            "successful_backups": 8,
            "failed_backups": 2
        }

        # Test admin access
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/backups/statistics")
        assert response.status_code == status.HTTP_200_OK

        # Test regular user forbidden
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.get("/api/v1/backups/statistics")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch('app.services.backup_service.backup_service.create_scheduled_backup')
    def test_create_scheduled_backups_admin_only(self, mock_create_scheduled, client, admin_user, test_user):
        """Test creating scheduled backups admin only"""
        mock_create_scheduled.return_value = Mock(id=1)

        scheduled_data = {
            "server_ids": [1, 2, 3]
        }

        # Test admin access
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/backups/scheduled", json=scheduled_data)
        assert response.status_code == status.HTTP_200_OK

        # Test regular user forbidden
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.post("/api/v1/backups/scheduled", json=scheduled_data)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_scheduler_status_admin_only(self, client, admin_user, test_user):
        """Test getting scheduler status admin only"""
        # Test admin access
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.backup_scheduler.backup_scheduler.get_scheduler_status') as mock_status:
                mock_status.return_value = {"status": "running", "scheduled_servers": []}
                response = client.get("/api/v1/scheduler/status")
        assert response.status_code == status.HTTP_200_OK

        # Test regular user forbidden
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.get("/api/v1/scheduler/status")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_add_server_to_schedule_admin_only(self, client, admin_user, test_user, db):
        """Test adding server to backup schedule admin only"""
        # Create test server
        server = Server(
            id=1,
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
        )
        db.add(server)
        db.commit()

        # Test admin access
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.backup_scheduler.backup_scheduler.add_server_schedule') as mock_add:
                mock_add.return_value = True
                response = client.post("/api/v1/scheduler/servers/1/schedule?interval_hours=24&max_backups=7")
        assert response.status_code == status.HTTP_200_OK

        # Test regular user forbidden
        with patch('app.auth.dependencies.get_current_user', return_value=test_user):
            response = client.post("/api/v1/scheduler/servers/1/schedule")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_backup_validation_errors(self, client, admin_user):
        """Test backup creation validation errors"""
        # Missing required fields
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/backups", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid backup type
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/servers/1/backups", json={
                "name": "test",
                "backup_type": "invalid"
            })
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_backup_operations_require_authentication(self, client):
        """Test that backup operations require authentication"""
        response = client.get("/api/v1/servers/1/backups")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.post("/api/v1/servers/1/backups", json={"name": "test", "backup_type": "manual"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        response = client.get("/api/v1/backups")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('app.services.authorization_service.authorization_service.check_backup_access')
    def test_backup_error_handling(self, mock_check_backup, client, admin_user):
        """Test backup operation error handling"""
        from app.services.backup_service import BackupError
        
        # Test backup not found
        from fastapi import HTTPException
        mock_check_backup.side_effect = HTTPException(status_code=404, detail="Backup not found")

        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.get("/api/v1/backups/999")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_scheduler_validation_errors(self, client, admin_user):
        """Test scheduler endpoint validation"""
        # Invalid interval hours
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/scheduler/servers/1/schedule?interval_hours=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Invalid max backups
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            response = client.post("/api/v1/scheduler/servers/1/schedule?max_backups=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_backup_restore_validation(self, client, admin_user):
        """Test backup restore validation"""
        # Missing confirm flag
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_backup_access'):
                response = client.post("/api/v1/backups/1/restore", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Missing template name for restore with template
        with patch('app.auth.dependencies.get_current_user', return_value=admin_user):
            with patch('app.services.authorization_service.authorization_service.check_backup_access'):
                response = client.post("/api/v1/backups/1/restore-with-template", json={"confirm": True})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY