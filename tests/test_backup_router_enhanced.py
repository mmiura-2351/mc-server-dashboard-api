"""Enhanced tests for backup router endpoints covering missing paths"""
from unittest.mock import Mock, patch, AsyncMock

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.backups.router import router
from app.backups.schemas import (
    BackupCreateRequest,
    BackupRestoreRequest,
    BackupRestoreWithTemplateRequest,
    ScheduledBackupRequest
)
from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
)
from app.main import app
from app.servers.models import BackupType
from app.users.models import Role, User


# Add the router to the app for testing
app.include_router(router, prefix="/api/v1")


class TestCreateBackup:
    """Test backup creation endpoint"""
    
    @pytest.fixture
    def mock_user_admin(self):
        """Create mock admin user"""
        user = Mock(spec=User)
        user.id = 1
        user.username = "admin"
        user.role = Role.admin
        return user
    
    @pytest.fixture
    def mock_user_operator(self):
        """Create mock operator user"""
        user = Mock(spec=User)
        user.id = 2
        user.username = "operator"
        user.role = Role.operator
        return user
    
    @pytest.fixture
    def mock_user_regular(self):
        """Create mock regular user"""
        user = Mock(spec=User)
        user.id = 3
        user.username = "user"
        user.role = Role.user
        return user
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    def test_create_backup_success_admin(self, client, mock_user_admin):
        """Test successful backup creation by admin"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.name = "test-backup"
        mock_backup.description = "Test backup"
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service, \
             patch('app.backups.router.BackupResponse') as mock_response:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.create_backup.return_value = mock_backup
            mock_response.from_orm.return_value = {"id": 1, "name": "test-backup"}
            
            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "test-backup",
                    "description": "Test backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 201
            mock_auth.check_server_access.assert_called_once_with(1, mock_user_admin, mock.ANY)
            mock_backup_service.create_backup.assert_called_once()
    
    def test_create_backup_success_operator(self, client, mock_user_operator):
        """Test successful backup creation by operator"""
        mock_backup = Mock()
        mock_backup.id = 1
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_operator), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service, \
             patch('app.backups.router.BackupResponse') as mock_response:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.create_backup.return_value = mock_backup
            mock_response.from_orm.return_value = {"id": 1}
            
            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "test-backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 201
    
    def test_create_backup_forbidden_user(self, client, mock_user_regular):
        """Test backup creation forbidden for regular user"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_regular), \
             patch('app.backups.router.authorization_service') as mock_auth:
            
            mock_auth.check_server_access.return_value = None
            
            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "test-backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 403
            assert "Only operators and admins can create backups" in response.json()["detail"]
    
    def test_create_backup_server_not_found(self, client, mock_user_admin):
        """Test backup creation when server not found"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth:
            
            mock_auth.check_server_access.side_effect = ServerNotFoundException("Server not found")
            
            response = client.post(
                "/api/v1/servers/999/backups",
                json={
                    "name": "test-backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 404
    
    def test_create_backup_file_operation_error(self, client, mock_user_admin):
        """Test backup creation with file operation error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.create_backup.side_effect = FileOperationException("File error")
            
            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "test-backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 500
    
    def test_create_backup_database_error(self, client, mock_user_admin):
        """Test backup creation with database error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.create_backup.side_effect = DatabaseOperationException("DB error")
            
            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "test-backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 500
    
    def test_create_backup_general_error(self, client, mock_user_admin):
        """Test backup creation with general error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.create_backup.side_effect = ValueError("Unexpected error")
            
            response = client.post(
                "/api/v1/servers/1/backups",
                json={
                    "name": "test-backup",
                    "backup_type": "manual"
                }
            )
            
            assert response.status_code == 500
            assert "Failed to create backup" in response.json()["detail"]


