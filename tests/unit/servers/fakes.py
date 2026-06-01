"""In-memory fakes for the servers domain Ports.

These structurally implement the Protocols in
`app.servers.domain.ports`. They let unit tests exercise the servers
application service (introduced under PR #2 of #228) without a
database.

Mirrors `tests.unit.backups.fakes.FakeBackupRepository` /
`FakeBackupsUnitOfWork` (#227): same construction style, same
re-entry semantics, same `seed(...)` helper for arranging fixtures.
"""

from dataclasses import replace
from datetime import datetime, timezone
from types import TracebackType
from typing import Dict, List, Mapping, Optional

from app.servers.domain.entities import (
    CreateServerCommand,
    ServerEntity,
    ServerListPage,
    ServerListSpec,
    UpdateServerCommand,
)
from app.servers.models import ServerStatus, ServerType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FakeServerRepository:
    """Dict-backed `ServerRepository` for unit tests."""

    def __init__(self) -> None:
        self._records: Dict[int, ServerEntity] = {}
        self._next_id = 1

    # ----- Internal helpers -----

    def _visible(self, include_deleted: bool) -> List[ServerEntity]:
        if include_deleted:
            return list(self._records.values())
        return [r for r in self._records.values() if not r.is_deleted]

    # ----- Reads -----

    async def get(
        self, server_id: int, *, include_deleted: bool = False
    ) -> Optional[ServerEntity]:
        row = self._records.get(server_id)
        if row is None:
            return None
        if not include_deleted and row.is_deleted:
            return None
        return row

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[ServerEntity]:
        for row in self._visible(include_deleted):
            if row.name == name:
                return row
        return None

    async def list_paged(self, spec: ServerListSpec) -> ServerListPage:
        rows = self._visible(spec.include_deleted)
        if spec.owner_id is not None:
            rows = [r for r in rows if r.owner_id == spec.owner_id]
        if spec.status is not None:
            rows = [r for r in rows if r.status == spec.status]
        if spec.server_type is not None:
            rows = [r for r in rows if r.server_type == spec.server_type]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        total = len(rows)
        start = (spec.page - 1) * spec.size
        end = start + spec.size
        return ServerListPage(
            entities=rows[start:end],
            total=total,
            page=spec.page,
            size=spec.size,
        )

    async def list_by_status(
        self, status: ServerStatus, *, include_deleted: bool = False
    ) -> List[ServerEntity]:
        return [r for r in self._visible(include_deleted) if r.status == status]

    async def list_by_port(
        self,
        port: Optional[int],
        *,
        statuses: Optional[List[ServerStatus]] = None,
        exclude_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> List[ServerEntity]:
        rows = self._visible(include_deleted)
        if port is not None:
            rows = [r for r in rows if r.port == port]
        if statuses:
            rows = [r for r in rows if r.status in statuses]
        if exclude_id is not None:
            rows = [r for r in rows if r.id != exclude_id]
        return rows

    async def list_by_ids(
        self, server_ids: List[int], *, include_deleted: bool = False
    ) -> List[ServerEntity]:
        idset = set(server_ids)
        return [r for r in self._visible(include_deleted) if r.id in idset]

    async def list_by_owner(
        self, owner_id: int, *, include_deleted: bool = False
    ) -> List[ServerEntity]:
        return [r for r in self._visible(include_deleted) if r.owner_id == owner_id]

    # ----- Writes (stage-only) -----

    async def add(self, command: CreateServerCommand) -> ServerEntity:
        now = utcnow()
        entity = ServerEntity(
            id=self._next_id,
            name=command.name,
            directory_path=command.directory_path,
            minecraft_version=command.minecraft_version,
            server_type=command.server_type,
            port=command.port,
            max_memory=command.max_memory,
            max_players=command.max_players,
            owner_id=command.owner_id,
            status=ServerStatus.stopped,
            created_at=now,
            updated_at=now,
            description=command.description,
            is_deleted=False,
            owner_username=None,
        )
        self._records[self._next_id] = entity
        self._next_id += 1
        return entity

    async def update(
        self, server_id: int, command: UpdateServerCommand
    ) -> Optional[ServerEntity]:
        existing = self._records.get(server_id)
        if existing is None or existing.is_deleted:
            return None
        applied = command.applied_fields()
        if not applied:
            return existing
        updated = replace(existing, **applied, updated_at=utcnow())
        self._records[server_id] = updated
        return updated

    async def soft_delete(
        self, server_id: int, *, directory_path: Optional[str] = None
    ) -> bool:
        existing = self._records.get(server_id)
        if existing is None:
            return False
        updates: dict = dict(
            is_deleted=True,
            status=ServerStatus.stopped,
            updated_at=utcnow(),
        )
        if directory_path is not None:
            updates["directory_path"] = directory_path
        self._records[server_id] = replace(existing, **updates)
        return True

    # ----- Status writes (own-transaction in production; flat here) -----

    async def update_status(
        self, server_id: int, status: ServerStatus
    ) -> Optional[ServerEntity]:
        existing = self._records.get(server_id)
        if existing is None:
            return None
        updated = replace(existing, status=status, updated_at=utcnow())
        self._records[server_id] = updated
        return updated

    async def batch_update_statuses(
        self, updates: Mapping[int, ServerStatus]
    ) -> Mapping[int, Optional[ServerEntity]]:
        result: Dict[int, Optional[ServerEntity]] = {}
        for sid, new_status in updates.items():
            result[sid] = await self.update_status(sid, new_status)
        return result

    async def update_port(self, server_id: int, port: int) -> Optional[ServerEntity]:
        existing = self._records.get(server_id)
        if existing is None:
            return None
        updated = replace(existing, port=port, updated_at=utcnow())
        self._records[server_id] = updated
        return updated

    # ----- Test helpers -----

    def seed(self, entity: ServerEntity) -> ServerEntity:
        assert entity.id is not None
        self._records[entity.id] = entity
        self._next_id = max(self._next_id, entity.id + 1)
        return entity


class FakeServersUnitOfWork:
    """In-memory `ServersUnitOfWork` for unit tests.

    Re-uses the repository instance across enters so test setup
    carries through into the code under test. `rollback()` does NOT
    undo changes already applied to the in-memory store — assert via
    `rolled_back` / `committed` counters.
    """

    def __init__(self, servers: Optional[FakeServerRepository] = None):
        self.servers: FakeServerRepository = servers or FakeServerRepository()
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeServersUnitOfWork":
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


def make_server_entity(
    *,
    id: int,
    owner_id: int = 1,
    name: str = "srv",
    directory_path: str = "/servers/srv",
    minecraft_version: str = "1.20.1",
    server_type: ServerType = ServerType.vanilla,
    port: int = 25565,
    max_memory: int = 1024,
    max_players: int = 20,
    status: ServerStatus = ServerStatus.stopped,
    created_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
    description: Optional[str] = None,
    is_deleted: bool = False,
    owner_username: Optional[str] = None,
) -> ServerEntity:
    """Build a fully-populated `ServerEntity` for unit tests.

    Provides explicit defaults for every column so test arrange blocks
    only spell out what they care about. Mirrors
    `tests.unit.backups.fakes.make_backup_entity`.
    """
    now = utcnow()
    return ServerEntity(
        id=id,
        name=name,
        directory_path=directory_path,
        minecraft_version=minecraft_version,
        server_type=server_type,
        port=port,
        max_memory=max_memory,
        max_players=max_players,
        owner_id=owner_id,
        status=status,
        created_at=created_at or now,
        updated_at=updated_at or now,
        description=description,
        is_deleted=is_deleted,
        owner_username=owner_username,
    )


class FakeServerReadPort:
    """Dict-backed `ServerReadPort` for unit tests.

    Consolidates the previously duplicated FakeServerReadPort
    implementations from `tests/unit/backups/fakes.py` and
    `tests/unit/files/fakes.py` (Issue #168).

    Stores per-server `directory_path` and (optionally) a full
    `ServerEntity` snapshot consumed by `ServerReadPort.get`. The two
    stores are kept independent so tests that only exercise
    file-history surfaces stay terse, while groups tests can
    seed a full entity (including `owner_id`, which the groups domain
    reads to apply the "admin-or-server-owner" rule — see
    `app.groups.application.service._can_manage_server_groups`).
    """

    def __init__(
        self,
        paths: Optional[Dict[int, Optional[str]]] = None,
        servers: Optional[Dict[int, ServerEntity]] = None,
    ) -> None:
        self._paths: Dict[int, Optional[str]] = dict(paths or {})
        self._servers: Dict[int, ServerEntity] = dict(servers or {})

    async def get_directory_path(self, server_id: int) -> Optional[str]:
        if server_id in self._paths:
            return self._paths[server_id]
        s = self._servers.get(server_id)
        return s.directory_path if s else None

    async def get(self, server_id: int) -> Optional[ServerEntity]:
        return self._servers.get(server_id)

    def set_path(self, server_id: int, path: Optional[str]) -> None:
        self._paths[server_id] = path

    def set_server(self, server: ServerEntity) -> None:
        """Register a `ServerEntity` and mirror its `directory_path`."""
        self._servers[server.id] = server
        self._paths[server.id] = server.directory_path

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
        """Seed a `ServerEntity` directly (backups-style API)."""
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
        self.set_server(entity)
        return entity


__all__ = [
    "FakeServerReadPort",
    "FakeServerRepository",
    "FakeServersUnitOfWork",
    "make_server_entity",
    "utcnow",
]
