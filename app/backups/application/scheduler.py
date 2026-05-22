"""Backup scheduler service (application layer).

Maintains the persistent backup-schedule rows and surfaces them to the
router. The actual scheduler tick is a no-op stub today (`TODO: Implement
actual backup execution logic` in the legacy code); the tick loop and
backup-execution wiring will be added in a follow-up.

Cache invalidation (D-8): the per-server schedule cache is invalidated
after every successful UoW commit that touches the corresponding
server's row, so subsequent reads see fresh state without an extra
SELECT.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from app.backups.domain.entities import (
    AppendScheduleLogCommand,
    BackupScheduleEntity,
    BackupScheduleLogEntity,
    CreateBackupScheduleCommand,
    UpdateBackupScheduleCommand,
)
from app.backups.domain.exceptions import (
    BackupScheduleAlreadyExistsError,
    BackupScheduleNotFoundError,
)
from app.backups.domain.ports import BackupsUnitOfWork
from app.backups.models import ScheduleAction
from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.domain.ports import ServerReadPort
from app.servers.models import ServerStatus

ServerReadPortFactory = Callable[[], ServerReadPort]

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackupSchedulerService:
    """Schedule CRUD + scheduler loop control.

    Constructed with a `uow_factory` callable (because each tick needs
    its own UoW bound to its own session) and a `clock` callable
    (D-12: deterministic time injection for tests). `server_read` is
    used for owner-validation prior to creating a schedule.
    """

    def __init__(
        self,
        uow_factory: Callable[[], BackupsUnitOfWork],
        server_read_factory: ServerReadPortFactory,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._uow_factory = uow_factory
        self._server_read_factory = server_read_factory
        self._clock = clock
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._schedule_cache: Dict[int, BackupScheduleEntity] = {}

    # ===================
    # Schedule CRUD
    # ===================

    async def create_schedule(
        self,
        server_id: int,
        interval_hours: int,
        max_backups: int,
        enabled: bool = True,
        only_when_running: bool = True,
        executed_by_user_id: Optional[int] = None,
    ) -> BackupScheduleEntity:
        """Create a schedule + log row atomically in one UoW commit.

        Behaviour change (disclosed in PR): legacy code committed the
        schedule and the log row in two separate transactions. If the
        log insert failed, the schedule was already persisted. New
        code commits both in one transaction; a log-insert failure
        rolls back the schedule.
        """
        uow = self._uow_factory()
        async with uow:
            existing = await uow.schedules.find_by_server(server_id)
            if existing is not None:
                raise BackupScheduleAlreadyExistsError(
                    f"Server {server_id} already has a backup schedule"
                )

            server = await self._server_read_factory().get(server_id)
            if server is None:
                raise BackupScheduleNotFoundError(
                    f"Server {server_id} not found or deleted"
                )

            now = self._clock()
            next_backup_at = now + timedelta(hours=interval_hours)
            entity = await uow.schedules.add(
                CreateBackupScheduleCommand(
                    server_id=server_id,
                    interval_hours=interval_hours,
                    max_backups=max_backups,
                    enabled=enabled,
                    only_when_running=only_when_running,
                    next_backup_at=next_backup_at,
                )
            )

            await uow.schedules.append_log(
                AppendScheduleLogCommand(
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
            )
            await uow.commit()

        self._schedule_cache[server_id] = entity
        return entity

    async def update_schedule(
        self,
        server_id: int,
        interval_hours: Optional[int] = None,
        max_backups: Optional[int] = None,
        enabled: Optional[bool] = None,
        only_when_running: Optional[bool] = None,
        executed_by_user_id: Optional[int] = None,
    ) -> BackupScheduleEntity:
        uow = self._uow_factory()
        async with uow:
            existing = await uow.schedules.find_by_server(server_id)
            if existing is None:
                raise BackupScheduleNotFoundError(
                    f"No backup schedule found for server {server_id}"
                )

            old_config = {
                "interval_hours": existing.interval_hours,
                "max_backups": existing.max_backups,
                "enabled": existing.enabled,
                "only_when_running": existing.only_when_running,
            }

            command_kwargs = {
                "interval_hours": interval_hours,
                "max_backups": max_backups,
                "enabled": enabled,
                "only_when_running": only_when_running,
            }

            # Recompute `next_backup_at` when interval changes
            if interval_hours is not None:
                base = existing.last_backup_at or self._clock()
                command_kwargs["next_backup_at"] = base + timedelta(hours=interval_hours)

            updated = await uow.schedules.update(
                server_id,
                UpdateBackupScheduleCommand(**command_kwargs),
            )
            assert updated is not None  # find_by_server succeeded just above

            new_config = {
                "interval_hours": updated.interval_hours,
                "max_backups": updated.max_backups,
                "enabled": updated.enabled,
                "only_when_running": updated.only_when_running,
            }

            await uow.schedules.append_log(
                AppendScheduleLogCommand(
                    server_id=server_id,
                    action=ScheduleAction.updated,
                    reason="Schedule updated",
                    old_config=old_config,
                    new_config=new_config,
                    executed_by_user_id=executed_by_user_id,
                )
            )
            await uow.commit()

        self._schedule_cache[server_id] = updated
        return updated

    async def delete_schedule(
        self,
        server_id: int,
        executed_by_user_id: Optional[int] = None,
    ) -> bool:
        uow = self._uow_factory()
        async with uow:
            existing = await uow.schedules.find_by_server(server_id)
            if existing is None:
                return False

            old_config = {
                "interval_hours": existing.interval_hours,
                "max_backups": existing.max_backups,
                "enabled": existing.enabled,
                "only_when_running": existing.only_when_running,
            }

            await uow.schedules.delete_by_server(server_id)
            await uow.schedules.append_log(
                AppendScheduleLogCommand(
                    server_id=server_id,
                    action=ScheduleAction.deleted,
                    reason="Schedule deleted",
                    old_config=old_config,
                    executed_by_user_id=executed_by_user_id,
                )
            )
            await uow.commit()

        # Invalidate cache
        self._schedule_cache.pop(server_id, None)
        return True

    async def get_schedule(self, server_id: int) -> Optional[BackupScheduleEntity]:
        # Cache check
        if server_id in self._schedule_cache:
            return self._schedule_cache[server_id]
        uow = self._uow_factory()
        async with uow:
            entity = await uow.schedules.find_by_server(server_id)
        if entity is not None:
            self._schedule_cache[server_id] = entity
        return entity

    async def list_schedules(
        self, enabled_only: bool = False
    ) -> List[BackupScheduleEntity]:
        uow = self._uow_factory()
        async with uow:
            schedules = await uow.schedules.list(enabled_only=enabled_only)
        for s in schedules:
            self._schedule_cache[s.server_id] = s
        return schedules

    async def get_due_schedules(self) -> List[BackupScheduleEntity]:
        uow = self._uow_factory()
        async with uow:
            return await uow.schedules.list_due(self._clock())

    async def list_logs_for_server(
        self, server_id: int, page: int = 1, size: int = 50
    ) -> List[BackupScheduleLogEntity]:
        uow = self._uow_factory()
        async with uow:
            return await uow.schedules.list_logs_for_server(
                server_id, page=page, size=size
            )

    # ===================
    # Execution decision (kept for unit-test coverage)
    # ===================

    async def _should_execute_backup(
        self, schedule: BackupScheduleEntity
    ) -> tuple[bool, str]:
        if not schedule.enabled:
            return False, "Schedule is disabled"
        now = self._clock()
        if schedule.next_backup_at and now < schedule.next_backup_at:
            return False, f"Not yet time (next: {schedule.next_backup_at})"
        if schedule.only_when_running:
            try:
                status = minecraft_server_manager.get_server_status(schedule.server_id)
                if status != ServerStatus.running:
                    return False, f"Server not running (status: {status.value})"
            except Exception as e:
                return False, f"Failed to get server status: {str(e)}"
        return True, "Ready for backup"

    # ===================
    # Scheduler control
    # ===================

    async def load_schedules_from_db(self) -> None:
        self._schedule_cache.clear()
        schedules = await self.list_schedules()
        for s in schedules:
            self._schedule_cache[s.server_id] = s

    async def start_scheduler(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            await self.load_schedules_from_db()
            logger.info("Successfully loaded schedules from database")
        except Exception as e:
            logger.error(f"Failed to load schedules from database during startup: {e}")
        self._task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
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
        """No-op stub matching legacy behaviour.

        The legacy tick was a `pass`-with-sleep too; the actual
        execution loop is tracked separately and will be added when
        `BackupService.create_scheduled_backup` is plumbed through.
        """
        while self._running:
            try:
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                logger.info("Backup scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in backup scheduler loop: {e}")
                await asyncio.sleep(60)

    # ===================
    # Properties
    # ===================

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cache_size(self) -> int:
        return len(self._schedule_cache)

    def clear_cache(self) -> None:
        self._schedule_cache.clear()