class TestListBackups:
    """Test backup listing endpoints"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_user_admin(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        return user
    
    @pytest.fixture
    def mock_user_regular(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        return user
    
    def test_list_server_backups_success(self, client, mock_user_admin):
        """Test successful server backup listing"""
        mock_backups = [Mock(id=1), Mock(id=2)]
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service, \
             patch('app.backups.router.BackupResponse') as mock_response:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.list_backups.return_value = {
                "backups": mock_backups,
                "total": 2,
                "page": 1,
                "size": 50
            }
            mock_response.from_orm.side_effect = lambda x: {"id": x.id}
            
            response = client.get("/api/v1/servers/1/backups")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
            assert data["page"] == 1
            assert len(data["backups"]) == 2
    
    def test_list_server_backups_with_filters(self, client, mock_user_admin):
        """Test server backup listing with filters"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service, \
             patch('app.backups.router.BackupResponse') as mock_response:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.list_backups.return_value = {
                "backups": [],
                "total": 0,
                "page": 2,
                "size": 10
            }
            mock_response.from_orm.side_effect = lambda x: {"id": x.id}
            
            response = client.get(
                "/api/v1/servers/1/backups?page=2&size=10&backup_type=manual"
            )
            
            assert response.status_code == 200
            mock_backup_service.list_backups.assert_called_once_with(
                server_id=1,
                backup_type=BackupType.manual,
                page=2,
                size=10,
                db=mock.ANY
            )
    
    def test_list_server_backups_error(self, client, mock_user_admin):
        """Test server backup listing with error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.list_backups.side_effect = Exception("Database error")
            
            response = client.get("/api/v1/servers/1/backups")
            
            assert response.status_code == 500
            assert "Failed to list backups" in response.json()["detail"]
    
    def test_list_all_backups_admin_success(self, client, mock_user_admin):
        """Test successful listing of all backups by admin"""
        mock_backups = [Mock(id=1), Mock(id=2), Mock(id=3)]
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service, \
             patch('app.backups.router.BackupResponse') as mock_response:
            
            mock_backup_service.list_backups.return_value = {
                "backups": mock_backups,
                "total": 3,
                "page": 1,
                "size": 50
            }
            mock_response.from_orm.side_effect = lambda x: {"id": x.id}
            
            response = client.get("/api/v1/backups")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 3
            assert len(data["backups"]) == 3
    
    def test_list_all_backups_forbidden_user(self, client, mock_user_regular):
        """Test all backups listing forbidden for regular user"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_regular):
            
            response = client.get("/api/v1/backups")
            
            assert response.status_code == 403
            assert "Only admins can view all backups" in response.json()["detail"]
    
    def test_list_all_backups_error(self, client, mock_user_admin):
        """Test all backups listing with error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_backup_service.list_backups.side_effect = Exception("Service error")
            
            response = client.get("/api/v1/backups")
            
            assert response.status_code == 500
            assert "Failed to list all backups" in response.json()["detail"]


class TestGetBackup:
    """Test backup retrieval endpoint"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_user(self):
        user = Mock(spec=User)
        user.id = 1
        return user
    
    def test_get_backup_success(self, client, mock_user):
        """Test successful backup retrieval"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.name = "test-backup"
        
        with patch('app.backups.router.get_current_user', return_value=mock_user), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.BackupResponse') as mock_response:
            
            mock_auth.check_backup_access.return_value = mock_backup
            mock_response.from_orm.return_value = {"id": 1, "name": "test-backup"}
            
            response = client.get("/api/v1/backups/1")
            
            assert response.status_code == 200
            mock_auth.check_backup_access.assert_called_once_with(1, mock_user, mock.ANY)
    
    def test_get_backup_not_found(self, client, mock_user):
        """Test backup retrieval when backup not found"""
        with patch('app.backups.router.get_current_user', return_value=mock_user), \
             patch('app.backups.router.authorization_service') as mock_auth:
            
            mock_auth.check_backup_access.side_effect = HTTPException(
                status_code=404, detail="Backup not found"
            )
            
            response = client.get("/api/v1/backups/999")
            
            assert response.status_code == 404
    
    def test_get_backup_error(self, client, mock_user):
        """Test backup retrieval with error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user), \
             patch('app.backups.router.authorization_service') as mock_auth:
            
            mock_auth.check_backup_access.side_effect = Exception("Unexpected error")
            
            response = client.get("/api/v1/backups/1")
            
            assert response.status_code == 500
            assert "Failed to get backup" in response.json()["detail"]


