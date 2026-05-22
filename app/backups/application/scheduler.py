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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
        backups_directory: Path = Path("backups"),
        pending_retention_hours: Optional[int] = None,
        failed_retention_days: Optional[int] = None,
        cleanup_interval_seconds: Optional[int] = None,
    ):
        self._uow_factory = uow_factory
        self._server_read_factory = server_read_factory
        self._clock = clock
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._schedule_cache: Dict[int, BackupScheduleEntity] = {}

        # Sweep configuration for `.pending/` and `.failed/` (Issue #284).
        # Defaults come from `app.core.config.settings` but each value can
        # be overridden by the constructor for tests / wiring flexibility.
        from app.core.config import settings as _settings

        self._backups_directory: Path = Path(backups_directory)
        self._pending_retention_hours: int = (
            pending_retention_hours
            if pending_retention_hours is not None
            else _settings.BACKUPS_PENDING_RETENTION_HOURS
        )
        self._failed_retention_days: int = (
            failed_retention_days
            if failed_retention_days is not None
            else _settings.BACKUPS_FAILED_RETENTION_DAYS
        )
        self._cleanup_interval_seconds: int = (
            cleanup_interval_seconds
            if cleanup_interval_seconds is not None
            else _settings.BACKUPS_CLEANUP_INTERVAL_SECONDS
        )

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
        # One-shot sweep at startup picks up any artifacts left by a
        # previous crashed process before the periodic loop's first
        # tick (Issue #284). Failures here are non-fatal — they're
        # logged and the periodic loop will retry.
        try:
            self.sweep_stale_pending_and_failed()
        except Exception as e:
            logger.warning(f"Startup sweep of .pending/.failed failed: {e}")
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_scheduler(self) -> None:
        if not self._running:
            return
        self._running = False
        for task_attr in ("_task", "_cleanup_task"):
            task: Optional[asyncio.Task] = getattr(self, task_attr)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, task_attr, None)
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

    async def _cleanup_loop(self) -> None:
        """Periodic sweep of `.pending/` and `.failed/` artifacts (Issue #284).

        Runs `sweep_stale_pending_and_failed()` every
        `cleanup_interval_seconds` (default 1h). Each sweep is
        idempotent (mtime-based, query-then-skip), so a missed tick
        will catch up on the next run. Exceptions are logged and the
        loop continues — never block the scheduler on housekeeping.
        """
        while self._running:
            try:
                await asyncio.sleep(self._cleanup_interval_seconds)
            except asyncio.CancelledError:
                logger.info("Backup cleanup loop cancelled")
                break
            if not self._running:
                break
            try:
                self.sweep_stale_pending_and_failed()
            except Exception as e:
                logger.warning(f"Periodic sweep of .pending/.failed failed: {e}")

    # ===================
    # `.pending/` / `.failed/` housekeeping (Issue #284)
    # ===================

    def sweep_stale_pending_and_failed(self) -> Dict[str, int]:
        """Delete stale `*.tar.gz` files from `.pending/` and `.failed/`.

        Retention defaults (env-tunable via
        `BACKUPS_PENDING_RETENTION_HOURS` /
        `BACKUPS_FAILED_RETENTION_DAYS`):

        - `.pending/*.tar.gz`: 24h (atomic-rename interrupted between
          tar-write and `os.replace` — orphan temp file with no DB row).
        - `.failed/*.tar.gz`: 30d (post-commit `os.replace` failure
          recovery files; operator should review before auto-deletion,
          but the retention window is long enough to catch human
          attention via monitoring).

        Idempotent: only files whose `mtime` is older than the
        retention cutoff are unlinked. Per-file failures (permission
        denied, etc.) are logged at WARNING and the sweep continues.
        Returns `{"pending_deleted": int, "failed_deleted": int}` for
        callers (tests / metrics).
        """
        result = {"pending_deleted": 0, "failed_deleted": 0}
        result["pending_deleted"] = self._sweep_directory(
            self._backups_directory / ".pending",
            max_age_seconds=self._pending_retention_hours * 3600,
            kind="pending",
        )
        result["failed_deleted"] = self._sweep_directory(
            self._backups_directory / ".failed",
            max_age_seconds=self._failed_retention_days * 86400,
            kind="failed",
        )
        return result

    def _sweep_directory(
        self, directory: Path, *, max_age_seconds: int, kind: str
    ) -> int:
        """Unlink `*.tar.gz` files older than `max_age_seconds` in `directory`.

        Returns the number of files actually deleted. Missing
        directories are a no-op (the directory is lazily created by
        the atomic-rename failure path, so absence simply means no
        artifacts have accumulated yet).
        """
        if not directory.exists():
            return 0
        try:
            entries = list(directory.glob("*.tar.gz"))
        except OSError as e:
            logger.warning(f"Failed to enumerate {kind} sweep directory {directory}: {e}")
            return 0

        deleted = 0
        now = time.time()
        cutoff = now - max_age_seconds
        for path in entries:
            try:
                mtime = path.stat().st_mtime
            except OSError as e:
                logger.warning(f"Failed to stat {kind} artifact {path}: {e}")
                continue
            if mtime >= cutoff:
                # Within retention window — skip (query-then-skip
                # idempotency).
                continue
            try:
                path.unlink()
                deleted += 1
                age_hours = (now - mtime) / 3600
                logger.info(
                    "Swept stale %s backup artifact %s (age=%.1fh)",
                    kind,
                    path,
                    age_hours,
                )
            except OSError as e:
                # Per-file failure (permission, ENOENT race, …): warn
                # and continue — do not let one bad file block the
                # rest of the sweep.
                logger.warning(f"Failed to unlink stale {kind} artifact {path}: {e}")
        return deleted

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


