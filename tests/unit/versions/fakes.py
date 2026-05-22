"""In-memory fakes for the versions domain Ports.

`FakeVersionRepository` and `FakeUnitOfWork` structurally implement the
Protocols in `app.versions.domain.ports`. They let unit tests exercise
application services without a database — replacing
`MagicMock().query().filter().first()` chains entirely.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from types import TracebackType
from typing import Dict, List, Optional

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


class FakeVersionRepository:
    """Dict-backed `VersionRepository` for unit tests."""

    def __init__(self) -> None:
        self._versions: Dict[int, MinecraftVersionEntity] = {}
        self._logs: Dict[int, VersionUpdateLogEntity] = {}
        self._next_version_id = 1
        self._next_log_id = 1

    # ----- internal helpers -----

    def _put_version(self, entity: MinecraftVersionEntity) -> MinecraftVersionEntity:
        assert entity.id is not None
        self._versions[entity.id] = entity
        return entity

    def _put_log(self, entity: VersionUpdateLogEntity) -> VersionUpdateLogEntity:
        assert entity.id is not None
        self._logs[entity.id] = entity
        return entity

    # ----- Version reads -----

    async def get_all_active_versions(self) -> List[MinecraftVersionEntity]:
        return sorted(
            (v for v in self._versions.values() if v.is_active),
            key=lambda v: (v.server_type.value, v.version),
        )

    async def get_versions_by_type(
        self, server_type: ServerType
    ) -> List[MinecraftVersionEntity]:
        return sorted(
            (
                v
                for v in self._versions.values()
                if v.server_type == server_type and v.is_active
            ),
            key=lambda v: v.version,
            reverse=True,
        )

    async def get_version_by_type_and_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersionEntity]:
        for v in self._versions.values():
            if v.server_type == server_type and v.version == version:
                return v
        return None

    # ----- Version writes -----

    async def create_version(
        self, command: CreateVersionCommand
    ) -> MinecraftVersionEntity:
        now = utcnow()
        entity = MinecraftVersionEntity(
            id=self._next_version_id,
            server_type=command.server_type,
            version=command.version,
            download_url=command.download_url,
            release_date=command.release_date,
            is_stable=command.is_stable,
            build_number=command.build_number,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._next_version_id += 1
        return self._put_version(entity)

    async def upsert_version(
        self, command: CreateVersionCommand
    ) -> MinecraftVersionEntity:
        existing = await self.get_version_by_type_and_version(
            command.server_type, command.version
        )
        if existing is not None:
            updated = replace(
                existing,
                download_url=command.download_url,
                release_date=command.release_date,
                is_stable=command.is_stable,
                build_number=command.build_number,
                is_active=True,
                updated_at=utcnow(),
            )
            return self._put_version(updated)
        return await self.create_version(command)

    async def update_version(
        self, version_id: int, command: UpdateVersionCommand
    ) -> Optional[MinecraftVersionEntity]:
        existing = self._versions.get(version_id)
        if existing is None:
            return None
        updated = replace(existing, **command.applied_fields(), updated_at=utcnow())
        return self._put_version(updated)

    async def deactivate_versions(
        self, server_type: ServerType, keep_versions: List[str]
    ) -> int:
        keep = set(keep_versions)
        count = 0
        for v_id, v in list(self._versions.items()):
            if v.server_type == server_type and v.is_active and v.version not in keep:
                self._versions[v_id] = replace(v, is_active=False, updated_at=utcnow())
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

    async def get_version_stats(self) -> VersionStatsEntity:
        by_type: Dict[str, Dict[str, int]] = {}
        total_total = 0
        total_active = 0
        for v in self._versions.values():
            bucket = by_type.setdefault(v.server_type.value, {"total": 0, "active": 0})
            bucket["total"] += 1
            total_total += 1
            if v.is_active:
                bucket["active"] += 1
                total_active += 1
        return VersionStatsEntity(
            total_versions=total_total,
            active_versions=total_active,
            by_server_type=by_type,
        )

    # ----- Update log -----

    async def create_update_log(
        self, command: CreateUpdateLogCommand
    ) -> VersionUpdateLogEntity:
        log = VersionUpdateLogEntity(
            id=self._next_log_id,
            update_type=command.update_type,
            status=command.status,
            server_type=command.server_type,
            executed_by_user_id=command.executed_by_user_id,
            started_at=utcnow(),
        )
        self._next_log_id += 1
        return self._put_log(log)

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
        existing = self._logs.get(log_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            status=status,
            completed_at=utcnow(),
            execution_time_ms=execution_time_ms,
            error_message=error_message,
            versions_added=versions_added,
            versions_updated=versions_updated,
            versions_removed=versions_removed,
            external_api_calls=external_api_calls,
        )
        return self._put_log(updated)

    async def get_latest_update_log(self) -> Optional[VersionUpdateLogEntity]:
        if not self._logs:
            return None
        return max(self._logs.values(), key=lambda log: log.started_at or datetime.min)

    async def get_update_logs(
        self, limit: int = 10, update_type: Optional[str] = None
    ) -> List[VersionUpdateLogEntity]:
        logs = sorted(
            self._logs.values(),
            key=lambda log: log.started_at or datetime.min,
            reverse=True,
        )
        if update_type:
            logs = [log for log in logs if log.update_type == update_type]
        return logs[:limit]

    # ----- Sync convenience -----

    def get_all_versions(
        self, limit: Optional[int] = None
    ) -> List[MinecraftVersionEntity]:
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
    ) -> List[MinecraftVersionEntity]:
        return sorted(
            (v for v in self._versions.values() if v.server_type.value == server_type),
            key=lambda v: v.updated_at or datetime.min,
            reverse=True,
        )

    def delete_version(self, version_id: int) -> bool:
        if version_id not in self._versions:
            return False
        del self._versions[version_id]
        return True

    def find_duplicate_versions(self) -> List[DuplicateVersionEntity]:
        counts: Dict[tuple, int] = {}
        for v in self._versions.values():
            key = (v.server_type.value, v.version)
            counts[key] = counts.get(key, 0) + 1
        return [
            DuplicateVersionEntity(server_type=st, version=ver, count=c)
            for (st, ver), c in counts.items()
            if c > 1
        ]

    def get_versions_older_than(
        self, cutoff_date: datetime
    ) -> List[MinecraftVersionEntity]:
        return sorted(
            (
                v
                for v in self._versions.values()
                if (v.updated_at or datetime.min) < cutoff_date
            ),
            key=lambda v: v.updated_at or datetime.min,
        )


class FakeUnitOfWork:
    """In-memory `UnitOfWork` for unit tests.

    Re-uses a single `FakeVersionRepository` instance across enters so
    test setup (priming the repo with data) carries through into the
    code-under-test. `commit` and `rollback` are tracked as call counts
    for assertions.

    **Caveat (see PR #229 review item 9)**: `rollback()` does **not**
    actually undo changes made to the in-memory store. The Fake's reads
    and writes mutate the same `FakeVersionRepository` dictionaries
    irrespective of the surrounding transaction. Tests of exception
    paths therefore cannot rely on "the bad write disappeared after
    rollback" — they should instead assert on the `rolled_back` counter
    and/or use a hand-snapshotted state for before/after comparisons.
    """

    def __init__(self, versions: Optional[FakeVersionRepository] = None) -> None:
        self.versions: FakeVersionRepository = versions or FakeVersionRepository()
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
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
        """Increment the rollback counter. Does NOT rewind state — see class docstring."""
        self.rolled_back += 1
