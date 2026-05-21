"""Backward-compatibility shim for the migrated backup scheduler.

The real implementation lives at
`app.backups.application.scheduler.BackupSchedulerService` and is
provisioned during the FastAPI lifespan callback into
`app.backups.backup_scheduler_instance`.

`_SchedulerProxy` is the public alias `backup_scheduler` exported
from this module. It declares each forwarded method explicitly so
`hasattr(backup_scheduler, "start_scheduler")` returns True even
before the lifespan callback has run (required by
`tests/integration/test_main_comprehensive.py:628`).

Resolution-time dispatch (each call goes through
`backup_scheduler_instance.get()`) means tests that
`patch("app.backups.backup_scheduler_instance")` can inject a mock
without re-importing this module.

TODO(#228): once all in-tree callers depend on
`Depends(get_backup_scheduler_service)`, delete this file.
"""

from typing import Any

from app.backups import backup_scheduler_instance

__all__ = [
    "BackupSchedulerService",
    "backup_scheduler",
]

from app.backups.application.scheduler import (
    BackupSchedulerService as BackupSchedulerService,
)


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

    # ---- Properties ----

    @property
    def is_running(self) -> bool:
        return backup_scheduler_instance.get().is_running

    @property
    def cache_size(self) -> int:
        return backup_scheduler_instance.get().cache_size


backup_scheduler = _SchedulerProxy()
