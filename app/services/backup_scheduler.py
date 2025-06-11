"""
New BackupSchedulerService implementation
Database-based persistent backup scheduler
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction
from app.servers.models import Server, ServerStatus
from app.services.minecraft_server import minecraft_server_manager

logger = logging.getLogger(__name__)


class BackupSchedulerService:
    """
    Database persistence-compatible backup scheduler
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._schedule_cache: Dict[int, BackupSchedule] = {}  # Performance cache

    # ===================
    # Schedule management
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
        Create new backup schedule

        Args:
            db: Database session
            server_id: Server ID
            interval_hours: Backup interval (hours)
            max_backups: Number of backups to retain
            enabled: Schedule enabled/disabled
            only_when_running: Execute only when server is running
            executed_by_user_id: User ID of the executor (for logging)

        Returns:
            Created BackupSchedule

        Raises:
            ValueError: When a schedule already exists
        """
        # Check for existing schedule
        existing_schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        if existing_schedule:
            raise ValueError(f"Server {server_id} already has a backup schedule")

        # Check server existence
        server = (
            db.query(Server)
            .filter(Server.id == server_id, Server.is_deleted.is_(False))
            .first()
        )

        if not server:
            raise ValueError(f"Server {server_id} not found or deleted")

        # Calculate next backup time
        now = datetime.utcnow()
        next_backup_at = now + timedelta(hours=interval_hours)

        # Create schedule
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

        # Update cache
        self._schedule_cache[server_id] = schedule

        # Create log
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
        Update existing backup schedule

        Args:
            db: Database session
            server_id: Server ID
            interval_hours: Backup interval (hours)
            max_backups: Number of backups to retain
            enabled: Schedule enabled/disabled
            only_when_running: Execute only when server is running
            executed_by_user_id: User ID of the executor (for logging)

        Returns:
            Updated BackupSchedule

        Raises:
            ValueError: When schedule does not exist
        """
        # Get existing schedule
        schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        if not schedule:
            raise ValueError(f"No backup schedule found for server {server_id}")

        # Save previous configuration (for logging)
        old_config = {
            "interval_hours": schedule.interval_hours,
            "max_backups": schedule.max_backups,
            "enabled": schedule.enabled,
            "only_when_running": schedule.only_when_running,
        }

        # Execute update
        if interval_hours is not None:
            schedule.interval_hours = interval_hours
            # Recalculate next execution time when interval changes
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

        # Manually update updated_at
        schedule.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(schedule)

        # Update cache
        self._schedule_cache[server_id] = schedule

        # Configuration after changes
        new_config = {
            "interval_hours": schedule.interval_hours,
            "max_backups": schedule.max_backups,
            "enabled": schedule.enabled,
            "only_when_running": schedule.only_when_running,
        }

        # Create log
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
        Delete backup schedule

        Args:
            db: Database session
            server_id: Server ID
            executed_by_user_id: User ID of the executor (for logging)

        Returns:
            True if deletion successful, False if no schedule exists
        """
        # Get existing schedule
        schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        if not schedule:
            return False

        # Save configuration before deletion (for logging)
        old_config = {
            "interval_hours": schedule.interval_hours,
            "max_backups": schedule.max_backups,
            "enabled": schedule.enabled,
            "only_when_running": schedule.only_when_running,
        }

        # Execute deletion
        db.delete(schedule)
        db.commit()

        # Remove from cache
        if server_id in self._schedule_cache:
            del self._schedule_cache[server_id]

        # Create log
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
        Get backup schedule for specified server

        Args:
            db: Database session
            server_id: Server ID

        Returns:
            BackupSchedule or None
        """
        # Check cache
        if server_id in self._schedule_cache:
            return self._schedule_cache[server_id]

        # Get from database
        schedule = (
            db.query(BackupSchedule).filter(BackupSchedule.server_id == server_id).first()
        )

        # Add to cache
        if schedule:
            self._schedule_cache[server_id] = schedule

        return schedule

    async def list_schedules(
        self, db: Session, enabled_only: bool = False
    ) -> List[BackupSchedule]:
        """
        Get all backup schedules

        Args:
            db: Database session
            enabled_only: Whether to get only enabled schedules

        Returns:
            List of BackupSchedules
        """
        query = db.query(BackupSchedule)

        if enabled_only:
            query = query.filter(BackupSchedule.enabled)

        schedules = query.all()

        # Update cache
        for schedule in schedules:
            self._schedule_cache[schedule.server_id] = schedule

        return schedules

    # ===================
    # Execution decision
    # ===================

    async def _should_execute_backup(self, schedule: BackupSchedule) -> Tuple[bool, str]:
        """
        Determine whether backup should be executed

        Args:
            schedule: BackupSchedule

        Returns:
            (should_execute: bool, reason: str)
        """
        # 1. Schedule validity check
        if not schedule.enabled:
            return False, "Schedule is disabled"

        # 2. Execution time check
        now = datetime.utcnow()
        if schedule.next_backup_at and now < schedule.next_backup_at:
            return False, f"Not yet time (next: {schedule.next_backup_at})"

        # 3. Server existence check
        # Note: DB access is avoided here, expected to use schedule.server relation
        # If actual DB access is needed, pre-check should be done by caller

        # 4. Server status check (new feature)
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
        Get backup schedules due for execution

        Args:
            db: Database session

        Returns:
            List of BackupSchedules due for execution
        """
        now = datetime.utcnow()

        due_schedules = (
            db.query(BackupSchedule)
            .filter(BackupSchedule.enabled, BackupSchedule.next_backup_at <= now)
            .all()
        )

        return due_schedules

    # ===================
    # Database operations
    # ===================

    async def load_schedules_from_db(self, db: Session) -> None:
        """
        Load schedules from database into cache

        Args:
            db: Database session
        """
        schedules = await self.list_schedules(db=db)

        # Clear cache and rebuild
        self._schedule_cache.clear()
        for schedule in schedules:
            self._schedule_cache[schedule.server_id] = schedule

    # ===================
    # Logging functionality
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
        Create schedule operation log

        Args:
            db: Database session
            server_id: Server ID
            action: Action that was executed
            reason: Reason/details
            old_config: Configuration before changes
            new_config: Configuration after changes
            executed_by_user_id: User ID of the executor
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
    # Scheduler control
    # ===================

    async def start_scheduler(self) -> None:
        """Start scheduler"""
        if self._running:
            return

        self._running = True
        # Load schedules from database using proper session management
        from app.core.database import SessionLocal

        db_session = SessionLocal()
        try:
            await self.load_schedules_from_db(db_session)
            logger.info("Successfully loaded schedules from database")
        except Exception as e:
            logger.error(f"Failed to load schedules from database during startup: {e}")
            # Continue startup even if schedule loading fails - scheduler can still accept new schedules
        finally:
            try:
                db_session.close()
            except Exception as e:
                logger.warning(
                    f"Error closing database session during scheduler startup: {e}"
                )

        # Start scheduler task
        self._task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        """Stop scheduler"""
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
        Scheduler main loop
        Check for due backups every 10 minutes
        """
        while self._running:
            try:
                # TODO: Implement actual backup execution logic
                # When implementing, use proper session management:
                # from app.core.database import SessionLocal
                # db_session = SessionLocal()
                # try:
                #     # Execute scheduled backups
                #     pass
                # except Exception as e:
                #     logger.error(f"Error executing scheduled backups: {e}")
                # finally:
                #     db_session.close()

                await asyncio.sleep(600)  # Wait 10 minutes
            except asyncio.CancelledError:
                logger.info("Backup scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in backup scheduler loop: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    # ===================
    # Properties
    # ===================

    @property
    def is_running(self) -> bool:
        """Whether the scheduler is running"""
        return self._running

    @property
    def cache_size(self) -> int:
        """Number of cached schedules"""
        return len(self._schedule_cache)

    def clear_cache(self) -> None:
        """Clear cache (for testing)"""
        self._schedule_cache.clear()


# Singleton instance
backup_scheduler = BackupSchedulerService()
