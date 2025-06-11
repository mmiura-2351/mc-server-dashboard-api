"""
新しいBackupSchedulerService実装
データベースベースの永続化対応バックアップスケジューラー
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction
from app.servers.models import Server, ServerStatus
from app.services.minecraft_server import minecraft_server_manager


class BackupSchedulerService:
    """
    データベース永続化対応のバックアップスケジューラー
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._schedule_cache: Dict[int, BackupSchedule] = {}  # パフォーマンス用キャッシュ

    # ===================
    # スケジュール管理
    # ===================

    async def create_schedule(
        self,
        db: Session,
        server_id: int,
        interval_hours: int,
        max_backups: int,
        enabled: bool = True,
        only_when_running: bool = True,
        executed_by_user_id: Optional[int] = None,
    ) -> BackupSchedule:
        """
        新しいバックアップスケジュールを作成

        Args:
            db: データベースセッション
            server_id: サーバーID
            interval_hours: バックアップ間隔（時間）
            max_backups: 保持するバックアップ数
            enabled: スケジュールの有効/無効
            only_when_running: サーバー稼働中のみ実行するか
            executed_by_user_id: 実行者のユーザーID（ログ用）

        Returns:
            作成されたBackupSchedule

        Raises:
            ValueError: 既にスケジュールが存在する場合
        """
        # 既存スケジュールの確認
        existing_schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        if existing_schedule:
            raise ValueError(f"Server {server_id} already has a backup schedule")

        # サーバーの存在確認
        server = (
            db.query(Server)
            .filter(Server.id == server_id, Server.is_deleted.is_(False))
            .first()
        )

        if not server:
            raise ValueError(f"Server {server_id} not found or deleted")

        # 次回バックアップ時刻を計算
        now = datetime.utcnow()
        next_backup_at = now + timedelta(hours=interval_hours)

        # スケジュール作成
        schedule = BackupSchedule(
            server_id=server_id,
            interval_hours=interval_hours,
            max_backups=max_backups,
            enabled=enabled,
            only_when_running=only_when_running,
            next_backup_at=next_backup_at,
        )

        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        # キャッシュ更新
        self._schedule_cache[server_id] = schedule

        # ログ作成
        await self._log_schedule_action(
            db=db,
            server_id=server_id,
            action=ScheduleAction.created,
            reason="Schedule created",
            new_config={
                "interval_hours": interval_hours,
                "max_backups": max_backups,
                "enabled": enabled,
                "only_when_running": only_when_running,
            },
            executed_by_user_id=executed_by_user_id,
        )

        return schedule

    async def update_schedule(
        self,
        db: Session,
        server_id: int,
        interval_hours: Optional[int] = None,
        max_backups: Optional[int] = None,
        enabled: Optional[bool] = None,
        only_when_running: Optional[bool] = None,
        executed_by_user_id: Optional[int] = None,
    ) -> BackupSchedule:
        """
        既存のバックアップスケジュールを更新

        Args:
            db: データベースセッション
            server_id: サーバーID
            interval_hours: バックアップ間隔（時間）
            max_backups: 保持するバックアップ数
            enabled: スケジュールの有効/無効
            only_when_running: サーバー稼働中のみ実行するか
            executed_by_user_id: 実行者のユーザーID（ログ用）

        Returns:
            更新されたBackupSchedule

        Raises:
            ValueError: スケジュールが存在しない場合
        """
        # 既存スケジュールの取得
        schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        if not schedule:
            raise ValueError(f"No backup schedule found for server {server_id}")

        # 変更前の設定を保存（ログ用）
        old_config = {
            "interval_hours": schedule.interval_hours,
            "max_backups": schedule.max_backups,
            "enabled": schedule.enabled,
            "only_when_running": schedule.only_when_running,
        }

        # 更新実行
        if interval_hours is not None:
            schedule.interval_hours = interval_hours
            # インターバル変更時は次回実行時刻も再計算
            if schedule.last_backup_at:
                schedule.next_backup_at = schedule.last_backup_at + timedelta(
                    hours=interval_hours
                )
            else:
                schedule.next_backup_at = datetime.utcnow() + timedelta(
                    hours=interval_hours
                )

        if max_backups is not None:
            schedule.max_backups = max_backups

        if enabled is not None:
            schedule.enabled = enabled

        if only_when_running is not None:
            schedule.only_when_running = only_when_running

        # updated_atを手動で更新
        schedule.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(schedule)

        # キャッシュ更新
        self._schedule_cache[server_id] = schedule

        # 変更後の設定
        new_config = {
            "interval_hours": schedule.interval_hours,
            "max_backups": schedule.max_backups,
            "enabled": schedule.enabled,
            "only_when_running": schedule.only_when_running,
        }

        # ログ作成
        await self._log_schedule_action(
            db=db,
            server_id=server_id,
            action=ScheduleAction.updated,
            reason="Schedule updated",
            old_config=old_config,
            new_config=new_config,
            executed_by_user_id=executed_by_user_id,
        )

        return schedule

    async def delete_schedule(
        self, db: Session, server_id: int, executed_by_user_id: Optional[int] = None
    ) -> bool:
        """
        バックアップスケジュールを削除

        Args:
            db: データベースセッション
            server_id: サーバーID
            executed_by_user_id: 実行者のユーザーID（ログ用）

        Returns:
            削除成功時True、スケジュールが存在しない場合False
        """
        # 既存スケジュールの取得
        schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        if not schedule:
            return False

        # 削除前の設定を保存（ログ用）
        old_config = {
            "interval_hours": schedule.interval_hours,
            "max_backups": schedule.max_backups,
            "enabled": schedule.enabled,
            "only_when_running": schedule.only_when_running,
        }

        # 削除実行
        db.delete(schedule)
        db.commit()

        # キャッシュから削除
        if server_id in self._schedule_cache:
            del self._schedule_cache[server_id]

        # ログ作成
        await self._log_schedule_action(
            db=db,
            server_id=server_id,
            action=ScheduleAction.deleted,
            reason="Schedule deleted",
            old_config=old_config,
            executed_by_user_id=executed_by_user_id,
        )

        return True

    async def get_schedule(self, db: Session, server_id: int) -> Optional[BackupSchedule]:
        """
        指定サーバーのバックアップスケジュールを取得

        Args:
            db: データベースセッション
            server_id: サーバーID

        Returns:
            BackupSchedule またはNone
        """
        # キャッシュから確認
        if server_id in self._schedule_cache:
            return self._schedule_cache[server_id]

        # データベースから取得
        schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        # キャッシュに追加
        if schedule:
            self._schedule_cache[server_id] = schedule

        return schedule

    async def list_schedules(
        self, db: Session, enabled_only: bool = False
    ) -> List[BackupSchedule]:
        """
        全バックアップスケジュールを取得

        Args:
            db: データベースセッション
            enabled_only: 有効なスケジュールのみ取得するか

        Returns:
            BackupScheduleのリスト
        """
        query = db.query(BackupSchedule)

        if enabled_only:
            query = query.filter(BackupSchedule.enabled)

        schedules = query.all()

        # キャッシュ更新
        for schedule in schedules:
            self._schedule_cache[schedule.server_id] = schedule

        return schedules

    # ===================
    # 実行判定
    # ===================

    async def _should_execute_backup(self, schedule: BackupSchedule) -> Tuple[bool, str]:
        """
        バックアップ実行可否を判定

        Args:
            schedule: BackupSchedule

        Returns:
            (should_execute: bool, reason: str)
        """
        # 1. スケジュール有効性チェック
        if not schedule.enabled:
            return False, "Schedule is disabled"

        # 2. 実行時刻チェック
        now = datetime.utcnow()
        if schedule.next_backup_at and now < schedule.next_backup_at:
            return False, f"Not yet time (next: {schedule.next_backup_at})"

        # 3. サーバー存在チェック
        # Note: ここではDBアクセスを避けてschedule.serverリレーションを使用想定
        # 実際のDBアクセスが必要な場合は呼び出し元で事前チェック

        # 4. サーバー状態チェック（新機能）
        if schedule.only_when_running:
            try:
                status = minecraft_server_manager.get_server_status(schedule.server_id)
                if status != ServerStatus.running:
                    return False, f"Server not running (status: {status.value})"
            except Exception as e:
                return False, f"Failed to get server status: {str(e)}"

        return True, "Ready for backup"

    async def get_due_schedules(self, db: Session) -> List[BackupSchedule]:
        """
        実行予定のバックアップスケジュールを取得

        Args:
            db: データベースセッション

        Returns:
            実行予定のBackupScheduleリスト
        """
        now = datetime.utcnow()

        due_schedules = (
            db.query(BackupSchedule)
            .filter(BackupSchedule.enabled, BackupSchedule.next_backup_at <= now)
            .all()
        )

        return due_schedules

    # ===================
    # データベース操作
    # ===================

    async def load_schedules_from_db(self, db: Session) -> None:
        """
        データベースからスケジュールをキャッシュに読み込み

        Args:
            db: データベースセッション
        """
        schedules = await self.list_schedules(db=db)

        # キャッシュクリアして再構築
        self._schedule_cache.clear()
        for schedule in schedules:
            self._schedule_cache[schedule.server_id] = schedule

    # ===================
    # ログ機能
    # ===================

    async def _log_schedule_action(
        self,
        db: Session,
        server_id: int,
        action: ScheduleAction,
        reason: Optional[str] = None,
        old_config: Optional[Dict] = None,
        new_config: Optional[Dict] = None,
        executed_by_user_id: Optional[int] = None,
    ) -> None:
        """
        スケジュール操作ログを作成

        Args:
            db: データベースセッション
            server_id: サーバーID
            action: 実行されたアクション
            reason: 理由・詳細
            old_config: 変更前設定
            new_config: 変更後設定
            executed_by_user_id: 実行者のユーザーID
        """
        log = BackupScheduleLog(
            server_id=server_id,
            action=action,
            reason=reason,
            old_config=old_config,
            new_config=new_config,
            executed_by_user_id=executed_by_user_id,
        )

        db.add(log)
        db.commit()

    # ===================
    # スケジューラー制御
    # ===================

    async def start_scheduler(self) -> None:
        """スケジューラー開始"""
        if self._running:
            return

        self._running = True
        # データベースからスケジュールを読み込み
        from app.core.database import get_db
        db = next(get_db())
        try:
            await self.load_schedules_from_db(db)
        finally:
            db.close()
        
        # スケジューラータスクを開始
        self._task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        """スケジューラー停止"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._schedule_cache.clear()

    async def _scheduler_loop(self) -> None:
        """
        スケジューラーメインループ
        10分間隔で実行予定のバックアップをチェック
        """
        while self._running:
            try:
                # データベースアクセスは実際の実装時に注入される想定
                # ここではスケルトン実装
                await asyncio.sleep(600)  # 10分待機
            except asyncio.CancelledError:
                break
            except Exception:
                # ログ出力は実際の実装時に追加
                await asyncio.sleep(60)  # エラー時は1分後にリトライ

    # ===================
    # プロパティ
    # ===================

    @property
    def is_running(self) -> bool:
        """スケジューラーが稼働中かどうか"""
        return self._running

    @property
    def cache_size(self) -> int:
        """キャッシュされているスケジュール数"""
        return len(self._schedule_cache)
    
    def clear_cache(self) -> None:
        """キャッシュをクリア（テスト用）"""
        self._schedule_cache.clear()


# シングルトンインスタンス
backup_scheduler = BackupSchedulerService()