class TestRestoreBackup:
    """Test backup restoration endpoints"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_user_admin(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        return user
    
    @pytest.fixture
    def mock_user_regular(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        return user
    
    def test_restore_backup_success(self, client, mock_user_admin):
        """Test successful backup restoration"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.server_id = 1
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_backup_access.return_value = mock_backup
            mock_auth.check_server_access.return_value = None
            mock_backup_service.restore_backup.return_value = True
            
            response = client.post(
                "/api/v1/backups/1/restore",
                json={"confirm": True}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "restored successfully" in data["message"]
    
    def test_restore_backup_with_target_server(self, client, mock_user_admin):
        """Test backup restoration to different target server"""
        mock_backup = Mock()
        mock_backup.id = 1
        mock_backup.server_id = 1
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_backup_access.return_value = mock_backup
            mock_auth.check_server_access.return_value = None
            mock_backup_service.restore_backup.return_value = True
            
            response = client.post(
                "/api/v1/backups/1/restore",
                json={"target_server_id": 2, "confirm": True}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["details"]["target_server_id"] == 2
            mock_auth.check_server_access.assert_called_with(2, mock_user_admin, mock.ANY)
    
    def test_restore_backup_forbidden_user(self, client, mock_user_regular):
        """Test backup restoration forbidden for regular user"""
        mock_backup = Mock()
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_regular), \
             patch('app.backups.router.authorization_service') as mock_auth:
            
            mock_auth.check_backup_access.return_value = mock_backup
            
            response = client.post(
                "/api/v1/backups/1/restore",
                json={"confirm": True}
            )
            
            assert response.status_code == 403
            assert "Only operators and admins can restore backups" in response.json()["detail"]


class TestScheduledBackups:
    """Test scheduled backup endpoint"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_user_admin(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        return user
    
    @pytest.fixture
    def mock_user_regular(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        return user
    
    def test_create_scheduled_backups_success(self, client, mock_user_admin):
        """Test successful scheduled backup creation"""
        mock_backup1 = Mock()
        mock_backup1.id = 1
        mock_backup2 = Mock()
        mock_backup2.id = 2
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_backup_service.create_scheduled_backup.side_effect = [mock_backup1, mock_backup2]
            
            response = client.post(
                "/api/v1/backups/scheduled",
                json={"server_ids": [1, 2]}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["details"]["total_created"] == 2
            assert data["details"]["created_backups"] == [1, 2]
    
    def test_create_scheduled_backups_partial_failure(self, client, mock_user_admin):
        """Test scheduled backup creation with partial failures"""
        mock_backup = Mock()
        mock_backup.id = 1
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            # First succeeds, second fails, third returns None
            mock_backup_service.create_scheduled_backup.side_effect = [
                mock_backup, Exception("Error"), None
            ]
            
            response = client.post(
                "/api/v1/backups/scheduled",
                json={"server_ids": [1, 2, 3]}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True  # At least one succeeded
            assert data["details"]["total_created"] == 1
            assert data["details"]["failed_servers"] == [2, 3]
    
    def test_create_scheduled_backups_all_fail(self, client, mock_user_admin):
        """Test scheduled backup creation when all fail"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_backup_service.create_scheduled_backup.side_effect = Exception("Error")
            
            response = client.post(
                "/api/v1/backups/scheduled",
                json={"server_ids": [1, 2]}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["details"]["total_created"] == 0
            assert data["details"]["failed_servers"] == [1, 2]
    
    def test_create_scheduled_backups_forbidden_user(self, client, mock_user_regular):
        """Test scheduled backup creation forbidden for regular user"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_regular):
            
            response = client.post(
                "/api/v1/backups/scheduled",
                json={"server_ids": [1, 2]}
            )
            
            assert response.status_code == 403
            assert "Only admins can create scheduled backups" in response.json()["detail"]
    
    def test_create_scheduled_backups_error(self, client, mock_user_admin):
        """Test scheduled backup creation with general error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            # Mock an error before we even process servers
            mock_backup_service.create_scheduled_backup.side_effect = RuntimeError("Service down")
            
            response = client.post(
                "/api/v1/backups/scheduled",
                json={"server_ids": [1]}
            )
            
            assert response.status_code == 200  # Still returns 200 with details about failures


class TestDeleteBackup:
    """Test backup deletion endpoint"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_user_admin(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        return user
    
    @pytest.fixture
    def mock_user_regular(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        return user
    
    def test_delete_backup_success(self, client, mock_user_admin):
        """Test successful backup deletion"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_backup_access.return_value = Mock()
            mock_backup_service.delete_backup.return_value = True
            
            response = client.delete("/api/v1/backups/1")
            
            assert response.status_code == 204
    
    def test_delete_backup_not_found(self, client, mock_user_admin):
        """Test backup deletion when backup not found"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_backup_access.return_value = Mock()
            mock_backup_service.delete_backup.return_value = False
            
            response = client.delete("/api/v1/backups/999")
            
            assert response.status_code == 404
    
    def test_delete_backup_forbidden_user(self, client, mock_user_regular):
        """Test backup deletion forbidden for regular user"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_regular), \
             patch('app.backups.router.authorization_service') as mock_auth:
            
            mock_auth.check_backup_access.return_value = Mock()
            
            response = client.delete("/api/v1/backups/1")
            
            assert response.status_code == 403
            assert "Only operators and admins can delete backups" in response.json()["detail"]


class TestBackupStatistics:
    """Test backup statistics endpoints"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @pytest.fixture
    def mock_user_admin(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        return user
    
    @pytest.fixture
    def mock_user_regular(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        return user
    
    def test_get_server_backup_statistics_success(self, client, mock_user_admin):
        """Test successful server backup statistics retrieval"""
        mock_stats = {
            "total_backups": 10,
            "successful_backups": 9,
            "failed_backups": 1,
            "total_size": 1024000
        }
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.get_backup_statistics.return_value = mock_stats
            
            response = client.get("/api/v1/servers/1/backups/statistics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_backups"] == 10
            assert data["successful_backups"] == 9
    
    def test_get_server_backup_statistics_error(self, client, mock_user_admin):
        """Test server backup statistics with error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.authorization_service') as mock_auth, \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_auth.check_server_access.return_value = None
            mock_backup_service.get_backup_statistics.side_effect = Exception("Stats error")
            
            response = client.get("/api/v1/servers/1/backups/statistics")
            
            assert response.status_code == 500
            assert "Failed to get backup statistics" in response.json()["detail"]
    
    def test_get_global_backup_statistics_success(self, client, mock_user_admin):
        """Test successful global backup statistics retrieval"""
        mock_stats = {
            "total_backups": 100,
            "successful_backups": 95,
            "failed_backups": 5,
            "total_size": 10240000
        }
        
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_backup_service.get_backup_statistics.return_value = mock_stats
            
            response = client.get("/api/v1/backups/statistics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_backups"] == 100
    
    def test_get_global_backup_statistics_forbidden_user(self, client, mock_user_regular):
        """Test global backup statistics forbidden for regular user"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_regular):
            
            response = client.get("/api/v1/backups/statistics")
            
            assert response.status_code == 403
            assert "Only admins can view global backup statistics" in response.json()["detail"]
    
    def test_get_global_backup_statistics_error(self, client, mock_user_admin):
        """Test global backup statistics with error"""
        with patch('app.backups.router.get_current_user', return_value=mock_user_admin), \
             patch('app.backups.router.backup_service') as mock_backup_service:
            
            mock_backup_service.get_backup_statistics.side_effect = Exception("Stats error")
            
            response = client.get("/api/v1/backups/statistics")
            
            assert response.status_code == 500
            assert "Failed to get global backup statistics" in response.json()["detail"]