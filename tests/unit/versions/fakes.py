"""In-memory fake implementations of versions domain Ports.

These fakes structurally implement `app.versions.domain.ports.VersionRepository`
and let unit tests exercise application services without a database. They
replace MagicMock-on-Session chains across the test suite.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.core.datetime_utils import utcnow
from app.servers.models import ServerType
from app.versions.models import MinecraftVersion, VersionUpdateLog
from app.versions.schemas import (
    MinecraftVersionCreate,
    MinecraftVersionUpdate,
    VersionUpdateLogCreate,
)


class FakeVersionRepository:
    """Dict-backed `VersionRepository` for unit tests."""

    def __init__(self) -> None:
        self._versions: Dict[int, MinecraftVersion] = {}
        self._logs: Dict[int, VersionUpdateLog] = {}
        self._next_version_id = 1
        self._next_log_id = 1

    # ----- internal helpers -----

    def _new_version(self, data: MinecraftVersionCreate) -> MinecraftVersion:
        v = MinecraftVersion(
            id=self._next_version_id,
            server_type=data.server_type.value,
            version=data.version,
            download_url=data.download_url,
            release_date=data.release_date,
            is_stable=data.is_stable,
            build_number=data.build_number,
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self._versions[self._next_version_id] = v
        self._next_version_id += 1
        return v

    # ----- Version CRUD -----

    async def get_all_active_versions(self) -> List[MinecraftVersion]:
        return sorted(
            (v for v in self._versions.values() if v.is_active),
            key=lambda v: (v.server_type, v.version),
            reverse=False,
        )

    async def get_versions_by_type(
        self, server_type: ServerType
    ) -> List[MinecraftVersion]:
        return sorted(
            (
                v
                for v in self._versions.values()
                if v.server_type == server_type.value and v.is_active
            ),
            key=lambda v: v.version,
            reverse=True,
        )

    async def get_version_by_type_and_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersion]:
        for v in self._versions.values():
            if v.server_type == server_type.value and v.version == version:
                return v
        return None

    async def create_version(
        self, version_data: MinecraftVersionCreate
    ) -> MinecraftVersion:
        return self._new_version(version_data)

    async def upsert_version(
        self, version_data: MinecraftVersionCreate
    ) -> MinecraftVersion:
        existing = await self.get_version_by_type_and_version(
            version_data.server_type, version_data.version
        )
        if existing:
            existing.download_url = version_data.download_url
            existing.release_date = version_data.release_date
            existing.is_stable = version_data.is_stable
            existing.build_number = version_data.build_number
            existing.is_active = True
            existing.updated_at = utcnow()
            return existing
        return self._new_version(version_data)

    async def update_version(
        self, version_id: int, version_data: MinecraftVersionUpdate
    ) -> Optional[MinecraftVersion]:
        v = self._versions.get(version_id)
        if v is None:
            return None
        for field, value in version_data.model_dump(exclude_unset=True).items():
            setattr(v, field, value)
        v.updated_at = utcnow()
        return v

    async def deactivate_versions(
        self, server_type: ServerType, keep_versions: List[str]
    ) -> int:
        count = 0
        keep = set(keep_versions)
        for v in self._versions.values():
            if (
                v.server_type == server_type.value
                and v.is_active
                and v.version not in keep
            ):
                v.is_active = False
                v.updated_at = utcnow()
                count += 1
        return count

    async def cleanup_old_versions(self, days_old: int = 30) -> int:
        cutoff = utcnow() - timedelta(days=days_old)
        to_delete = [
            v_id
            for v_id, v in self._versions.items()
            if (not v.is_active) and (v.updated_at is not None) and v.updated_at < cutoff
        ]
        for v_id in to_delete:
            del self._versions[v_id]
        return len(to_delete)

    # ----- Statistics -----

    async def get_version_stats(self) -> dict:
        result: dict = {}
        total_active = 0
        for v in self._versions.values():
            bucket = result.setdefault(v.server_type, {"total": 0, "active": 0})
            bucket["total"] += 1
            if v.is_active:
                bucket["active"] += 1
                total_active += 1
        result["_total"] = {
            "total": sum(b["total"] for b in result.values() if isinstance(b, dict)),
            "active": total_active,
        }
        return result

    # ----- Update log -----

    async def create_update_log(
        self, log_data: VersionUpdateLogCreate
    ) -> VersionUpdateLog:
        log = VersionUpdateLog(
            id=self._next_log_id,
            started_at=utcnow(),
            **log_data.model_dump(),
        )
        self._logs[self._next_log_id] = log
        self._next_log_id += 1
        return log

    async def complete_update_log(
        self,
        log_id: int,
        status: str,
        execution_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[VersionUpdateLog]:
        log = self._logs.get(log_id)
        if log is None:
            return None
        log.status = status
        log.completed_at = utcnow()
        log.execution_time_ms = execution_time_ms
        log.error_message = error_message
        return log

    async def update_log_counts(
        self,
        log_id: int,
        versions_added: int,
        versions_updated: int,
        versions_removed: int,
        external_api_calls: int,
    ) -> None:
        log = self._logs.get(log_id)
        if log is None:
            return
        log.versions_added = versions_added
        log.versions_updated = versions_updated
        log.versions_removed = versions_removed
        log.external_api_calls = external_api_calls

    async def get_latest_update_log(self) -> Optional[VersionUpdateLog]:
        if not self._logs:
            return None
        return max(self._logs.values(), key=lambda log: log.started_at)

    async def get_update_logs(
        self, limit: int = 10, update_type: Optional[str] = None
    ) -> List[VersionUpdateLog]:
        logs = sorted(
            self._logs.values(), key=lambda log: log.started_at, reverse=True
        )
        if update_type:
            logs = [log for log in logs if log.update_type == update_type]
        return logs[:limit]

    # ----- Sync convenience -----

    def get_all_versions(
        self, limit: Optional[int] = None
    ) -> List[MinecraftVersion]:
        versions = sorted(
            self._versions.values(),
            key=lambda v: v.updated_at or datetime.min,
            reverse=True,
        )
        if limit:
            versions = versions[:limit]
        return versions

    def get_versions_by_server_type(
        self, server_type: str
    ) -> List[MinecraftVersion]:
        return sorted(
            (v for v in self._versions.values() if v.server_type == server_type),
            key=lambda v: v.updated_at or datetime.min,
            reverse=True,
        )

    def delete_version(self, version_id: int) -> bool:
        if version_id not in self._versions:
            return False
        del self._versions[version_id]
        return True

    def find_duplicate_versions(self) -> List[tuple]:
        counts: Dict[tuple, int] = {}
        for v in self._versions.values():
            key = (v.server_type, v.version)
            counts[key] = counts.get(key, 0) + 1
        return [(st, ver, c) for (st, ver), c in counts.items() if c > 1]

    def get_versions_older_than(
        self, cutoff_date: datetime
    ) -> List[MinecraftVersion]:
        return sorted(
            (
                v
                for v in self._versions.values()
                if (v.updated_at or datetime.min) < cutoff_date
            ),
            key=lambda v: v.updated_at or datetime.min,
        )
