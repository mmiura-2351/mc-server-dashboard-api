import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy.orm import Session

from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction
from app.servers.models import Server, ServerStatus
from app.users.models import User, Role


class TestNewBackupSchedulerService:
    """新しいBackupSchedulerServiceのテスト"""

    @pytest.fixture
    def mock_db_session(self):
        """モックDBセッション"""
        mock_session = Mock()
        mock_session.query.return_value = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.rollback = Mock()
        return mock_session

    @pytest.fixture
    def test_user(self, db: Session):
        """テスト用ユーザー"""
        user = User(
            username="scheduleruser",
            email="scheduler@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.flush()
        return user

    @pytest.fixture
    def test_server(self, db: Session, test_user: User):
        """テスト用サーバー"""
        server = Server(
            name="scheduler-test-server",
            description="Scheduler test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25620,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id,
            directory_path="/servers/scheduler-test-server"
        )
        db.add(server)
        db.flush()
        return server

    @pytest.mark.asyncio
    async def test_create_schedule_success(self, db: Session, test_server: Server, test_user: User):
        """スケジュール作成の成功テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # スケジュール作成
        schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=12,
            max_backups=10,
            enabled=True,
            only_when_running=True,
            executed_by_user_id=test_user.id
        )
        
        # 検証
        assert schedule is not None
        assert schedule.server_id == test_server.id
        assert schedule.interval_hours == 12
        assert schedule.max_backups == 10
        assert schedule.enabled is True
        assert schedule.only_when_running is True
        
        # データベースに保存されているか確認
        saved_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == test_server.id
        ).first()
        assert saved_schedule is not None
        
        # ログが作成されているか確認
        log = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id,
            BackupScheduleLog.action == ScheduleAction.created
        ).first()
        assert log is not None
        assert log.executed_by_user_id == test_user.id

    @pytest.mark.asyncio
    async def test_create_schedule_duplicate_server(self, db: Session, test_server: Server, test_user: User):
        """同じサーバーに重複スケジュール作成エラーテスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 最初のスケジュール作成
        await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=12,
            max_backups=10,
            executed_by_user_id=test_user.id
        )
        
        # 重複作成を試行（例外が発生するはず）
        with pytest.raises(ValueError, match="already has a backup schedule"):
            await scheduler.create_schedule(
                db=db,
                server_id=test_server.id,
                interval_hours=6,
                max_backups=5,
                executed_by_user_id=test_user.id
            )

    @pytest.mark.asyncio
    async def test_update_schedule_success(self, db: Session, test_server: Server, test_user: User):
        """スケジュール更新の成功テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # スケジュール作成
        original_schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=12,
            max_backups=10,
            executed_by_user_id=test_user.id
        )
        
        # 少し時間を置く
        import time
        time.sleep(0.01)
        
        # スケジュール更新
        updated_schedule = await scheduler.update_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=6,
            max_backups=15,
            enabled=False,
            only_when_running=False,
            executed_by_user_id=test_user.id
        )
        
        # 検証
        assert updated_schedule.interval_hours == 6
        assert updated_schedule.max_backups == 15
        assert updated_schedule.enabled is False
        assert updated_schedule.only_when_running is False
        
        # データベースから再取得して検証
        db_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == test_server.id
        ).first()
        assert db_schedule.interval_hours == 6
        assert db_schedule.max_backups == 15
        assert db_schedule.enabled is False
        assert db_schedule.only_when_running is False
        
        # ログが作成されているか確認
        update_log = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id,
            BackupScheduleLog.action == ScheduleAction.updated
        ).first()
        assert update_log is not None
        assert update_log.old_config["interval_hours"] == 12
        assert update_log.new_config["interval_hours"] == 6

    @pytest.mark.asyncio
    async def test_delete_schedule_success(self, db: Session, test_server: Server, test_user: User):
        """スケジュール削除の成功テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # スケジュール作成
        await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=12,
            max_backups=10,
            executed_by_user_id=test_user.id
        )
        
        # スケジュール削除
        result = await scheduler.delete_schedule(
            db=db,
            server_id=test_server.id,
            executed_by_user_id=test_user.id
        )
        
        # 検証
        assert result is True
        
        # データベースから削除されているか確認
        deleted_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == test_server.id
        ).first()
        assert deleted_schedule is None
        
        # 削除ログが作成されているか確認
        delete_log = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id,
            BackupScheduleLog.action == ScheduleAction.deleted
        ).first()
        assert delete_log is not None

    @pytest.mark.asyncio
    async def test_get_schedule_success(self, db: Session, test_server: Server, test_user: User):
        """スケジュール取得の成功テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # スケジュール作成
        created_schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=8,
            max_backups=12,
            executed_by_user_id=test_user.id
        )
        
        # スケジュール取得
        retrieved_schedule = await scheduler.get_schedule(
            db=db,
            server_id=test_server.id
        )
        
        # 検証
        assert retrieved_schedule is not None
        assert retrieved_schedule.id == created_schedule.id
        assert retrieved_schedule.interval_hours == 8
        assert retrieved_schedule.max_backups == 12

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, db: Session, test_server: Server):
        """存在しないスケジュール取得テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 存在しないスケジュール取得
        schedule = await scheduler.get_schedule(
            db=db,
            server_id=test_server.id
        )
        
        # 検証
        assert schedule is None

    @pytest.mark.asyncio
    async def test_list_schedules_all(self, db: Session, test_user: User):
        """全スケジュール一覧取得テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 複数のサーバーとスケジュールを作成
        servers = []
        for i in range(3):
            server = Server(
                name=f"list-test-server-{i}",
                description=f"List test server {i}",
                minecraft_version="1.20.1",
                server_type="vanilla",
                port=25630 + i,
                max_memory=1024,
                max_players=20,
                owner_id=test_user.id,
                directory_path=f"/servers/list-test-server-{i}"
            )
            servers.append(server)
            db.add(server)
        
        db.flush()
        
        # スケジュール作成（1つは無効化）
        for i, server in enumerate(servers):
            await scheduler.create_schedule(
                db=db,
                server_id=server.id,
                interval_hours=6 * (i + 1),
                max_backups=10 + i,
                enabled=i != 1,  # 2番目のスケジュールは無効
                executed_by_user_id=test_user.id
            )
        
        # 全スケジュール取得
        all_schedules = await scheduler.list_schedules(db=db)
        assert len(all_schedules) == 3
        
        # 有効なスケジュールのみ取得
        enabled_schedules = await scheduler.list_schedules(db=db, enabled_only=True)
        assert len(enabled_schedules) == 2

    @pytest.mark.asyncio
    async def test_should_execute_backup_enabled_and_running(self, db: Session, test_server: Server, test_user: User):
        """バックアップ実行判定：有効かつサーバー稼働中"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 実行時刻が過ぎたスケジュール作成
        now = datetime.utcnow()
        schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=6,
            max_backups=10,
            enabled=True,
            only_when_running=True,
            executed_by_user_id=test_user.id
        )
        
        # 実行時刻を過去に設定
        schedule.next_backup_at = now - timedelta(minutes=30)
        db.commit()
        
        # サーバー状態をrunningにモック
        with patch('app.services.new_backup_scheduler.minecraft_server_manager.get_server_status') as mock_status:
            mock_status.return_value = ServerStatus.running
            
            should_execute, reason = await scheduler._should_execute_backup(schedule)
            
            assert should_execute is True
            assert "Ready for backup" in reason

    @pytest.mark.asyncio
    async def test_should_execute_backup_disabled(self, db: Session, test_server: Server, test_user: User):
        """バックアップ実行判定：無効スケジュール"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 無効なスケジュール作成
        schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=6,
            max_backups=10,
            enabled=False,  # 無効
            executed_by_user_id=test_user.id
        )
        
        should_execute, reason = await scheduler._should_execute_backup(schedule)
        
        assert should_execute is False
        assert "disabled" in reason.lower()

    @pytest.mark.asyncio
    async def test_should_execute_backup_not_time_yet(self, db: Session, test_server: Server, test_user: User):
        """バックアップ実行判定：まだ実行時刻でない"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 未来の実行時刻のスケジュール作成
        now = datetime.utcnow()
        schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=6,
            max_backups=10,
            executed_by_user_id=test_user.id
        )
        
        # 実行時刻を未来に設定
        schedule.next_backup_at = now + timedelta(hours=2)
        db.commit()
        
        should_execute, reason = await scheduler._should_execute_backup(schedule)
        
        assert should_execute is False
        assert "Not yet time" in reason

    @pytest.mark.asyncio
    async def test_should_execute_backup_server_not_running(self, db: Session, test_server: Server, test_user: User):
        """バックアップ実行判定：サーバー停止中（only_when_running=True）"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # only_when_running=Trueのスケジュール作成
        now = datetime.utcnow()
        schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=6,
            max_backups=10,
            enabled=True,
            only_when_running=True,
            executed_by_user_id=test_user.id
        )
        
        # 実行時刻を過去に設定
        schedule.next_backup_at = now - timedelta(minutes=30)
        db.commit()
        
        # サーバー状態をstoppedにモック
        with patch('app.services.new_backup_scheduler.minecraft_server_manager.get_server_status') as mock_status:
            mock_status.return_value = ServerStatus.stopped
            
            should_execute, reason = await scheduler._should_execute_backup(schedule)
            
            assert should_execute is False
            assert "not running" in reason.lower()

    @pytest.mark.asyncio
    async def test_should_execute_backup_server_stopped_but_allowed(self, db: Session, test_server: Server, test_user: User):
        """バックアップ実行判定：サーバー停止中でも実行許可（only_when_running=False）"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # only_when_running=Falseのスケジュール作成
        now = datetime.utcnow()
        schedule = await scheduler.create_schedule(
            db=db,
            server_id=test_server.id,
            interval_hours=6,
            max_backups=10,
            enabled=True,
            only_when_running=False,  # 停止中でも実行
            executed_by_user_id=test_user.id
        )
        
        # 実行時刻を過去に設定
        schedule.next_backup_at = now - timedelta(minutes=30)
        db.commit()
        
        # サーバー状態をstoppedにモック
        with patch('app.services.new_backup_scheduler.minecraft_server_manager.get_server_status') as mock_status:
            mock_status.return_value = ServerStatus.stopped
            
            should_execute, reason = await scheduler._should_execute_backup(schedule)
            
            assert should_execute is True
            assert "Ready for backup" in reason

    @pytest.mark.asyncio
    async def test_load_schedules_from_db(self, db: Session, test_user: User):
        """データベースからスケジュール読み込みテスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        # 複数のスケジュールを作成
        for i in range(2):
            server = Server(
                name=f"load-test-server-{i}",
                description=f"Load test server {i}",
                minecraft_version="1.20.1",
                server_type="vanilla",
                port=25640 + i,
                max_memory=1024,
                max_players=20,
                owner_id=test_user.id,
                directory_path=f"/servers/load-test-server-{i}"
            )
            db.add(server)
            db.flush()
            
            await scheduler.create_schedule(
                db=db,
                server_id=server.id,
                interval_hours=12,
                max_backups=10,
                executed_by_user_id=test_user.id
            )
        
        # スケジュール読み込み
        await scheduler.load_schedules_from_db(db=db)
        
        # キャッシュに読み込まれているか確認
        assert len(scheduler._schedule_cache) == 2
        
        # キャッシュの内容確認
        cached_schedules = list(scheduler._schedule_cache.values())
        assert all(schedule.interval_hours == 12 for schedule in cached_schedules)
        assert all(schedule.max_backups == 10 for schedule in cached_schedules)

    @pytest.mark.asyncio 
    async def test_get_due_schedules(self, db: Session, test_user: User):
        """実行予定スケジュール取得テスト"""
        from app.services.new_backup_scheduler import NewBackupSchedulerService
        
        scheduler = NewBackupSchedulerService()
        
        now = datetime.utcnow()
        
        # 3つのスケジュールを作成（実行予定あり、なし、無効）
        servers_data = [
            {"name": "due-server", "due": True, "enabled": True},
            {"name": "future-server", "due": False, "enabled": True},
            {"name": "disabled-server", "due": True, "enabled": False}
        ]
        
        for i, data in enumerate(servers_data):
            server = Server(
                name=data["name"],
                description=f"Due test server {i}",
                minecraft_version="1.20.1",
                server_type="vanilla",
                port=25650 + i,
                max_memory=1024,
                max_players=20,
                owner_id=test_user.id,
                directory_path=f"/servers/{data['name']}"
            )
            db.add(server)
            db.flush()
            
            schedule = await scheduler.create_schedule(
                db=db,
                server_id=server.id,
                interval_hours=6,
                max_backups=10,
                enabled=data["enabled"],
                executed_by_user_id=test_user.id
            )
            
            # 実行時刻設定
            if data["due"]:
                schedule.next_backup_at = now - timedelta(minutes=30)  # 実行予定過ぎ
            else:
                schedule.next_backup_at = now + timedelta(hours=1)     # まだ実行予定じゃない
            
            db.commit()
        
        # 実行予定スケジュール取得
        due_schedules = await scheduler.get_due_schedules(db=db)
        
        # 有効で実行時刻が過ぎたもののみ取得されているか確認
        assert len(due_schedules) == 1
        assert due_schedules[0].server.name == "due-server"