# ---------------------------------------------------------------------------
# Legacy module-level proxy
# ---------------------------------------------------------------------------

from typing import Any  # noqa: E402

from app.backups import backup_scheduler_instance  # noqa: E402


class _SchedulerProxy:
    """Attribute-bearing proxy forwarding to the lifespan-scoped scheduler.

    Each method delegates to `backup_scheduler_instance.get()` at call
    time, raising `RuntimeError` if the instance has not yet been set
    (i.e. the lifespan callback has not run). The explicit method
    declarations (not `__getattr__`) keep `hasattr(...)` truthful for
    every public method on `BackupSchedulerService`.
    """

    # ---- Schedule CRUD ----

    async def create_schedule(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().create_schedule(*args, **kwargs)

    async def update_schedule(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().update_schedule(*args, **kwargs)

    async def delete_schedule(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().delete_schedule(*args, **kwargs)

    async def get_schedule(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().get_schedule(*args, **kwargs)

    async def list_schedules(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().list_schedules(*args, **kwargs)

    async def get_due_schedules(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().get_due_schedules(*args, **kwargs)

    async def list_logs_for_server(self, *args: Any, **kwargs: Any) -> Any:
        return await backup_scheduler_instance.get().list_logs_for_server(*args, **kwargs)

    # ---- Scheduler control ----

    async def start_scheduler(self) -> Any:
        return await backup_scheduler_instance.get().start_scheduler()

    async def stop_scheduler(self) -> Any:
        return await backup_scheduler_instance.get().stop_scheduler()

    async def load_schedules_from_db(self) -> Any:
        return await backup_scheduler_instance.get().load_schedules_from_db()

    def clear_cache(self) -> None:
        backup_scheduler_instance.get().clear_cache()

    # ---- Housekeeping ----

    def sweep_stale_pending_and_failed(self) -> Any:
        return backup_scheduler_instance.get().sweep_stale_pending_and_failed()

    # ---- Properties ----

    @property
    def is_running(self) -> bool:
        return backup_scheduler_instance.get().is_running

    @property
    def cache_size(self) -> int:
        return backup_scheduler_instance.get().cache_size


backup_scheduler = _SchedulerProxy()


__all__ = ["BackupSchedulerService", "_SchedulerProxy", "backup_scheduler"]
