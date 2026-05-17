"""SQLAlchemy implementation of the versions domain Ports.

Implements `app.versions.domain.ports.VersionRepository`. The adapter is
the only layer that knows about SQLAlchemy ORM and the table columns; it
converts ORM rows to/from `MinecraftVersionEntity` /
`VersionUpdateLogEntity` so the application layer never sees ORM types.

Per the UnitOfWork pattern, repository methods **do not commit**. They
stage changes on the session and rely on the surrounding
`SqlAlchemyUnitOfWork` (or the caller) to commit.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from app.core.datetime_utils import utcnow
from app.servers.models import ServerType
from app.versions.domain.entities import (
    CreateUpdateLogCommand,
    CreateVersionCommand,
    DuplicateVersionEntity,
    MinecraftVersionEntity,
    UpdateVersionCommand,
    VersionStatsEntity,
    VersionUpdateLogEntity,
)
from app.versions.models import MinecraftVersion, VersionUpdateLog


def _version_to_entity(v: MinecraftVersion) -> MinecraftVersionEntity:
    """Convert an ORM row into a domain entity."""
    return MinecraftVersionEntity(
        id=v.id,
        server_type=ServerType(v.server_type),
        version=v.version,
        download_url=v.download_url,
        release_date=v.release_date,
        is_stable=v.is_stable,
        build_number=v.build_number,
        is_active=v.is_active,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _log_to_entity(log: VersionUpdateLog) -> VersionUpdateLogEntity:
    """Convert a log ORM row into a domain entity."""
    return VersionUpdateLogEntity(
        id=log.id,
        update_type=log.update_type,
        status=log.status,
        server_type=log.server_type,
        versions_added=log.versions_added,
        versions_updated=log.versions_updated,
        versions_removed=log.versions_removed,
        execution_time_ms=log.execution_time_ms,
        external_api_calls=log.external_api_calls,
        error_message=log.error_message,
        executed_by_user_id=log.executed_by_user_id,
        started_at=log.started_at,
        completed_at=log.completed_at,
    )


class SqlAlchemyVersionRepository:
    """SQLAlchemy-backed implementation of the version persistence Port.

    Does not commit. Callers must drive transactions via `UnitOfWork`
    (production) or by explicitly committing the session (legacy paths,
    while shims still exist).
    """

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Version reads
    # ===================

    async def get_all_active_versions(self) -> List[MinecraftVersionEntity]:
        rows = (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.is_active)
            .order_by(MinecraftVersion.server_type, desc(MinecraftVersion.version))
            .all()
        )
        return [_version_to_entity(r) for r in rows]

    async def get_versions_by_type(
        self, server_type: ServerType
    ) -> List[MinecraftVersionEntity]:
        rows = (
            self.db.query(MinecraftVersion)
            .filter(
                and_(
                    MinecraftVersion.server_type == server_type.value,
                    MinecraftVersion.is_active,
                )
            )
            .order_by(desc(MinecraftVersion.version))
            .all()
        )
        return [_version_to_entity(r) for r in rows]

    async def get_version_by_type_and_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersionEntity]:
        row = (
            self.db.query(MinecraftVersion)
            .filter(
                and_(
                    MinecraftVersion.server_type == server_type.value,
                    MinecraftVersion.version == version,
                )
            )
            .first()
        )
        return _version_to_entity(row) if row else None

    # ===================
    # Version writes
    # ===================

    async def create_version(
        self, command: CreateVersionCommand
    ) -> MinecraftVersionEntity:
        row = MinecraftVersion(
            server_type=command.server_type.value,
            version=command.version,
            download_url=command.download_url,
            release_date=command.release_date,
            is_stable=command.is_stable,
            build_number=command.build_number,
        )
        self.db.add(row)
        self.db.flush()
        return _version_to_entity(row)

    async def upsert_version(
        self, command: CreateVersionCommand
    ) -> MinecraftVersionEntity:
        existing = (
            self.db.query(MinecraftVersion)
            .filter(
                and_(
                    MinecraftVersion.server_type == command.server_type.value,
                    MinecraftVersion.version == command.version,
                )
            )
            .first()
        )

        if existing:
            existing.download_url = command.download_url
            existing.release_date = command.release_date
            existing.is_stable = command.is_stable
            existing.build_number = command.build_number
            existing.is_active = True
            existing.updated_at = utcnow()
            self.db.flush()
            return _version_to_entity(existing)

        return await self.create_version(command)

    async def update_version(
        self, version_id: int, command: UpdateVersionCommand
    ) -> Optional[MinecraftVersionEntity]:
        row = (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.id == version_id)
            .first()
        )
        if not row:
            return None

        for field_name, value in command.applied_fields().items():
            setattr(row, field_name, value)
        row.updated_at = utcnow()

        self.db.flush()
        return _version_to_entity(row)

    async def deactivate_versions(
        self, server_type: ServerType, keep_versions: List[str]
    ) -> int:
        query = self.db.query(MinecraftVersion).filter(
            and_(
                MinecraftVersion.server_type == server_type.value,
                MinecraftVersion.is_active,
                ~MinecraftVersion.version.in_(keep_versions),
            )
        )

        count = query.count()

        query.update(
            {"is_active": False, "updated_at": utcnow()},
            synchronize_session=False,
        )
        return count

    async def cleanup_old_versions(self, days_old: int = 30) -> int:
        cutoff_date = utcnow() - timedelta(days=days_old)

        query = self.db.query(MinecraftVersion).filter(
            and_(
                ~MinecraftVersion.is_active,
                MinecraftVersion.updated_at < cutoff_date,
            )
        )

        count = query.count()
        query.delete(synchronize_session=False)
        return count

    # ===================
    # Statistics
    # ===================

    async def get_version_stats(self) -> VersionStatsEntity:
        stats = (
            self.db.query(
                MinecraftVersion.server_type,
                func.count(MinecraftVersion.id).label("total"),
                func.count(func.nullif(MinecraftVersion.is_active, False)).label(
                    "active"
                ),
            )
            .group_by(MinecraftVersion.server_type)
            .all()
        )

        by_type: dict = {}
        total_total = 0
        total_active = 0
        for stat in stats:
            by_type[stat.server_type] = {"total": stat.total, "active": stat.active}
            total_total += stat.total
            total_active += stat.active

        return VersionStatsEntity(
            total_versions=total_total,
            active_versions=total_active,
            by_server_type=by_type,
        )

    # ===================
    # Update log
    # ===================

    async def create_update_log(
        self, command: CreateUpdateLogCommand
    ) -> VersionUpdateLogEntity:
        row = VersionUpdateLog(
            update_type=command.update_type,
            status=command.status,
            server_type=command.server_type,
            executed_by_user_id=command.executed_by_user_id,
        )
        self.db.add(row)
        self.db.flush()
        return _log_to_entity(row)

    async def complete_update_log(
        self,
        log_id: int,
        status: str,
        execution_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
        versions_added: int = 0,
        versions_updated: int = 0,
        versions_removed: int = 0,
        external_api_calls: int = 0,
    ) -> Optional[VersionUpdateLogEntity]:
        row = (
            self.db.query(VersionUpdateLog).filter(VersionUpdateLog.id == log_id).first()
        )
        if not row:
            return None

        row.status = status
        row.completed_at = utcnow()
        row.execution_time_ms = execution_time_ms
        row.error_message = error_message
        row.versions_added = versions_added
        row.versions_updated = versions_updated
        row.versions_removed = versions_removed
        row.external_api_calls = external_api_calls

        self.db.flush()
        return _log_to_entity(row)

    async def get_latest_update_log(self) -> Optional[VersionUpdateLogEntity]:
        row = (
            self.db.query(VersionUpdateLog)
            .order_by(desc(VersionUpdateLog.started_at))
            .first()
        )
        return _log_to_entity(row) if row else None

    async def get_update_logs(
        self, limit: int = 10, update_type: Optional[str] = None
    ) -> List[VersionUpdateLogEntity]:
        query = self.db.query(VersionUpdateLog)
        if update_type:
            query = query.filter(VersionUpdateLog.update_type == update_type)
        rows = query.order_by(desc(VersionUpdateLog.started_at)).limit(limit).all()
        return [_log_to_entity(r) for r in rows]

    # ===================
    # Sync convenience for management/CLI
    # ===================

    def get_all_versions(
        self, limit: Optional[int] = None
    ) -> List[MinecraftVersionEntity]:
        query = self.db.query(MinecraftVersion).order_by(
            MinecraftVersion.updated_at.desc()
        )
        if limit:
            query = query.limit(limit)
        return [_version_to_entity(r) for r in query.all()]

    def get_versions_by_server_type(
        self, server_type: str
    ) -> List[MinecraftVersionEntity]:
        rows = (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.server_type == server_type)
            .order_by(MinecraftVersion.updated_at.desc())
            .all()
        )
        return [_version_to_entity(r) for r in rows]

    def delete_version(self, version_id: int) -> bool:
        row = (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.id == version_id)
            .first()
        )
        if not row:
            return False
        self.db.delete(row)
        return True

    def find_duplicate_versions(self) -> List[DuplicateVersionEntity]:
        rows = (
            self.db.query(
                MinecraftVersion.server_type,
                MinecraftVersion.version,
                func.count(MinecraftVersion.id).label("count"),
            )
            .group_by(MinecraftVersion.server_type, MinecraftVersion.version)
            .having(func.count(MinecraftVersion.id) > 1)
            .all()
        )
        return [
            DuplicateVersionEntity(
                server_type=r.server_type, version=r.version, count=r.count
            )
            for r in rows
        ]

    def get_versions_older_than(
        self, cutoff_date: datetime
    ) -> List[MinecraftVersionEntity]:
        rows = (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.updated_at < cutoff_date)
            .order_by(MinecraftVersion.updated_at.asc())
            .all()
        )
        return [_version_to_entity(r) for r in rows]
