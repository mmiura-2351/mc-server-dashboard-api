"""Port (Protocol) definitions for the backups domain.

Per `docs/app/ARCHITECTURE.md` Section 4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types crossing
these Protocols are pure domain entities defined in `entities.py`.

Three Ports are defined:

- `BackupRepository`: persistence Port for the `Backup` aggregate.
- `BackupScheduleRepository`: persistence Port for the
  `BackupSchedule` + `BackupScheduleLog` aggregates. Split from
  `BackupRepository` because the two have independent transactional
  lifetimes (a schedule mutation is unrelated to a backup row mutation).
- `BackupsUnitOfWork`: transactional boundary Port. Application code
  wraps a set of repository calls in `async with uow:` and calls
  `await uow.commit()` to finalise.
"""

from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol

from app.backups.domain.entities import (
    AppendScheduleLogCommand,
    BackupEntity,
    BackupListPage,
    BackupListSpec,
    BackupScheduleEntity,
    BackupScheduleLogEntity,
    BackupStatistics,
    CreateBackupCommand,
    CreateBackupScheduleCommand,
    UpdateBackupFileCommand,
    UpdateBackupScheduleCommand,
)
from app.servers.domain.value_objects import BackupStatus


class BackupRepository(Protocol):
    """Persistence port for the `Backup` aggregate.

    Concrete implementations: `SqlAlchemyBackupRepository` (production),
    `FakeBackupRepository` (unit tests).

    Repository methods **do not commit**. Wrap calls in a
    `BackupsUnitOfWork` context and call `await uow.commit()` once
    you are done.
    """

    # ----- Reads -----

    async def get(self, backup_id: int) -> Optional[BackupEntity]: ...

    async def list_paged(self, spec: BackupListSpec) -> BackupListPage: ...

    async def get_statistics(
        self, server_id: Optional[int] = None
    ) -> BackupStatistics: ...

    # ----- Writes -----

    async def add(self, command: CreateBackupCommand) -> BackupEntity:
        """Insert a new backup row.

        The default `CreateBackupCommand` has `status=creating` and
        empty file fields — that is the two-phase create path. Callers
        on the upload path pass `status=completed` plus the file
        fields, making this a one-shot insert.
        """
        ...

    async def update_file_info(
        self, backup_id: int, command: UpdateBackupFileCommand
    ) -> Optional[BackupEntity]: ...

    async def update_status(
        self, backup_id: int, status: BackupStatus
    ) -> Optional[BackupEntity]: ...

    async def delete(self, backup_id: int) -> bool: ...


class BackupScheduleRepository(Protocol):
    """Persistence port for the `BackupSchedule` + log aggregates.

    Cross-domain JOIN against `User` (for `executed_by_username`) is
    intentionally kept here rather than dispatched through a
    `UserReadPort`: the alternative would issue one query per log row
    (legacy N+1). See `docs/app/ARCHITECTURE.md` Section 4.3 — the adapter layer
    is allowed to touch the ORM directly; only the **application**
    layer is forbidden.
    """

    # ----- Reads -----

    async def find_by_server(self, server_id: int) -> Optional[BackupScheduleEntity]: ...

    async def list(self, enabled_only: bool = False) -> List[BackupScheduleEntity]: ...

    async def list_due(self, now: datetime) -> List[BackupScheduleEntity]:
        """Return enabled schedules whose `next_backup_at <= now`."""
        ...

    async def list_logs_for_server(
        self, server_id: int, page: int, size: int
    ) -> List[BackupScheduleLogEntity]: ...

    # ----- Writes -----

    async def add(self, command: CreateBackupScheduleCommand) -> BackupScheduleEntity: ...

    async def update(
        self, server_id: int, command: UpdateBackupScheduleCommand
    ) -> Optional[BackupScheduleEntity]: ...

    async def delete_by_server(self, server_id: int) -> bool: ...

    async def append_log(self, command: AppendScheduleLogCommand) -> None: ...


class BackupsUnitOfWork(Protocol):
    """Transactional boundary Port for the backups domain.

    Application services enter a UoW context, perform repository
    operations through the same session, then call `commit()` to
    persist atomically. Exiting the context without committing rolls
    back.
    """

    backups: BackupRepository
    schedules: BackupScheduleRepository

    async def __aenter__(self) -> "BackupsUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
