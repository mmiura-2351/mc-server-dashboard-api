"""Backups domain package.

Eagerly imports `app.backups.models` so the `Backup`, `BackupSchedule`,
and `BackupScheduleLog` SQLAlchemy classes are registered with
`Base.metadata` before `Base.metadata.create_all()` runs in `app.main`
startup. This also ensures `Server.backups` / `Server.backup_schedule`
relationships in `app.servers.models` resolve at mapper-configuration
time.

Re-exports the lifespan-scoped `backup_scheduler_instance` holder so
that the FastAPI app startup (`app.main._initialize_backup_scheduler`)
and the module-level `_SchedulerProxy` (in
`app.backups.application.scheduler`) can share the same singleton
without crossing layers.

The holder pattern (not a module-global instance) is necessary because
the scheduler is wired during FastAPI's `lifespan` callback, *after*
all module imports have resolved. A bare module-level instance would
either be `None` for tests that import-then-mock, or would have to be
built at import time (which is too early to depend on a session
factory). Tests can `backup_scheduler_instance.set(...)` to inject a
test double; production calls `make_backup_scheduler()` in
`_initialize_backup_scheduler`.
"""

from typing import TYPE_CHECKING, Optional

from . import (
    models,  # noqa: F401  # eager import so ORM classes register before create_all
)

if TYPE_CHECKING:
    from app.backups.application.scheduler import BackupSchedulerService


class _BackupSchedulerInstance:
    """Process-wide holder for the current `BackupSchedulerService`.

    Mirrors the pattern used elsewhere for late-bound singletons
    (`websocket_service`, etc.). `get()` raises `RuntimeError` if no
    instance has been set yet — this gives a clear error rather than
    masking the missing-init bug with an `AttributeError`.
    """

    def __init__(self) -> None:
        self._instance: Optional["BackupSchedulerService"] = None

    def set(self, instance: "BackupSchedulerService") -> None:
        self._instance = instance

    def get(self) -> "BackupSchedulerService":
        if self._instance is None:
            raise RuntimeError(
                "BackupSchedulerService is not initialised; "
                "call make_backup_scheduler() during application startup."
            )
        return self._instance

    def clear(self) -> None:
        """Reset to the un-initialised state (test helper)."""
        self._instance = None

    def is_set(self) -> bool:
        return self._instance is not None


backup_scheduler_instance = _BackupSchedulerInstance()
