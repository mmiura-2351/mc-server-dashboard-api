"""In-memory fakes for the backups domain Ports.

These structurally implement the Protocols in
`app.backups.domain.ports`. They let unit tests exercise the backups
application service without a database.

`FakeServerReadPort` is reused from `tests.unit.files.fakes` (or kept
local here when the existing one lacks fields). For #227 we use a
local lightweight `FakeServerReadPort` because the legacy
`tests/unit/files/fakes.py` `get` method may not return all the fields
the backup service touches.
"""

from dataclasses import replace
from datetime import datetime, timezone
from types import TracebackType
from typing import Dict, List, Optional

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
from app.backups.models import BackupStatus, BackupType, ScheduleAction
from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Backup repository fake
# ---------------------------------------------------------------------------


class FakeBackupRepository:
    """Dict-backed `BackupRepository` for unit tests."""

    def __init__(self) -> None:
        self._records: Dict[int, BackupEntity] = {}
        self._next_id = 1

    # ----- Reads -----

    async def get(self, backup_id: int) -> Optional[BackupEntity]:
        return self._records.get(backup_id)

    async def list_paged(self, spec: BackupListSpec) -> BackupListPage:
        rows = list(self._records.values())
        if spec.server_id is not None:
            rows = [r for r in rows if r.server_id == spec.server_id]
        if spec.backup_type is not None:
            rows = [r for r in rows if r.backup_type == spec.backup_type]
        if spec.status is not None:
            rows = [r for r in rows if r.status == spec.status]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        total = len(rows)
        start = (spec.page - 1) * spec.size
        end = start + spec.size
        return BackupListPage(
            entities=rows[start:end],
            total=total,
            page=spec.page,
            size=spec.size,
        )

    async def get_statistics(self, server_id: Optional[int] = None) -> BackupStatistics:
        rows = list(self._records.values())
        if server_id is not None:
            rows = [r for r in rows if r.server_id == server_id]
        completed = [r for r in rows if r.status == BackupStatus.completed]
        failed = [r for r in rows if r.status == BackupStatus.failed]
        return BackupStatistics(
            total_backups=len(rows),
            completed_backups=len(completed),
            failed_backups=len(failed),
            total_size_bytes=sum(r.file_size for r in completed),
        )

    # ----- Writes -----

    async def add(self, command: CreateBackupCommand) -> BackupEntity:
        entity = BackupEntity(
            id=self._next_id,
            server_id=command.server_id,
            name=command.name,
            description=command.description,
            file_path=command.file_path,
            file_size=command.file_size,
            backup_type=command.backup_type,
            status=command.status,
            created_at=_utcnow(),
            server_name=None,
            minecraft_version=None,
            server_owner_id=None,
        )
        self._records[self._next_id] = entity
        self._next_id += 1
        return entity

    async def update_file_info(
        self, backup_id: int, command: UpdateBackupFileCommand
    ) -> Optional[BackupEntity]:
        existing = self._records.get(backup_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            file_path=command.file_path,
            file_size=command.file_size,
            status=command.status,
        )
        self._records[backup_id] = updated
        return updated

    async def update_status(
        self, backup_id: int, status: BackupStatus
    ) -> Optional[BackupEntity]:
        existing = self._records.get(backup_id)
        if existing is None:
            return None
        updated = replace(existing, status=status)
        self._records[backup_id] = updated
        return updated

    async def delete(self, backup_id: int) -> bool:
        if backup_id not in self._records:
            return False
        del self._records[backup_id]
        return True

    # ----- Test helpers -----

    def seed(self, entity: BackupEntity) -> BackupEntity:
        assert entity.id is not None
        self._records[entity.id] = entity
        self._next_id = max(self._next_id, entity.id + 1)
        return entity


# ---------------------------------------------------------------------------
# Schedule repository fake
# ---------------------------------------------------------------------------


