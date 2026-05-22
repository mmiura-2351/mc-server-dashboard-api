"""Fixed comprehensive tests for backup router endpoints.

Migrated under #227: the legacy `@patch("app.services.backup_service.backup_service.X")`
sites are replaced by `app.dependency_overrides[get_backup_service]`
fixtures (D-4). The service is mocked with `AsyncMock(spec=BackupService)`
so async method semantics (and signature checks) carry through.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status

from app.auth.auth import create_access_token
from app.backups.api.dependencies import get_backup_service
from app.backups.application.service import BackupService
from app.backups.domain.entities import (
    BackupEntity,
    BackupListPage,
    BackupStatistics,
)
from app.core.exceptions import (
    BackupNotFoundException,
    FileOperationException,
    ServerNotFoundException,
)
from app.main import app
from app.servers.models import Backup, BackupStatus, BackupType, Server, ServerType
from app.users.domain.value_objects import Role
from app.users.models import User


def get_auth_headers(username: str):
    """Generate authentication headers"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


def make_entity(
    *,
    id: int,
    server_id: int,
    name: str,
    backup_type: BackupType = BackupType.manual,
    status: BackupStatus = BackupStatus.completed,
    file_path: str = "/backups/x.tar.gz",
    file_size: int = 1024,
    description=None,
    server_name=None,
    minecraft_version=None,
    created_at=None,
) -> BackupEntity:
    """Helper to build a domain entity for AsyncMock return values."""
    return BackupEntity(
        id=id,
        server_id=server_id,
        name=name,
        description=description,
        file_path=file_path,
        file_size=file_size,
        backup_type=backup_type,
        status=status,
        created_at=created_at or datetime.now(),
        server_name=server_name,
        minecraft_version=minecraft_version,
    )


@pytest.fixture
def mock_backup_service():
    """Replace the DI-injected `BackupService` with an AsyncMock.

    The fixture installs the override on the shared `app.dependency_overrides`
    dict; it is removed in teardown so other tests are not affected.
    """
    mock = AsyncMock(spec=BackupService)
    app.dependency_overrides[get_backup_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_backup_service, None)


