"""Pure domain entities for the backups module.

These dataclasses are the language the application layer speaks. They have
no SQLAlchemy, Pydantic, FastAPI, or any framework dependency — only the
Python standard library (plus `BackupType`, `BackupStatus`, and
`ScheduleAction`, all `enum.Enum`; see the deviation notes in
`app.backups.domain.__init__`).

The application service receives and returns these types. Adapters convert
to/from ORM rows; the api layer converts to/from Pydantic DTOs.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.backups.models import ScheduleAction
from app.servers.models import (  # known deviation: see __init__.py
    BackupStatus,
    BackupType,
)

# ---------------------------------------------------------------------------
# Backup aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupEntity:
    """A persisted backup row.

    `server_name` / `minecraft_version` are denormalised onto the entity
    because the wire response (`BackupResponse`) needs both and the
    adapter eager-loads `Backup.server` via `joinedload` to avoid a
    per-row N+1.
    """

    id: int
    server_id: int
    name: str
    description: Optional[str]
    file_path: str
    file_size: int
    backup_type: BackupType
    status: BackupStatus
    created_at: datetime
    server_name: Optional[str]
    minecraft_version: Optional[str]


@dataclass(frozen=True)
class CreateBackupCommand:
    """Inputs to persist a new backup row.

    Used for both the two-phase create path (status=creating, empty
    file fields, later finalised via `update_file_info`) and the
    one-shot upload path (status=completed, file fields populated).
    Defaults match the two-phase create path.
    """

    server_id: int
    name: str
    description: Optional[str]
    backup_type: BackupType
    status: BackupStatus = BackupStatus.creating
    file_path: str = ""
    file_size: int = 0


@dataclass(frozen=True)
class UpdateBackupFileCommand:
    """Update a backup row with file metadata after the archive is written."""

    file_path: str
    file_size: int
    status: BackupStatus


@dataclass(frozen=True)
class BackupListSpec:
    """Inputs for `BackupRepository.list_paged`."""

    server_id: Optional[int] = None
    backup_type: Optional[BackupType] = None
    status: Optional[BackupStatus] = None
    page: int = 1
    size: int = 50


@dataclass(frozen=True)
class BackupListPage:
    """Read result for `BackupRepository.list_paged`."""

    entities: List[BackupEntity]
    total: int
    page: int
    size: int


@dataclass(frozen=True)
class BackupStatistics:
    """Aggregate counts for the backup catalogue.

    Pure domain DTO: no `total_size_mb` (MB conversion is an
    application/api concern, kept out of the persistence boundary per
    lesson #9).
    """

    total_backups: int
    completed_backups: int
    failed_backups: int
    total_size_bytes: int


# ---------------------------------------------------------------------------
# BackupSchedule aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupScheduleEntity:
    """A persisted backup-schedule row.

    `BackupSchedule.server_id` is `unique=True`, so the schedule is
    effectively keyed by server. The Repository surface mirrors that:
    most reads are `find_by_server`, not `get(id)`.
    """

    id: int
    server_id: int
    interval_hours: int
    max_backups: int
    enabled: bool
    only_when_running: bool
    last_backup_at: Optional[datetime]
    next_backup_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreateBackupScheduleCommand:
    """Inputs to persist a new backup schedule row."""

    server_id: int
    interval_hours: int
    max_backups: int
    enabled: bool
    only_when_running: bool
    next_backup_at: Optional[datetime]


@dataclass(frozen=True)
class UpdateBackupScheduleCommand:
    """Sparse update for an existing schedule.

    A field set to `None` is treated as "leave column untouched".
    `next_backup_at` is set by the application layer (recomputed when
    the interval changes); the adapter does not derive it.
    """

    interval_hours: Optional[int] = None
    max_backups: Optional[int] = None
    enabled: Optional[bool] = None
    only_when_running: Optional[bool] = None
    last_backup_at: Optional[datetime] = None
    next_backup_at: Optional[datetime] = None

    def applied_fields(self) -> Dict[str, Any]:
        """Return only the fields the caller actually set (non-None)."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


# ---------------------------------------------------------------------------
# BackupScheduleLog aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupScheduleLogEntity:
    """A persisted log row recording a schedule mutation or execution.

    `executed_by_username` is eager-loaded via `joinedload(executed_by)`
    in the adapter to eliminate the legacy N+1 on the per-row username
    lookup.
    """

    id: int
    server_id: int
    action: ScheduleAction
    reason: Optional[str]
    old_config: Optional[Dict[str, Any]]
    new_config: Optional[Dict[str, Any]]
    executed_by_user_id: Optional[int]
    executed_by_username: Optional[str]
    created_at: datetime


@dataclass(frozen=True)
class AppendScheduleLogCommand:
    """Inputs to persist a new schedule-log row."""

    server_id: int
    action: ScheduleAction
    reason: Optional[str] = None
    old_config: Optional[Dict[str, Any]] = None
    new_config: Optional[Dict[str, Any]] = None
    executed_by_user_id: Optional[int] = None