class FakeBackupScheduleRepository:
    """Dict-backed `BackupScheduleRepository` for unit tests."""

    def __init__(self) -> None:
        self._schedules: Dict[int, BackupScheduleEntity] = {}  # keyed by server_id
        self._logs: List[BackupScheduleLogEntity] = []
        self._next_schedule_id = 1
        self._next_log_id = 1
        # Optional injection point so a test can force the next append_log()
        # call to raise — used to pin the atomic schedule+log behaviour.
        self._append_log_raises: Optional[BaseException] = None

    # ----- Reads -----

    async def find_by_server(self, server_id: int) -> Optional[BackupScheduleEntity]:
        return self._schedules.get(server_id)

    async def list(self, enabled_only: bool = False) -> List[BackupScheduleEntity]:
        rows = list(self._schedules.values())
        if enabled_only:
            rows = [r for r in rows if r.enabled]
        return rows

    async def list_due(self, now: datetime) -> List[BackupScheduleEntity]:
        rows = [
            r
            for r in self._schedules.values()
            if r.enabled and r.next_backup_at is not None and r.next_backup_at <= now
        ]
        rows.sort(key=lambda r: r.next_backup_at or now)
        return rows

    async def list_logs_for_server(
        self, server_id: int, page: int, size: int
    ) -> List[BackupScheduleLogEntity]:
        rows = [log for log in self._logs if log.server_id == server_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        start = (page - 1) * size
        end = start + size
        return rows[start:end]

    # ----- Writes -----

    async def add(self, command: CreateBackupScheduleCommand) -> BackupScheduleEntity:
        now = _utcnow()
        entity = BackupScheduleEntity(
            id=self._next_schedule_id,
            server_id=command.server_id,
            interval_hours=command.interval_hours,
            max_backups=command.max_backups,
            enabled=command.enabled,
            only_when_running=command.only_when_running,
            last_backup_at=None,
            next_backup_at=command.next_backup_at,
            created_at=now,
            updated_at=now,
        )
        self._schedules[command.server_id] = entity
        self._next_schedule_id += 1
        return entity

    async def update(
        self, server_id: int, command: UpdateBackupScheduleCommand
    ) -> Optional[BackupScheduleEntity]:
        existing = self._schedules.get(server_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            **command.applied_fields(),
            updated_at=_utcnow(),
        )
        self._schedules[server_id] = updated
        return updated

    async def delete_by_server(self, server_id: int) -> bool:
        if server_id not in self._schedules:
            return False
        del self._schedules[server_id]
        return True

    async def append_log(self, command: AppendScheduleLogCommand) -> None:
        if self._append_log_raises is not None:
            raise self._append_log_raises
        log = BackupScheduleLogEntity(
            id=self._next_log_id,
            server_id=command.server_id,
            action=command.action,
            reason=command.reason,
            old_config=command.old_config,
            new_config=command.new_config,
            executed_by_user_id=command.executed_by_user_id,
            executed_by_username=None,
            created_at=_utcnow(),
        )
        self._logs.append(log)
        self._next_log_id += 1

    # ----- Test helpers -----

    def seed_schedule(self, entity: BackupScheduleEntity) -> None:
        self._schedules[entity.server_id] = entity
        self._next_schedule_id = max(self._next_schedule_id, entity.id + 1)

    def fail_next_log(self, exc: BaseException) -> None:
        """Force the next `append_log` call to raise `exc`."""
        self._append_log_raises = exc


# ---------------------------------------------------------------------------
# UnitOfWork fake
# ---------------------------------------------------------------------------


class FakeBackupsUnitOfWork:
    """In-memory `BackupsUnitOfWork` for unit tests.

    Re-uses repository instances across enters so test setup carries
    through into the code under test. NB: `rollback()` does NOT undo
    changes already applied to the in-memory store — assert via
    `rolled_back` counter or compare snapshots.
    """

    def __init__(
        self,
        backups: Optional[FakeBackupRepository] = None,
        schedules: Optional[FakeBackupScheduleRepository] = None,
    ):
        self.backups: FakeBackupRepository = backups or FakeBackupRepository()
        self.schedules: FakeBackupScheduleRepository = (
            schedules or FakeBackupScheduleRepository()
        )
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeBackupsUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


# ---------------------------------------------------------------------------
# Server read port fake
# ---------------------------------------------------------------------------


class FakeServerReadPort:
    """Lightweight `ServerReadPort` for backup unit tests."""

    def __init__(self) -> None:
        self._servers: Dict[int, ServerEntity] = {}

    async def get_directory_path(self, server_id: int) -> Optional[str]:
        s = self._servers.get(server_id)
        return s.directory_path if s else None

    async def get(self, server_id: int) -> Optional[ServerEntity]:
        return self._servers.get(server_id)

    def seed(
        self,
        *,
        id: int,
        owner_id: int = 1,
        name: str = "srv",
        directory_path: str = "/srv",
        port: int = 25565,
        server_type: ServerType = ServerType.vanilla,
        minecraft_version: str = "1.20.1",
        max_memory: int = 1024,
        max_players: int = 20,
    ) -> ServerEntity:
        entity = ServerEntity(
            id=id,
            name=name,
            directory_path=directory_path,
            minecraft_version=minecraft_version,
            server_type=server_type,
            port=port,
            max_memory=max_memory,
            max_players=max_players,
            owner_id=owner_id,
        )
        self._servers[id] = entity
        return entity


# ---------------------------------------------------------------------------
# Helper for constructing entities in tests
# ---------------------------------------------------------------------------


def make_backup_entity(
    *,
    id: int,
    server_id: int,
    name: str = "b",
    description: Optional[str] = None,
    file_path: str = "",
    file_size: int = 0,
    backup_type: BackupType = BackupType.manual,
    status: BackupStatus = BackupStatus.creating,
    created_at: Optional[datetime] = None,
    server_name: Optional[str] = None,
    minecraft_version: Optional[str] = None,
    server_owner_id: Optional[int] = None,
) -> BackupEntity:
    return BackupEntity(
        id=id,
        server_id=server_id,
        name=name,
        description=description,
        file_path=file_path,
        file_size=file_size,
        backup_type=backup_type,
        status=status,
        created_at=created_at or _utcnow(),
        server_name=server_name,
        minecraft_version=minecraft_version,
        server_owner_id=server_owner_id,
    )


def make_schedule_entity(
    *,
    id: int,
    server_id: int,
    interval_hours: int = 24,
    max_backups: int = 5,
    enabled: bool = True,
    only_when_running: bool = True,
    last_backup_at: Optional[datetime] = None,
    next_backup_at: Optional[datetime] = None,
) -> BackupScheduleEntity:
    now = _utcnow()
    return BackupScheduleEntity(
        id=id,
        server_id=server_id,
        interval_hours=interval_hours,
        max_backups=max_backups,
        enabled=enabled,
        only_when_running=only_when_running,
        last_backup_at=last_backup_at,
        next_backup_at=next_backup_at,
        created_at=now,
        updated_at=now,
    )


# Re-export for convenience
__all__ = [
    "FakeBackupRepository",
    "FakeBackupScheduleRepository",
    "FakeBackupsUnitOfWork",
    "FakeServerReadPort",
    "make_backup_entity",
    "make_schedule_entity",
    "ScheduleAction",
    "_utcnow",
]
