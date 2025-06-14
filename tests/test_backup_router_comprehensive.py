"""Fixed comprehensive tests for backup router endpoints"""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

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


class TestBackupRouterFixed:
    """Fixed comprehensive test backup router endpoints with proper mocking"""

    def test_create_backup_success(self, client, test_user, db):
        """Test successful backup creation with proper mocks"""
        # Update test user to operator role
        test_user.role = Role.operator
        db.commit()
        
        # Create a test server in database
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

        # Create expected backup response
        expected_backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            description="Test description",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.now(),
        )

        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth, \
             patch("app.services.backup_service.backup_service.create_backup") as mock_create:
            
            # Mock authorization to return the server (indicating access granted)
            mock_auth.return_value = server
            
            # Mock backup creation to return expected backup
            mock_create.return_value = expected_backup
            
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
            assert data["status"] == "completed"
            
            # Verify service calls with correct parameters
            mock_auth.assert_called_once()
            mock_create.assert_called_once()

    def test_create_backup_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users cannot create backups"""
        # Ensure user has regular role (default from fixture)
        assert test_user.role == Role.user
        
        # Create test server owned by user
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

        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth:
            # Mock authorization to return server (access granted)
            mock_auth.return_value = server

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
            
            # Authorization check should still be called
            mock_auth.assert_called_once()

    def test_create_backup_server_not_found(self, client, test_user):
        """Test backup creation when server doesn't exist"""
        test_user.role = Role.operator
        
        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth:
            # Mock authorization to raise ServerNotFoundException
            mock_auth.side_effect = ServerNotFoundException("Server not found")

            response = client.post(
                "/api/v1/backups/servers/999/backups",
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

        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth, \
             patch("app.services.backup_service.backup_service.create_backup") as mock_create:
            
            mock_auth.return_value = server
            mock_create.side_effect = FileOperationException("create", "backup", "Failed to create backup")

            response = client.post(
                "/api/v1/backups/servers/1/backups",
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
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        # Mock backup list response
        mock_backups = [
            Backup(
                id=1,
                server_id=1,
                name="Backup 1",
                backup_type=BackupType.manual,
                status=BackupStatus.completed,
                file_path="/backups/backup1.tar.gz",
                file_size=1024,
                created_at=datetime.now(),
            ),
            Backup(
                id=2,
                server_id=1,
                name="Backup 2",
                backup_type=BackupType.scheduled,
                status=BackupStatus.completed,
                file_path="/backups/backup2.tar.gz",
                file_size=2048,
                created_at=datetime.now(),
            ),
        ]

        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth, \
             patch("app.services.backup_service.backup_service.list_backups") as mock_list:
            
            mock_auth.return_value = server
            mock_list.return_value = {
                "backups": mock_backups,
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
            
            # Verify service calls
            mock_auth.assert_called_once()
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

        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth, \
             patch("app.services.backup_service.backup_service.list_backups") as mock_list:
            
            mock_auth.return_value = server
            mock_list.return_value = {
                "backups": [],
                "total": 0,
                "page": 2,
                "size": 10,
            }

            response = client.get(
                "/api/v1/backups/servers/1/backups?page=2&size=10&backup_type=manual", 
                headers=get_auth_headers(test_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["page"] == 2
            assert data["size"] == 10
            
            # Verify service was called with correct parameters
            mock_list.assert_called_once()
            call_kwargs = mock_list.call_args.kwargs
            assert call_kwargs["server_id"] == 1
            assert call_kwargs["backup_type"] == BackupType.manual
            assert call_kwargs["page"] == 2
            assert call_kwargs["size"] == 10

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
            
            # Verify service was called without server_id (for all backups)
            mock_list.assert_called_once()

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
            created_at=datetime.now(),
        )

        with patch("app.services.authorization_service.authorization_service.check_backup_access") as mock_auth:
            mock_auth.return_value = backup

            response = client.get(
                "/api/v1/backups/backups/1", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["id"] == 1
            assert data["name"] == "Test Backup"
            
            # Verify authorization check
            mock_auth.assert_called_once()

    def test_get_backup_not_found(self, client, test_user):
        """Test getting backup that doesn't exist"""
        with patch("app.services.authorization_service.authorization_service.check_backup_access") as mock_auth:
            mock_auth.side_effect = BackupNotFoundException("Backup not found")

            response = client.get(
                "/api/v1/backups/backups/999", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_404_NOT_FOUND

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
            created_at=datetime.now(),
        )

        with patch("app.services.authorization_service.authorization_service.check_backup_access") as mock_auth, \
             patch("app.services.backup_service.backup_service.delete_backup") as mock_delete:
            
            mock_auth.return_value = backup
            mock_delete.return_value = True

            response = client.delete(
                "/api/v1/backups/backups/1", 
                headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT
            
            # Verify service calls
            mock_auth.assert_called_once()
            mock_delete.assert_called_once()

    def test_delete_backup_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users cannot delete backups"""
        # Ensure user has regular role
        assert test_user.role == Role.user
        
        backup = Backup(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
            created_at=datetime.now(),
        )

        with patch("app.services.authorization_service.authorization_service.check_backup_access") as mock_auth:
            mock_auth.return_value = backup

            response = client.delete(
                "/api/v1/backups/backups/1", 
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

        mock_stats = {
            "total_backups": 5,
            "completed_backups": 4,
            "failed_backups": 1,
            "total_size_bytes": 1024000,
            "total_size_mb": 1024.0
        }

        with patch("app.services.authorization_service.authorization_service.check_server_access") as mock_auth, \
             patch("app.services.backup_service.backup_service.get_backup_statistics") as mock_stats_call:
            
            mock_auth.return_value = server
            mock_stats_call.return_value = mock_stats

            response = client.get(
                "/api/v1/backups/servers/1/backups/statistics", 
                headers=get_auth_headers(test_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total_backups"] == 5
            assert data["completed_backups"] == 4
            
            # Verify service calls
            mock_auth.assert_called_once()
            mock_stats_call.assert_called_once()

    def test_global_backup_statistics_admin_only(self, client, admin_user):
        """Test getting global backup statistics (admin only)"""
        mock_stats = {
            "total_backups": 50,
            "completed_backups": 45,
            "failed_backups": 5,
            "total_size_bytes": 10240000,
            "total_size_mb": 10240.0
        }

        with patch("app.services.backup_service.backup_service.get_backup_statistics") as mock_stats_call:
            mock_stats_call.return_value = mock_stats

            response = client.get(
                "/api/v1/backups/backups/statistics", 
                headers=get_auth_headers(admin_user.username)
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total_backups"] == 50
            
            # Should be called without server_id for global stats
            mock_stats_call.assert_called_once()

    def test_global_backup_statistics_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot access global backup statistics"""
        response = client.get(
            "/api/v1/backups/backups/statistics", 
            headers=get_auth_headers(test_user.username)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can view global backup statistics" in response.json()["detail"]

    def test_create_scheduled_backups_admin_only(self, client, admin_user):
        """Test creating scheduled backups (admin only)"""
        mock_backup1 = Backup(
            id=1,
            server_id=1,
            name="Scheduled Backup 1",
            backup_type=BackupType.scheduled,
            status=BackupStatus.completed,
            file_path="/backups/scheduled1.tar.gz",
            file_size=1024,
            created_at=datetime.now(),
        )
        mock_backup2 = Backup(
            id=2,
            server_id=2,
            name="Scheduled Backup 2",
            backup_type=BackupType.scheduled,
            status=BackupStatus.completed,
            file_path="/backups/scheduled2.tar.gz",
            file_size=2048,
            created_at=datetime.now(),
        )

        with patch("app.services.backup_service.backup_service.create_scheduled_backup") as mock_create:
            mock_create.side_effect = [mock_backup1, mock_backup2]

            response = client.post(
                "/api/v1/backups/backups/scheduled",
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
            "/api/v1/backups/backups/scheduled",
            json={"server_ids": [1, 2]},
            headers=get_auth_headers(test_user.username),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can create scheduled backups" in response.json()["detail"]

    def test_unauthorized_access(self, client):
        """Test unauthorized access to backup endpoints"""
        # No authentication headers
        response = client.post(
            "/api/v1/backups/servers/1/backups",
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
            "/api/v1/backups/servers/1/backups",
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
            "/api/v1/backups/servers/1/backups",
            json={
                "description": "Missing name and backup_type",
            },
            headers=get_auth_headers(test_user.username),
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_download_backup_success(self, client, test_user, db):
        """Test successful backup download"""
        import tempfile
        import os
        
        # Create a test server in database
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

        # Create a temporary test file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz') as tmp_file:
            tmp_file.write(b"test backup content")
            tmp_path = tmp_file.name

        try:
            # Create a test backup in database
            backup = Backup(
                id=1,
                server_id=server.id,
                name="Test Backup",
                backup_type=BackupType.manual,
                status=BackupStatus.completed,
                file_path=tmp_path,
                file_size=19,
                created_at=datetime.now(),
            )
            backup.server = server  # Set the relationship
            db.add(backup)
            db.commit()

            response = client.get(
                f"/api/v1/backups/backups/{backup.id}/download",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == 200
            assert 'attachment' in response.headers.get('content-disposition', '')
            assert 'Test Server_Test Backup_1.tar.gz' in response.headers.get('content-disposition', '')
            
        finally:
            # Clean up the temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_download_backup_not_completed(self, client, test_user, db):
        """Test download of backup that is not completed"""
        # Create a test server in database
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

        # Create a test backup in database with creating status
        backup = Backup(
            id=1,
            server_id=server.id,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.creating,  # Not completed
            file_path="/tmp/test_backup.tar.gz",
            file_size=1024,
            created_at=datetime.now(),
        )
        backup.server = server  # Set the relationship
        db.add(backup)
        db.commit()

        response = client.get(
            f"/api/v1/backups/backups/{backup.id}/download",
            headers=get_auth_headers(test_user.username),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Backup is not completed" in response.json()["detail"]

    def test_download_backup_file_not_found(self, client, test_user, db):
        """Test download when backup file doesn't exist on disk"""
        # Create a test server in database
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

        # Create a test backup in database
        backup = Backup(
            id=1,
            server_id=server.id,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/tmp/nonexistent_backup.tar.gz",
            file_size=1024,
            created_at=datetime.now(),
        )
        backup.server = server  # Set the relationship
        db.add(backup)
        db.commit()

        # Mock file existence check to return False
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = False

            response = client.get(
                f"/api/v1/backups/backups/{backup.id}/download",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_404_NOT_FOUND
            assert "Backup file not found on disk" in response.json()["detail"]

    def test_download_backup_unauthorized(self, client, test_user, db):
        """Test download backup that user doesn't have access to"""
        # Create another user's server
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        other_user = User(
            username="otheruser",
            email="other@example.com",
            hashed_password=pwd_context.hash("otherpass"),
            role=Role.user,
            is_approved=True,
        )
        db.add(other_user)
        db.commit()
        
        # Create a server owned by other_user
        server = Server(
            id=1,
            name="Other User's Server",
            description="Test server description",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/other-server",
            port=25565,
            owner_id=other_user.id,  # Owned by other_user
            is_deleted=False,
        )
        db.add(server)
        db.commit()

        # Create a backup for other_user's server
        backup = Backup(
            id=1,
            server_id=server.id,
            name="Other User's Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/tmp/other_backup.tar.gz",
            file_size=1024,
            created_at=datetime.now(),
        )
        backup.server = server
        db.add(backup)
        db.commit()

        # Try to download as test_user (should fail)
        response = client.get(
            f"/api/v1/backups/backups/{backup.id}/download",
            headers=get_auth_headers(test_user.username),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_upload_backup_success(self, client, test_user, db):
        """Test successful backup upload"""
        import tempfile
        import tarfile
        import io
        
        # Set test_user as operator to allow backup upload
        test_user.role = Role.operator
        db.commit()
        
        # Create a test server in database
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

        # Create a temporary tar.gz file
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp_file:
            # Create a minimal tar.gz content
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
                # Add a simple text file to the tar
                text_info = tarfile.TarInfo(name="test.txt")
                text_content = b"test content"
                text_info.size = len(text_content)
                tar.addfile(text_info, io.BytesIO(text_content))
            
            tar_content = tar_buffer.getvalue()
            tmp_file.write(tar_content)
            tmp_file.flush()

        try:
            # Test upload
            with open(tmp_file.name, 'rb') as f:
                response = client.post(
                    f"/api/v1/backups/servers/{server.id}/backups/upload",
                    files={"file": ("test_backup.tar.gz", f, "application/gzip")},
                    data={"name": "Test Upload", "description": "Test upload description"},
                    headers=get_auth_headers(test_user.username),
                )

            assert response.status_code == status.HTTP_201_CREATED
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Backup uploaded successfully"
            assert data["backup"]["name"] == "Test Upload"
            assert data["backup"]["description"] == "Test upload description"
            assert data["original_filename"] == "test_backup.tar.gz"
            assert data["file_size"] > 0
            
        finally:
            # Clean up
            import os
            if os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)

    def test_upload_backup_invalid_file_type(self, client, test_user, db):
        """Test upload with invalid file type"""
        # Set test_user as operator to allow backup upload
        test_user.role = Role.operator
        db.commit()
        
        # Create a test server in database
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

        # Create a text file instead of tar.gz
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_file:
            tmp_file.write(b"not a tar.gz file")
            tmp_file.flush()

        try:
            with open(tmp_file.name, 'rb') as f:
                response = client.post(
                    f"/api/v1/backups/servers/{server.id}/backups/upload",
                    files={"file": ("test.txt", f, "text/plain")},
                    headers=get_auth_headers(test_user.username),
                )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Only .tar.gz and .tgz files are supported" in response.json()["detail"]
            
        finally:
            # Clean up
            import os
            if os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)

    def test_upload_backup_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users cannot upload backups"""
        # Create a test server in database
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

        # Create a dummy file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.tar.gz') as tmp_file:
            tmp_file.write(b"dummy content")
            tmp_file.flush()

            with open(tmp_file.name, 'rb') as f:
                response = client.post(
                    f"/api/v1/backups/servers/{server.id}/backups/upload",
                    files={"file": ("test.tar.gz", f, "application/gzip")},
                    headers=get_auth_headers(test_user.username),
                )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only operators and admins can upload backups" in response.json()["detail"]

    def test_upload_backup_no_file(self, client, test_user, db):
        """Test upload without providing a file"""
        # Set test_user as operator to allow backup upload
        test_user.role = Role.operator
        db.commit()
        
        # Create a test server in database
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

        response = client.post(
            f"/api/v1/backups/servers/{server.id}/backups/upload",
            headers=get_auth_headers(test_user.username),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY