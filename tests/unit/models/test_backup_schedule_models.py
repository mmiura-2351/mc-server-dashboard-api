import pytest
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.servers.models import Server
from app.users.models import User, Role
from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction


class TestBackupScheduleModel:
    """BackupSchedule モデルのテスト"""

    def test_create_backup_schedule_success(self, db: Session):
        """正常なBackupSchedule作成テスト"""
        # テスト用ユーザーとサーバーを作成
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="test-server",
            description="Test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/test-server",
        )
        db.add(server)
        db.flush()

        # BackupSchedule作成
        schedule = BackupSchedule(
            server_id=server.id,
            interval_hours=12,
            max_backups=10,
            enabled=True,
            only_when_running=True,
        )
        db.add(schedule)
        db.commit()

        # 検証
        assert schedule.id is not None
        assert schedule.server_id == server.id
        assert schedule.interval_hours == 12
        assert schedule.max_backups == 10
        assert schedule.enabled is True
        assert schedule.only_when_running is True
        assert schedule.last_backup_at is None
        assert schedule.next_backup_at is None
        assert schedule.created_at is not None
        assert schedule.updated_at is not None

    def test_backup_schedule_validation_constraints(self, db: Session):
        """BackupScheduleのバリデーション制約テスト"""
        user = User(
            username="testuser2",
            email="test2@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="test-server2",
            description="Test server 2",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25566,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/test-server2",
        )
        db.add(server)
        db.flush()

        # interval_hours の範囲外テスト（0時間）
        with pytest.raises(Exception):  # CHECK制約エラー
            schedule = BackupSchedule(
                server_id=server.id,
                interval_hours=0,  # 無効値
                max_backups=10,
            )
            db.add(schedule)
            db.commit()

        db.rollback()

        # interval_hours の範囲外テスト（169時間）
        with pytest.raises(Exception):  # CHECK制約エラー
            schedule = BackupSchedule(
                server_id=server.id,
                interval_hours=169,  # 無効値
                max_backups=10,
            )
            db.add(schedule)
            db.commit()

        db.rollback()

        # max_backups の範囲外テスト（0個）
        with pytest.raises(Exception):  # CHECK制約エラー
            schedule = BackupSchedule(
                server_id=server.id,
                interval_hours=12,
                max_backups=0,  # 無効値
            )
            db.add(schedule)
            db.commit()

        db.rollback()

        # max_backups の範囲外テスト（31個）
        with pytest.raises(Exception):  # CHECK制約エラー
            schedule = BackupSchedule(
                server_id=server.id,
                interval_hours=12,
                max_backups=31,  # 無効値
            )
            db.add(schedule)
            db.commit()

    def test_backup_schedule_unique_server_constraint(self, db: Session):
        """1サーバー1スケジュールの制約テスト"""
        user = User(
            username="testuser3",
            email="test3@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="test-server3",
            description="Test server 3",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25567,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/test-server3",
        )
        db.add(server)
        db.flush()

        # 最初のスケジュール作成
        schedule1 = BackupSchedule(server_id=server.id, interval_hours=12, max_backups=10)
        db.add(schedule1)
        db.commit()

        # 同じサーバーに2つ目のスケジュール作成（失敗するはず）
        with pytest.raises(IntegrityError):  # UNIQUE制約エラー
            schedule2 = BackupSchedule(
                server_id=server.id, interval_hours=24, max_backups=5
            )
            db.add(schedule2)
            db.commit()

    def test_backup_schedule_server_relationship(self, db: Session):
        """サーバーとの関係性テスト"""
        user = User(
            username="testuser4",
            email="test4@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="test-server4",
            description="Test server 4",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25568,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/test-server4",
        )
        db.add(server)
        db.flush()

        schedule = BackupSchedule(server_id=server.id, interval_hours=6, max_backups=15)
        db.add(schedule)
        db.commit()

        # リレーションシップの確認
        assert schedule.server == server
        assert server.backup_schedule == schedule

    def test_backup_schedule_cascade_delete(self, db: Session):
        """サーバー削除時のカスケード削除テスト"""
        user = User(
            username="testuser5",
            email="test5@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="test-server5",
            description="Test server 5",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25569,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/test-server5",
        )
        db.add(server)
        db.flush()

        schedule = BackupSchedule(server_id=server.id, interval_hours=8, max_backups=12)
        db.add(schedule)
        db.commit()

        schedule_id = schedule.id

        # サーバー削除
        db.delete(server)
        db.commit()

        # スケジュールも削除されているか確認
        deleted_schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.id == schedule_id).first()
        )
        assert deleted_schedule is None

    def test_backup_schedule_default_values(self, db: Session):
        """デフォルト値のテスト"""
        user = User(
            username="testuser6",
            email="test6@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="test-server6",
            description="Test server 6",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25570,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/test-server6",
        )
        db.add(server)
        db.flush()

        # 最小限のフィールドでスケジュール作成
        schedule = BackupSchedule(server_id=server.id, interval_hours=12, max_backups=10)
        db.add(schedule)
        db.commit()

        # デフォルト値の確認
        assert schedule.enabled is True
        assert schedule.only_when_running is True
        assert schedule.last_backup_at is None
        assert schedule.next_backup_at is None


class TestBackupScheduleLogModel:
    """BackupScheduleLog モデルのテスト"""

    def test_create_backup_schedule_log_success(self, db: Session):
        """正常なBackupScheduleLog作成テスト"""
        user = User(
            username="loguser1",
            email="loguser1@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="log-server1",
            description="Log test server 1",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25571,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/log-server1",
        )
        db.add(server)
        db.flush()

        # BackupScheduleLog作成
        log = BackupScheduleLog(
            server_id=server.id,
            action=ScheduleAction.created,
            reason="Schedule created by admin",
            new_config={"interval_hours": 12, "max_backups": 10},
            executed_by_user_id=user.id,
        )
        db.add(log)
        db.commit()

        # 検証
        assert log.id is not None
        assert log.server_id == server.id
        assert log.action == ScheduleAction.created
        assert log.reason == "Schedule created by admin"
        assert log.old_config is None
        assert log.new_config == {"interval_hours": 12, "max_backups": 10}
        assert log.executed_by_user_id == user.id
        assert log.created_at is not None

    def test_backup_schedule_log_relationships(self, db: Session):
        """BackupScheduleLogのリレーションシップテスト"""
        user = User(
            username="loguser2",
            email="loguser2@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="log-server2",
            description="Log test server 2",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25572,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/log-server2",
        )
        db.add(server)
        db.flush()

        log = BackupScheduleLog(
            server_id=server.id,
            action=ScheduleAction.updated,
            executed_by_user_id=user.id,
        )
        db.add(log)
        db.commit()

        # リレーションシップの確認
        assert log.server == server
        assert log.executed_by == user

    def test_backup_schedule_log_all_actions(self, db: Session):
        """全てのScheduleActionのテスト"""
        user = User(
            username="loguser3",
            email="loguser3@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="log-server3",
            description="Log test server 3",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25573,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/log-server3",
        )
        db.add(server)
        db.flush()

        # 全てのアクションタイプをテスト
        actions = [
            ScheduleAction.created,
            ScheduleAction.updated,
            ScheduleAction.deleted,
            ScheduleAction.executed,
            ScheduleAction.skipped,
        ]

        for action in actions:
            log = BackupScheduleLog(
                server_id=server.id,
                action=action,
                reason=f"Test {action.value}",
                executed_by_user_id=user.id,
            )
            db.add(log)

        db.commit()

        # 作成されたログの確認
        logs = (
            db.query(BackupScheduleLog)
            .filter(BackupScheduleLog.server_id == server.id)
            .all()
        )
        assert len(logs) == 5

        log_actions = [log.action for log in logs]
        for action in actions:
            assert action in log_actions

    def test_backup_schedule_log_optional_fields(self, db: Session):
        """BackupScheduleLogのオプションフィールドテスト"""
        user = User(
            username="loguser4",
            email="loguser4@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True,
        )
        db.add(user)
        db.flush()

        server = Server(
            name="log-server4",
            description="Log test server 4",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25574,
            max_memory=1024,
            max_players=20,
            owner_id=user.id,
            directory_path="/servers/log-server4",
        )
        db.add(server)
        db.flush()

        # executed_by_user_id なしのログ（システム実行）
        log = BackupScheduleLog(
            server_id=server.id,
            action=ScheduleAction.executed,
            reason="Automated execution",
        )
        db.add(log)
        db.commit()

        assert log.executed_by_user_id is None
        assert log.executed_by is None
        assert log.reason == "Automated execution"
