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
    """バックアップスケジューラーAPIの権限テスト"""

    @pytest.fixture
    def client(self):
        """テストクライアント"""
        return TestClient(app)

    @pytest.fixture
    def admin_user(self, db: Session):
        """管理者ユーザー"""
        user = User(
            username="admin_user",
            email="admin@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def operator_user(self, db: Session):
        """オペレーターユーザー"""
        user = User(
            username="operator_user",
            email="operator@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def regular_user(self, db: Session):
        """一般ユーザー"""
        user = User(
            username="regular_user",
            email="user@example.com",
            hashed_password="hashed_password",
            role=Role.user,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def other_user(self, db: Session):
        """他のユーザー（サーバー所有者ではない）"""
        user = User(
            username="other_user",
            email="other@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def owner_server(self, db: Session, operator_user: User):
        """オペレーターユーザーが所有するサーバー"""
        server = Server(
            name="owner-test-server",
            description="Owner test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25580,
            max_memory=1024,
            max_players=20,
            owner_id=operator_user.id,
            directory_path="/servers/owner-test-server"
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        return server

    @pytest.fixture
    def admin_server(self, db: Session, admin_user: User):
        """管理者ユーザーが所有するサーバー"""
        server = Server(
            name="admin-test-server",
            description="Admin test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25581,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
            directory_path="/servers/admin-test-server"
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        return server

    def get_auth_headers(self, user: User):
        """認証ヘッダーを取得"""
        token = create_access_token(data={"sub": user.username})
        return {"Authorization": f"Bearer {token}"}

    def test_create_schedule_as_server_owner(self, client: TestClient, db: Session, operator_user: User, owner_server: Server):
        """サーバー所有者がスケジュール作成可能"""
        headers = self.get_auth_headers(operator_user)
        
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 10,
                "enabled": True,
                "only_when_running": True
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["server_id"] == owner_server.id
        assert data["interval_hours"] == 12
        assert data["max_backups"] == 10
        assert data["enabled"] is True
        assert data["only_when_running"] is True

    def test_create_schedule_as_admin(self, client: TestClient, db: Session, admin_user: User, owner_server: Server):
        """管理者が他人のサーバーのスケジュール作成可能"""
        headers = self.get_auth_headers(admin_user)
        
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 24,
                "max_backups": 5,
                "enabled": True,
                "only_when_running": False
            }
        )
        
        assert response.status_code == 201

    def test_create_schedule_as_non_owner_forbidden(self, client: TestClient, db: Session, other_user: User, owner_server: Server):
        """非所有者ユーザーはスケジュール作成不可"""
        headers = self.get_auth_headers(other_user)
        
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 10
            }
        )
        
        assert response.status_code == 403
        assert "access" in response.json()["detail"].lower()

    def test_create_schedule_as_regular_user_forbidden(self, client: TestClient, db: Session, regular_user: User, owner_server: Server):
        """一般ユーザーはスケジュール作成不可"""
        headers = self.get_auth_headers(regular_user)
        
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 10
            }
        )
        
        assert response.status_code == 403

    def test_get_schedule_as_server_owner(self, client: TestClient, db: Session, operator_user: User, owner_server: Server):
        """サーバー所有者がスケジュール取得可能"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(BackupSchedule.server_id == owner_server.id).delete()
        db.commit()
        
        # Clear scheduler cache to avoid conflicts with other tests
        from app.services.new_backup_scheduler import new_backup_scheduler
        new_backup_scheduler.clear_cache()
        
        # スケジュール作成
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=6,
            max_backups=15,
            enabled=True,
            only_when_running=True
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)
        
        response = client.get(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == owner_server.id
        assert data["interval_hours"] == 6
        assert data["max_backups"] == 15
        assert data["enabled"] is True
        assert data["only_when_running"] is True

    def test_get_schedule_as_admin(self, client: TestClient, db: Session, admin_user: User, owner_server: Server):
        """管理者が他人のサーバーのスケジュール取得可能"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(BackupSchedule.server_id == owner_server.id).delete()
        db.commit()
        
        # スケジュール作成
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=8,
            max_backups=12
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(admin_user)
        
        response = client.get(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers
        )
        
        assert response.status_code == 200

    def test_get_schedule_as_non_owner_forbidden(self, client: TestClient, db: Session, other_user: User, owner_server: Server):
        """非所有者ユーザーはスケジュール取得不可"""
        headers = self.get_auth_headers(other_user)
        
        response = client.get(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers
        )
        
        assert response.status_code == 403

    def test_update_schedule_as_server_owner(self, client: TestClient, db: Session, operator_user: User, owner_server: Server):
        """サーバー所有者がスケジュール更新可能"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(BackupSchedule.server_id == owner_server.id).delete()
        db.commit()
        
        # スケジュール作成
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=12,
            max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)
        
        response = client.put(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 6,
                "max_backups": 20,
                "enabled": False
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["interval_hours"] == 6
        assert data["max_backups"] == 20
        assert data["enabled"] is False

    def test_update_schedule_as_non_owner_forbidden(self, client: TestClient, db: Session, other_user: User, owner_server: Server):
        """非所有者ユーザーはスケジュール更新不可"""
        headers = self.get_auth_headers(other_user)
        
        response = client.put(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 24,
                "max_backups": 5
            }
        )
        
        assert response.status_code == 403

    def test_delete_schedule_as_server_owner(self, client: TestClient, db: Session, operator_user: User, owner_server: Server):
        """サーバー所有者がスケジュール削除可能"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(BackupSchedule.server_id == owner_server.id).delete()
        db.commit()
        
        # スケジュール作成
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=12,
            max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)
        
        response = client.delete(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers
        )
        
        assert response.status_code == 204

        # 削除確認
        deleted_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == owner_server.id
        ).first()
        assert deleted_schedule is None

    def test_delete_schedule_as_admin(self, client: TestClient, db: Session, admin_user: User, owner_server: Server):
        """管理者が他人のサーバーのスケジュール削除可能"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(BackupSchedule.server_id == owner_server.id).delete()
        db.commit()
        
        # スケジュール作成
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=12,
            max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(admin_user)
        
        response = client.delete(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers
        )
        
        assert response.status_code == 204

    def test_delete_schedule_as_non_owner_forbidden(self, client: TestClient, db: Session, other_user: User, owner_server: Server):
        """非所有者ユーザーはスケジュール削除不可"""
        headers = self.get_auth_headers(other_user)
        
        response = client.delete(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers
        )
        
        assert response.status_code == 403

    def test_scheduler_status_admin_only(self, client: TestClient, db: Session, admin_user: User, operator_user: User):
        """スケジューラー状態は管理者のみアクセス可能"""
        # 管理者アクセス
        headers = self.get_auth_headers(admin_user)
        response = client.get("/api/v1/backups/scheduler/status", headers=headers)
        assert response.status_code == 200

        # 非管理者アクセス
        headers = self.get_auth_headers(operator_user)
        response = client.get("/api/v1/backups/scheduler/status", headers=headers)
        assert response.status_code == 403

    def test_create_schedule_validation_errors(self, client: TestClient, db: Session, operator_user: User, owner_server: Server):
        """スケジュール作成のバリデーションエラーテスト"""
        headers = self.get_auth_headers(operator_user)
        
        # interval_hours範囲外
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 0,  # 無効値
                "max_backups": 10
            }
        )
        assert response.status_code == 422

        # max_backups範囲外
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 50  # 無効値
            }
        )
        assert response.status_code == 422

    def test_create_schedule_duplicate_server(self, client: TestClient, db: Session, operator_user: User, owner_server: Server):
        """重複スケジュール作成エラーテスト"""
        # Clear any existing schedules for this server first
        db.query(BackupSchedule).filter(BackupSchedule.server_id == owner_server.id).delete()
        db.commit()
        
        # 既存スケジュール作成
        schedule = BackupSchedule(
            server_id=owner_server.id,
            interval_hours=12,
            max_backups=10
        )
        db.add(schedule)
        db.commit()

        headers = self.get_auth_headers(operator_user)
        
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{owner_server.id}/schedule",
            headers=headers,
            json={
                "interval_hours": 24,
                "max_backups": 5
            }
        )
        
        assert response.status_code == 409
        assert "already has" in response.json()["detail"].lower()

    def test_operations_on_nonexistent_server(self, client: TestClient, db: Session, operator_user: User):
        """存在しないサーバーでの操作テスト"""
        headers = self.get_auth_headers(operator_user)
        nonexistent_server_id = 99999
        
        # 作成
        response = client.post(
            f"/api/v1/backups/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers,
            json={
                "interval_hours": 12,
                "max_backups": 10
            }
        )
        assert response.status_code == 404

        # 取得
        response = client.get(
            f"/api/v1/backups/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers
        )
        assert response.status_code == 404

        # 更新
        response = client.put(
            f"/api/v1/backups/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers,
            json={
                "interval_hours": 24
            }
        )
        assert response.status_code == 404

        # 削除
        response = client.delete(
            f"/api/v1/backups/scheduler/servers/{nonexistent_server_id}/schedule",
            headers=headers
        )
        assert response.status_code == 404