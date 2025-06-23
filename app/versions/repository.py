"""
Repository for Minecraft version data access
"""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from app.servers.models import ServerType
from app.versions.models import MinecraftVersion, VersionUpdateLog
from app.versions.schemas import (
    MinecraftVersionCreate,
    MinecraftVersionUpdate,
    VersionUpdateLogCreate,
)


class VersionRepository:
    """
    Repository for managing Minecraft version data

    Provides high-performance database operations for version management,
    replacing the slow external API calls.
    """

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Version CRUD operations
    # ===================

    async def get_all_active_versions(self) -> List[MinecraftVersion]:
        """Get all active versions across all server types"""
        return (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.is_active)
            .order_by(MinecraftVersion.server_type, desc(MinecraftVersion.version))
            .all()
        )

    async def get_versions_by_type(
        self, server_type: ServerType
    ) -> List[MinecraftVersion]:
        """Get active versions for a specific server type"""
        return (
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

    async def get_version_by_type_and_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersion]:
        """Get a specific version by server type and version string"""
        return (
            self.db.query(MinecraftVersion)
            .filter(
                and_(
                    MinecraftVersion.server_type == server_type.value,
                    MinecraftVersion.version == version,
                )
            )
            .first()
        )

    async def create_version(
        self, version_data: MinecraftVersionCreate
    ) -> MinecraftVersion:
        """Create a new version record"""
        db_version = MinecraftVersion(
            server_type=version_data.server_type.value,
            version=version_data.version,
            download_url=version_data.download_url,
            release_date=version_data.release_date,
            is_stable=version_data.is_stable,
            build_number=version_data.build_number,
        )

        self.db.add(db_version)
        self.db.commit()
        self.db.refresh(db_version)
        return db_version

    async def upsert_version(
        self, version_data: MinecraftVersionCreate
    ) -> MinecraftVersion:
        """Insert or update a version record"""
        existing = await self.get_version_by_type_and_version(
            version_data.server_type, version_data.version
        )

        if existing:
            # Update existing version
            existing.download_url = version_data.download_url
            existing.release_date = version_data.release_date
            existing.is_stable = version_data.is_stable
            existing.build_number = version_data.build_number
            existing.is_active = True  # Reactivate if was inactive
            existing.updated_at = datetime.utcnow()

            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            # Create new version
            return await self.create_version(version_data)

    async def update_version(
        self, version_id: int, version_data: MinecraftVersionUpdate
    ) -> Optional[MinecraftVersion]:
        """Update an existing version record"""
        db_version = (
            self.db.query(MinecraftVersion)
            .filter(MinecraftVersion.id == version_id)
            .first()
        )

        if not db_version:
            return None

        # Update only provided fields
        for field, value in version_data.model_dump(exclude_unset=True).items():
            setattr(db_version, field, value)

        db_version.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(db_version)
        return db_version

    async def deactivate_versions(
        self, server_type: ServerType, keep_versions: List[str]
    ) -> int:
        """
        Deactivate versions not in the keep list
        Returns number of versions deactivated
        """
        query = self.db.query(MinecraftVersion).filter(
            and_(
                MinecraftVersion.server_type == server_type.value,
                MinecraftVersion.is_active,
                ~MinecraftVersion.version.in_(keep_versions),
            )
        )

        count = query.count()

        query.update(
            {"is_active": False, "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )

        self.db.commit()
        return count

    async def cleanup_old_versions(self, days_old: int = 30) -> int:
        """
        Remove very old inactive versions to save space
        Returns number of versions deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        query = self.db.query(MinecraftVersion).filter(
            and_(
                ~MinecraftVersion.is_active,
                MinecraftVersion.updated_at < cutoff_date,
            )
        )

        count = query.count()
        query.delete(synchronize_session=False)

        self.db.commit()
        return count

    # ===================
    # Statistics and monitoring
    # ===================

    async def get_version_stats(self) -> dict:
        """Get version statistics by server type"""
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

        result = {}
        total_active = 0

        for stat in stats:
            result[stat.server_type] = {"total": stat.total, "active": stat.active}
            total_active += stat.active

        result["_total"] = {
            "total": sum(s["total"] for s in result.values() if isinstance(s, dict)),
            "active": total_active,
        }

        return result

    # ===================
    # Update log operations
    # ===================

    async def create_update_log(
        self, log_data: VersionUpdateLogCreate
    ) -> VersionUpdateLog:
        """Create a new update log entry"""
        db_log = VersionUpdateLog(**log_data.model_dump())

        self.db.add(db_log)
        self.db.commit()
        self.db.refresh(db_log)
        return db_log

    async def complete_update_log(
        self,
        log_id: int,
        status: str,
        execution_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[VersionUpdateLog]:
        """Mark an update log as completed"""
        db_log = (
            self.db.query(VersionUpdateLog).filter(VersionUpdateLog.id == log_id).first()
        )

        if not db_log:
            return None

        db_log.status = status
        db_log.completed_at = datetime.utcnow()
        db_log.execution_time_ms = execution_time_ms
        db_log.error_message = error_message

        self.db.commit()
        self.db.refresh(db_log)
        return db_log

    async def get_latest_update_log(self) -> Optional[VersionUpdateLog]:
        """Get the most recent update log"""
        return (
            self.db.query(VersionUpdateLog)
            .order_by(desc(VersionUpdateLog.started_at))
            .first()
        )

    async def get_update_logs(
        self, limit: int = 10, update_type: Optional[str] = None
    ) -> List[VersionUpdateLog]:
        """Get recent update logs with optional filtering"""
        query = self.db.query(VersionUpdateLog)

        if update_type:
            query = query.filter(VersionUpdateLog.update_type == update_type)

        return query.order_by(desc(VersionUpdateLog.started_at)).limit(limit).all()