class TestBackupRouterFixed:
    """Fixed comprehensive test backup router endpoints with proper mocking"""

    def test_create_backup_success(self, client, test_user, db, mock_backup_service):
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

        with patch(
            "app.servers.application.authorization.AuthorizationService.check_server_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = server
            mock_backup_service.create_backup.return_value = make_entity(
                id=1,
                server_id=1,
                name="Test Backup",
                description="Test description",
                backup_type=BackupType.manual,
                status=BackupStatus.completed,
                file_path="/backups/test.tar.gz",
                file_size=1024,
            )

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

            mock_auth.assert_called_once()
            mock_backup_service.create_backup.assert_called_once()

    def test_create_backup_not_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users are not forbidden from creating backups (Phase 1: shared resource model)"""
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

        response = client.post(
            "/api/v1/backups/servers/1/backups",
            json={
                "name": "Test Backup",
                "description": "Test description",
                "backup_type": "manual",
            },
            headers=get_auth_headers(test_user.username),
        )

        # Phase 1: Regular users should NOT get 403 Forbidden for backup creation
        # (May get other errors due to mocking/setup, but not authorization errors)
        assert response.status_code != status.HTTP_403_FORBIDDEN, (
            f"Regular users should not be forbidden from creating backups in Phase 1. Got {response.status_code}: {response.json() if response.status_code != 500 else 'Internal Server Error'}"
        )

    def test_create_backup_server_not_found(self, client, test_user):
        """Test backup creation when server doesn't exist"""
        test_user.role = Role.operator

        with patch(
            "app.servers.application.authorization.AuthorizationService.check_server_access",
            new_callable=AsyncMock,
        ) as mock_auth:
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

    def test_create_backup_file_operation_error(
        self, client, test_user, db, mock_backup_service
    ):
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
            "app.servers.application.authorization.AuthorizationService.check_server_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = server
            mock_backup_service.create_backup.side_effect = FileOperationException(
                "create", "backup", "Failed to create backup"
            )

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

    def test_list_server_backups(self, client, test_user, db, mock_backup_service):
        """Test listing backups for a specific server"""
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
            "app.servers.application.authorization.AuthorizationService.check_server_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = server
            mock_backup_service.list_backups.return_value = BackupListPage(
                entities=[
                    make_entity(
                        id=1,
                        server_id=1,
                        name="Backup 1",
                        backup_type=BackupType.manual,
                        file_path="/backups/backup1.tar.gz",
                        file_size=1024,
                    ),
                    make_entity(
                        id=2,
                        server_id=1,
                        name="Backup 2",
                        backup_type=BackupType.scheduled,
                        file_path="/backups/backup2.tar.gz",
                        file_size=2048,
                    ),
                ],
                total=2,
                page=1,
                size=50,
            )

            response = client.get(
                "/api/v1/backups/servers/1/backups",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total"] == 2
            assert len(data["backups"]) == 2
            assert data["backups"][0]["name"] == "Backup 1"

            mock_auth.assert_called_once()
            mock_backup_service.list_backups.assert_called_once()

    def test_list_server_backups_with_pagination(
        self, client, test_user, db, mock_backup_service
    ):
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

        with patch(
            "app.servers.application.authorization.AuthorizationService.check_server_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = server
            mock_backup_service.list_backups.return_value = BackupListPage(
                entities=[], total=0, page=2, size=10
            )

            response = client.get(
                "/api/v1/backups/servers/1/backups?page=2&size=10&backup_type=manual",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["page"] == 2
            assert data["size"] == 10

            mock_backup_service.list_backups.assert_called_once()
            call_kwargs = mock_backup_service.list_backups.call_args.kwargs
            assert call_kwargs["server_id"] == 1
            assert call_kwargs["backup_type"] == BackupType.manual
            assert call_kwargs["page"] == 2
            assert call_kwargs["size"] == 10

    def test_list_all_backups_admin_only(self, client, admin_user, mock_backup_service):
        """Test that only admins can list all backups"""
        mock_backup_service.list_backups.return_value = BackupListPage(
            entities=[], total=0, page=1, size=50
        )

        response = client.get(
            "/api/v1/backups/backups", headers=get_auth_headers(admin_user.username)
        )
        assert response.status_code == status.HTTP_200_OK
        mock_backup_service.list_backups.assert_called_once()

    def test_list_all_backups_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot list all backups"""
        response = client.get(
            "/api/v1/backups/backups", headers=get_auth_headers(test_user.username)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admins can view all backups" in response.json()["detail"]

    def test_get_backup_by_id(self, client, test_user, db):
        """Test getting backup details by ID"""
        # The router now serialises via `backup_entity_to_response`,
        # so the mock must return a domain entity (post-#228 PR 2b).
        backup_entity = make_entity(
            id=1,
            server_id=1,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/backups/test.tar.gz",
            file_size=1024,
        )

        with patch(
            "app.servers.application.authorization.AuthorizationService.check_backup_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = backup_entity

            response = client.get(
                "/api/v1/backups/backups/1", headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["id"] == 1
            assert data["name"] == "Test Backup"

            # Verify authorization check
            mock_auth.assert_called_once()

    def test_get_backup_not_found(self, client, test_user):
        """Test getting backup that doesn't exist"""
        with patch(
            "app.servers.application.authorization.AuthorizationService.check_backup_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.side_effect = BackupNotFoundException("Backup not found")

            response = client.get(
                "/api/v1/backups/backups/999",
                headers=get_auth_headers(test_user.username),
            )
            assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_backup(self, client, test_user, db, mock_backup_service):
        """Test deleting a backup as server owner"""
        # Create a server owned by test_user
        server = Server(
            id=1,
            name="Test User Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/test-server",
            port=25565,
            owner_id=test_user.id,  # Owned by test_user
            is_deleted=False,
        )
        db.add(server)
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
        backup.server = server  # Set up relationship
        db.add(backup)
        db.commit()

        with (
            patch(
                "app.servers.application.authorization.AuthorizationService.check_backup_access",
                new_callable=AsyncMock,
            ) as mock_auth,
            patch(
                "app.servers.application.authorization.AuthorizationService.can_delete_backup"
            ) as mock_can_delete,
        ):
            mock_auth.return_value = backup
            mock_can_delete.return_value = True  # Server owner can delete
            mock_backup_service.delete_backup.return_value = True

            response = client.delete(
                "/api/v1/backups/backups/1", headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT

            mock_auth.assert_called_once()
            mock_can_delete.assert_called_once()
            mock_backup_service.delete_backup.assert_called_once()

    def test_delete_backup_forbidden_for_regular_user(self, client, test_user, db):
        """Test that regular users cannot delete backups they don't own"""
        # Ensure user has regular role
        assert test_user.role == Role.user

        # Create a server owned by a different user
        other_user = User(
            id=999,
            username="otheruser",
            email="other@example.com",
            hashed_password="hashed",
            role=Role.user,
            is_approved=True,
        )
        db.add(other_user)
        db.commit()

        server = Server(
            id=1,
            name="Other User Server",
            minecraft_version="1.20.4",
            server_type=ServerType.vanilla,
            directory_path="/servers/other-server",
            port=25565,
            owner_id=other_user.id,  # Owned by different user
            is_deleted=False,
        )
        db.add(server)
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
        backup.server = server  # Set up relationship
        db.add(backup)
        db.commit()

        with (
            patch(
                "app.servers.application.authorization.AuthorizationService.check_backup_access",
                new_callable=AsyncMock,
            ) as mock_auth,
            patch(
                "app.servers.application.authorization.AuthorizationService.can_delete_backup"
            ) as mock_can_delete,
        ):
            mock_auth.return_value = backup
            mock_can_delete.return_value = False  # Not owner, not admin

            response = client.delete(
                "/api/v1/backups/backups/1", headers=get_auth_headers(test_user.username)
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert (
                "Only admins and server owners can delete backups"
                in response.json()["detail"]
            )

    def test_backup_statistics_server_specific(
        self, client, test_user, db, mock_backup_service
    ):
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

        with patch(
            "app.servers.application.authorization.AuthorizationService.check_server_access",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = server
            mock_backup_service.get_backup_statistics.return_value = BackupStatistics(
                total_backups=5,
                completed_backups=4,
                failed_backups=1,
                total_size_bytes=1024000,
            )

            response = client.get(
                "/api/v1/backups/servers/1/backups/statistics",
                headers=get_auth_headers(test_user.username),
            )

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total_backups"] == 5
            assert data["completed_backups"] == 4

            mock_auth.assert_called_once()
            mock_backup_service.get_backup_statistics.assert_called_once()

    def test_global_backup_statistics_admin_only(
        self, client, admin_user, mock_backup_service
    ):
        """Test getting global backup statistics (admin only)"""
        mock_backup_service.get_backup_statistics.return_value = BackupStatistics(
            total_backups=50,
            completed_backups=45,
            failed_backups=5,
            total_size_bytes=10240000,
        )

        response = client.get(
            "/api/v1/backups/backups/statistics",
            headers=get_auth_headers(admin_user.username),
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_backups"] == 50
        mock_backup_service.get_backup_statistics.assert_called_once()

    def test_global_backup_statistics_forbidden_for_non_admin(self, client, test_user):
        """Test that non-admins cannot access global backup statistics"""
        response = client.get(
            "/api/v1/backups/backups/statistics",
            headers=get_auth_headers(test_user.username),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert (
            "Only admins can view global backup statistics" in response.json()["detail"]
        )

    def test_create_scheduled_backups_admin_only(
        self, client, admin_user, mock_backup_service
    ):
        """Test creating scheduled backups (admin only)"""
        mock_backup_service.create_scheduled_backup.side_effect = [
            make_entity(
                id=1,
                server_id=1,
                name="Scheduled Backup 1",
                backup_type=BackupType.scheduled,
                file_path="/backups/scheduled1.tar.gz",
                file_size=1024,
            ),
            make_entity(
                id=2,
                server_id=2,
                name="Scheduled Backup 2",
                backup_type=BackupType.scheduled,
                file_path="/backups/scheduled2.tar.gz",
                file_size=2048,
            ),
        ]

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
            },
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
        import os
        import tempfile

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
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp_file:
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
            assert "attachment" in response.headers.get("content-disposition", "")
            assert "Test Server_Test Backup_1.tar.gz" in response.headers.get(
                "content-disposition", ""
            )

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

    def test_download_backup_file_not_exist(self, client, test_user, db):
        """Test download backup when file doesn't exist on disk"""
        # Create a server owned by test_user
        server = Server(
            id=1,
            name="Test User's Server",
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

        # Create a backup with non-existent file path
        backup = Backup(
            id=1,
            server_id=server.id,
            name="Test Backup",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
            file_path="/tmp/nonexistent_backup.tar.gz",  # Non-existent file
            file_size=1024,
            created_at=datetime.now(),
        )
        backup.server = server
        db.add(backup)
        db.commit()

        # Try to download (should fail because file doesn't exist)
        response = client.get(
            f"/api/v1/backups/backups/{backup.id}/download",
            headers=get_auth_headers(test_user.username),
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Backup file not found on disk" in response.json()["detail"]

    def test_upload_backup_success(self, client, test_user, db):
        """Test successful backup upload"""
        import io
        import tarfile
        import tempfile

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
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
            # Create a minimal tar.gz content
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
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
            with open(tmp_file.name, "rb") as f:
                response = client.post(
                    f"/api/v1/backups/servers/{server.id}/backups/upload",
                    files={"file": ("test_backup.tar.gz", f, "application/gzip")},
                    data={
                        "name": "Test Upload",
                        "description": "Test upload description",
                    },
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

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp_file:
            tmp_file.write(b"not a tar.gz file")
            tmp_file.flush()

        try:
            with open(tmp_file.name, "rb") as f:
                response = client.post(
                    f"/api/v1/backups/servers/{server.id}/backups/upload",
                    files={"file": ("test.txt", f, "text/plain")},
                    headers=get_auth_headers(test_user.username),
                )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert (
                "Only .tar.gz and .tgz files are supported" in response.json()["detail"]
            )

        finally:
            # Clean up
            import os

            if os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)

    def test_upload_backup_allowed_for_regular_user(self, client, test_user, db):
        """Test that regular users can now upload backups (Phase 1: shared resource model)"""
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

        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp_file:
            tmp_file.write(b"dummy content")
            tmp_file.flush()

            with open(tmp_file.name, "rb") as f:
                response = client.post(
                    f"/api/v1/backups/servers/{server.id}/backups/upload",
                    files={"file": ("test.tar.gz", f, "application/gzip")},
                    headers=get_auth_headers(test_user.username),
                )

        # Phase 1: Regular users should NOT get 403 Forbidden for backup upload
        # (May get other errors due to file format, but not authorization errors)
        assert response.status_code != status.HTTP_403_FORBIDDEN, (
            f"Regular users should not be forbidden from uploading backups in Phase 1. Got {response.status_code}: {response.json() if response.status_code != 500 else 'Internal Server Error'}"
        )

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

        assert response.status_code == status.HTTP_400_BAD_REQUEST
