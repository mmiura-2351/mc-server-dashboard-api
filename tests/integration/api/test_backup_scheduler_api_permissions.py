import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.users.models import User, Role
from app.servers.models import Server
from app.backups.models import BackupSchedule, ScheduleAction
from app.auth.auth import create_access_token


class TestBackupSchedulerAPIPermissions:
    """Backup scheduler API permission tests"""

    @pytest.fixture
    def client(self):
        """Test client"""
        return TestClient(app)

    # Use admin_user from conftest.py

    @pytest.fixture
    def operator_user(self, db: Session):
        """Operator user"""
        # Check if operator user already exists
        existing_user = db.query(User).filter_by(username="operator_user").first()
        if existing_user:
            return existing_user

        user = User(
            username="operator_user",
            email="operator@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def regular_user(self, db: Session):
        """Regular user"""
        # Check if regular user already exists
        existing_user = db.query(User).filter_by(username="regular_user").first()
        if existing_user:
            return existing_user

        user = User(
            username="regular_user",
            email="user@example.com",
            hashed_password="hashed_password",
            role=Role.user,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def other_user(self, db: Session):
        """Other user (not server owner)"""
        # Check if other user already exists
        existing_user = db.query(User).filter_by(username="other_user").first()
        if existing_user:
            return existing_user

        user = User(
            username="other_user",
            email="other@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def owner_server(self, db: Session, operator_user: User):
        """Server owned by operator user"""
        server = Server(
            name="owner-test-server",
            description="Owner test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25580,
            max_memory=1024,
            max_players=20,
            owner_id=operator_user.id,
            directory_path="/servers/owner-test-server",
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        return server

    @pytest.fixture
    def admin_server(self, db: Session, admin_user: User):
        """Server owned by admin user"""
        server = Server(
            name="admin-test-server",
            description="Admin test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25581,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
            directory_path="/servers/admin-test-server",
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        return server

    def get_auth_headers(self, user: User):
        """Get authentication header"""
        token = create_access_token(data={"sub": user.username})
        return {"Authorization": f"Bearer {token}"}

    def test_create_schedule_as_server_owner(
        self, client: TestClient, db: Session, operator_user: User, owner_server: Server
    ):
        """Server owner can create schedule"""
        headers = self.get_auth_headers(operator_user)

        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 10,
                "enabled": True,
                "only_when_running": True,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["server_id"] == owner_server.id
        assert data["interval_hours"] == 12
        assert data["max_backups"] == 10
        assert data["enabled"] is True
        assert data["only_when_running"] is True

    def test_create_schedule_as_admin(
        self, client: TestClient, db: Session, admin_user: User, owner_server: Server
    ):
        """Admin can create schedule for other user's server"""
        headers = self.get_auth_headers(admin_user)

        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 24,
                "max_backups": 5,
                "enabled": True,
                "only_when_running": False,
            },
        )

        assert response.status_code == 201

    def test_create_schedule_as_non_owner_forbidden(
        self, client: TestClient, db: Session, other_user: User, owner_server: Server
    ):
        """Non-owner user cannot create schedule"""
        headers = self.get_auth_headers(other_user)

        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={"interval_hours": 12, "max_backups": 10},
        )

        assert response.status_code == 403
        assert "access" in response.json()["detail"].lower()

    def test_create_schedule_as_regular_user_forbidden(
        self, client: TestClient, db: Session, regular_user: User, owner_server: Server
    ):
        """Regular user cannot create schedule"""
        headers = self.get_auth_headers(regular_user)

        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={"interval_hours": 12, "max_backups": 10},
        )

        assert response.status_code == 403

    def test_get_schedule_as_server_owner(
        self, client: TestClient, db: Session, operator_user: User, owner_server: Server
    ):
        """Server owner can get schedule"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).delete()
        db.commit()

        # Clear scheduler cache to avoid conflicts with other tests
        from app.services.backup_scheduler import backup_scheduler

        backup_scheduler.clear_cache()

        # Create schedule
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=6,
            max_backups=15,
            enabled=True,
            only_when_running=True,
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)

        response = client.get(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == owner_server.id
        assert data["interval_hours"] == 6
        assert data["max_backups"] == 15
        assert data["enabled"] is True
        assert data["only_when_running"] is True

    def test_get_schedule_as_admin(
        self, client: TestClient, db: Session, admin_user: User, owner_server: Server
    ):
        """Admin can get schedule for other user's server"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).delete()
        db.commit()

        # Create schedule
        schedule = BackupSchedule(
            server_id=owner_server.id, interval_hours=8, max_backups=12
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(admin_user)

        response = client.get(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
        )

        assert response.status_code == 200

    def test_get_schedule_as_non_owner_forbidden(
        self, client: TestClient, db: Session, other_user: User, owner_server: Server
    ):
        """Non-owner user cannot get schedule"""
        headers = self.get_auth_headers(other_user)

        response = client.get(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
        )

        assert response.status_code == 403

    def test_update_schedule_as_server_owner(
        self, client: TestClient, db: Session, operator_user: User, owner_server: Server
    ):
        """Server owner can update schedule"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).delete()
        db.commit()

        # Create schedule
        schedule = BackupSchedule(
            server_id=owner_server.id, interval_hours=12, max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)

        response = client.put(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={"interval_hours": 6, "max_backups": 20, "enabled": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["interval_hours"] == 6
        assert data["max_backups"] == 20
        assert data["enabled"] is False

    def test_update_schedule_as_non_owner_forbidden(
        self, client: TestClient, db: Session, other_user: User, owner_server: Server
    ):
        """Non-owner user cannot update schedule"""
        headers = self.get_auth_headers(other_user)

        response = client.put(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={"interval_hours": 24, "max_backups": 5},
        )

        assert response.status_code == 403

    def test_delete_schedule_as_server_owner(
        self, client: TestClient, db: Session, operator_user: User, owner_server: Server
    ):
        """Server owner can delete schedule"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).delete()
        db.commit()

        # Create schedule
        schedule = BackupSchedule(
            server_id=owner_server.id, interval_hours=12, max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)

        response = client.delete(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
        )

        assert response.status_code == 204

        # Confirm deletion
        deleted_schedule = (
            db.query(BackupSchedule)
            .filter(BackupSchedule.server_id == owner_server.id)
            .first()
        )
        assert deleted_schedule is None

    def test_delete_schedule_as_admin(
        self, client: TestClient, db: Session, admin_user: User, owner_server: Server
    ):
        """Admin can delete schedule for other user's server"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).delete()
        db.commit()

        # Create schedule
        schedule = BackupSchedule(
            server_id=owner_server.id, interval_hours=12, max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(admin_user)

        response = client.delete(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
        )

        assert response.status_code == 204

    def test_delete_schedule_as_non_owner_forbidden(
        self, client: TestClient, db: Session, other_user: User, owner_server: Server
    ):
        """Non-owner user cannot delete schedule"""
        headers = self.get_auth_headers(other_user)

        response = client.delete(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
        )

        assert response.status_code == 403

    def test_scheduler_status_admin_only(
        self, client: TestClient, db: Session, admin_user: User, operator_user: User
    ):
        """Only admin can access scheduler status"""
        # Admin access
        headers = self.get_auth_headers(admin_user)
        response = client.get(
            "/api/v1/backup-scheduler/scheduler/status", headers=headers
        )
        assert response.status_code == 200

        # Non-admin access
        headers = self.get_auth_headers(operator_user)
        response = client.get(
            "/api/v1/backup-scheduler/scheduler/status", headers=headers
        )
        assert response.status_code == 403

    def test_create_schedule_validation_errors(
        self, client: TestClient, db: Session, operator_user: User, owner_server: Server
    ):
        """Schedule creation validation error test"""
        headers = self.get_auth_headers(operator_user)

        # interval_hours out of range
        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 0,  # Invalid value
                "max_backups": 10,
            },
        )
        assert response.status_code == 422

        # max_backups out of range
        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 50,  # Invalid value
            },
        )
        assert response.status_code == 422

    def test_create_schedule_duplicate_server(
        self, client: TestClient, db: Session, operator_user: User, owner_server: Server
    ):
        """Duplicate schedule creation error test"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).delete()
        db.commit()

        # Create existing schedule
        schedule = BackupSchedule(
            server_id=owner_server.id, interval_hours=12, max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)

        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={"interval_hours": 24, "max_backups": 5},
        )

        assert response.status_code == 409
        assert "already has" in response.json()["detail"].lower()

    def test_operations_on_nonexistent_server(
        self, client: TestClient, db: Session, operator_user: User
    ):
        """Test operations on non-existent server"""
        headers = self.get_auth_headers(operator_user)
        nonexistent_server_id = 99999

        # Create
        response = client.post(
            f"/api/v1/backup-scheduler/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers,
            json={"interval_hours": 12, "max_backups": 10},
        )
        assert response.status_code == 404

        # Get
        response = client.get(
            f"/api/v1/backup-scheduler/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers,
        )
        assert response.status_code == 404

        # Update
        response = client.put(
            f"/api/v1/backup-scheduler/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers,
            json={"interval_hours": 24},
        )
        assert response.status_code == 404

        # Delete
        response = client.delete(
            f"/api/v1/backup-scheduler/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers,
        )
        assert response.status_code == 404
