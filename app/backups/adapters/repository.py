"""SQLAlchemy implementations of `BackupRepository` and
`BackupScheduleRepository`.

The adapters are the only layer that knows about the SQLAlchemy ORM
and the `Backup` / `BackupSchedule` / `BackupScheduleLog` / `User`
columns; they convert ORM rows to/from domain entities so the
application layer never sees ORM types.

Per the UnitOfWork pattern, repository methods **do not commit**. They
stage changes on the session and rely on the surrounding
`SqlAlchemyBackupsUnitOfWork` (or the caller) to commit.

Cross-domain JOIN against `User` (in `list_logs_for_server`) is
intentionally kept inside this adapter rather than dispatched through
a `UserReadPort`: the alternative would issue one query per log row
(legacy N+1). The `Backup.server` join is similarly eager-loaded so
the wire response can fill in `server_name` / `minecraft_version`
without a per-row lazy SELECT. See `docs/ARCHITECTURE.md` §4.3.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

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
from app.backups.models import Backup, BackupSchedule, BackupScheduleLog, BackupStatus
from app.core.datetime_utils import utcnow


def _backup_to_entity(row: Backup) -> BackupEntity:
    """Convert an ORM row to a `BackupEntity`.

    Reads `row.server.name` / `row.server.minecraft_version` /
    `row.server.owner_id` eagerly: callers that need these fields must
    load the row with `joinedload(Backup.server)` so the access does
    not trigger a separate SELECT.

    `server_owner_id` is denormalised under #274 so that
    ``AuthorizationService.can_delete_backup`` can keep a two-argument
    signature and the delete-backup router no longer needs a second
    round-trip to fetch the parent server purely for its owner.
    """
    return BackupEntity(
        id=row.id,
        server_id=row.server_id,
        name=row.name,
        description=row.description,
        file_path=row.file_path,
        file_size=row.file_size,
        backup_type=row.backup_type,
        status=row.status,
        created_at=row.created_at,
        server_name=row.server.name if row.server is not None else None,
        minecraft_version=row.server.minecraft_version
        if row.server is not None
        else None,
        server_owner_id=row.server.owner_id if row.server is not None else None,
    )


def _schedule_to_entity(row: BackupSchedule) -> BackupScheduleEntity:
    return BackupScheduleEntity(
        id=row.id,
        server_id=row.server_id,
        interval_hours=row.interval_hours,
        max_backups=row.max_backups,
        enabled=row.enabled,
        only_when_running=row.only_when_running,
        last_backup_at=row.last_backup_at,
        next_backup_at=row.next_backup_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _log_to_entity(row: BackupScheduleLog) -> BackupScheduleLogEntity:
    """Convert a log ORM row to a domain entity.

    `row.executed_by.username` is read eagerly; callers must use
    `joinedload(BackupScheduleLog.executed_by)` to avoid the legacy
    N+1 on the per-row username lookup.
    """
    username = row.executed_by.username if row.executed_by is not None else None
    return BackupScheduleLogEntity(
        id=row.id,
        server_id=row.server_id,
        action=row.action,
        reason=row.reason,
        old_config=row.old_config,
        new_config=row.new_config,
        executed_by_user_id=row.executed_by_user_id,
        executed_by_username=username,
        created_at=row.created_at,
    )


class SqlAlchemyBackupRepository:
    """SQLAlchemy-backed implementation of the backups persistence Port."""

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Reads
    # ===================

    async def get(self, backup_id: int) -> Optional[BackupEntity]:
        row = (
            self.db.query(Backup)
            .options(joinedload(Backup.server))
            .filter(Backup.id == backup_id)
            .first()
        )
        return _backup_to_entity(row) if row else None

    async def list_paged(self, spec: BackupListSpec) -> BackupListPage:
        query = self.db.query(Backup).options(joinedload(Backup.server))

        if spec.server_id is not None:
            query = query.filter(Backup.server_id == spec.server_id)
        if spec.backup_type is not None:
            query = query.filter(Backup.backup_type == spec.backup_type)
        if spec.status is not None:
            query = query.filter(Backup.status == spec.status)

        query = query.order_by(Backup.created_at.desc())

        total = query.count()
        rows = query.offset((spec.page - 1) * spec.size).limit(spec.size).all()

        return BackupListPage(
            entities=[_backup_to_entity(r) for r in rows],
            total=total,
            page=spec.page,
            size=spec.size,
        )

    async def get_statistics(self, server_id: Optional[int] = None) -> BackupStatistics:
        query = self.db.query(Backup)
        if server_id is not None:
            query = query.filter(Backup.server_id == server_id)

        total_backups = query.count()
        completed_backups = query.filter(Backup.status == BackupStatus.completed).count()
        failed_backups = query.filter(Backup.status == BackupStatus.failed).count()

        size_query = self.db.query(func.sum(Backup.file_size)).filter(
            Backup.status == BackupStatus.completed
        )
        if server_id is not None:
            size_query = size_query.filter(Backup.server_id == server_id)

        total_size = size_query.scalar() or 0

        return BackupStatistics(
            total_backups=total_backups,
            completed_backups=completed_backups,
            failed_backups=failed_backups,
            total_size_bytes=int(total_size),
        )

    # ===================
    # Writes
    # ===================

    async def add(self, command: CreateBackupCommand) -> BackupEntity:
        row = Backup(
            server_id=command.server_id,
            name=command.name,
            description=command.description,
            file_path=command.file_path,
            file_size=command.file_size,
            backup_type=command.backup_type,
            status=command.status,
        )
        self.db.add(row)
        self.db.flush()
        # Populate `server` relation so `_backup_to_entity` does not trigger
        # a stray lazy SELECT for the per-row server_name/minecraft_version.
        self.db.refresh(row, attribute_names=["created_at", "server"])
        return _backup_to_entity(row)

    async def update_file_info(
        self, backup_id: int, command: UpdateBackupFileCommand
    ) -> Optional[BackupEntity]:
        row = (
            self.db.query(Backup)
            .options(joinedload(Backup.server))
            .filter(Backup.id == backup_id)
            .first()
        )
        if row is None:
            return None
        row.file_path = command.file_path
        row.file_size = command.file_size
        row.status = command.status
        self.db.flush()
        return _backup_to_entity(row)

    async def update_status(
        self, backup_id: int, status: BackupStatus
    ) -> Optional[BackupEntity]:
        row = (
            self.db.query(Backup)
            .options(joinedload(Backup.server))
            .filter(Backup.id == backup_id)
            .first()
        )
        if row is None:
            return None
        row.status = status
        self.db.flush()
        return _backup_to_entity(row)

    async def delete(self, backup_id: int) -> bool:
        row = self.db.query(Backup).filter(Backup.id == backup_id).first()
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True


class SqlAlchemyBackupScheduleRepository:
    """SQLAlchemy-backed implementation of the schedule + log Ports."""

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Reads — schedules
    # ===================

    async def find_by_server(self, server_id: int) -> Optional[BackupScheduleEntity]:
        row = (
            self.db.query(BackupSchedule)
            .filter(BackupSchedule.server_id == server_id)
            .first()
        )
        return _schedule_to_entity(row) if row else None

    async def list(self, enabled_only: bool = False) -> List[BackupScheduleEntity]:
        query = self.db.query(BackupSchedule)
        if enabled_only:
            query = query.filter(BackupSchedule.enabled)
        return [_schedule_to_entity(r) for r in query.all()]

    async def list_due(self, now: datetime) -> List[BackupScheduleEntity]:
        rows = (
            self.db.query(BackupSchedule)
            .filter(
                BackupSchedule.enabled,
                BackupSchedule.next_backup_at <= now,
            )
            .order_by(BackupSchedule.next_backup_at.asc())
            .all()
        )
        return [_schedule_to_entity(r) for r in rows]

    # ===================
    # Reads — logs
    # ===================

    async def list_logs_for_server(
        self, server_id: int, page: int, size: int
    ) -> List[BackupScheduleLogEntity]:
        offset = (page - 1) * size
        rows = (
            self.db.query(BackupScheduleLog)
            .options(joinedload(BackupScheduleLog.executed_by))
            .filter(BackupScheduleLog.server_id == server_id)
            .order_by(BackupScheduleLog.created_at.desc())
            .offset(offset)
            .limit(size)
            .all()
        )
        return [_log_to_entity(r) for r in rows]

    # ===================
    # Writes — schedules
    # ===================

    async def add(self, command: CreateBackupScheduleCommand) -> BackupScheduleEntity:
        row = BackupSchedule(
            server_id=command.server_id,
            interval_hours=command.interval_hours,
            max_backups=command.max_backups,
            enabled=command.enabled,
            only_when_running=command.only_when_running,
            next_backup_at=command.next_backup_at,
        )
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row, attribute_names=["created_at", "updated_at"])
        return _schedule_to_entity(row)

    async def update(
        self, server_id: int, command: UpdateBackupScheduleCommand
    ) -> Optional[BackupScheduleEntity]:
        row = (
            self.db.query(BackupSchedule)
            .filter(BackupSchedule.server_id == server_id)
            .first()
        )
        if row is None:
            return None
        for field, value in command.applied_fields().items():
            setattr(row, field, value)
        # Bump updated_at explicitly: the legacy code did this manually
        # (the column has `onupdate=utcnow` but the schedule's tests
        # depend on the manual bump for deterministic ordering).
        row.updated_at = utcnow()
        self.db.flush()
        return _schedule_to_entity(row)

    async def delete_by_server(self, server_id: int) -> bool:
        row = (
            self.db.query(BackupSchedule)
            .filter(BackupSchedule.server_id == server_id)
            .first()
        )
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    # ===================
    # Writes — logs
    # ===================

    async def append_log(self, command: AppendScheduleLogCommand) -> None:
        row = BackupScheduleLog(
            server_id=command.server_id,
            action=command.action,
            reason=command.reason,
            old_config=command.old_config,
            new_config=command.new_config,
            executed_by_user_id=command.executed_by_user_id,
        )
        self.db.add(row)
        self.db.flush()
