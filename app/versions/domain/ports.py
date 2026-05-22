"""Port (Protocol) definitions for the versions domain.

Per `docs/ARCHITECTURE.md` §4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types crossing
these Protocols are pure domain entities defined in `entities.py`.

Two Ports are defined:
- `VersionRepository`: persistence Port for versions and update logs.
- `UnitOfWork`: transactional boundary Port. Application code wraps a set
  of Repository calls in `async with uow:` and calls `await uow.commit()`
  to finalize. Concrete adapters drive the SQLAlchemy session lifecycle.
"""

from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol

from app.servers.domain.value_objects import ServerType
from app.versions.domain.entities import (
    CreateUpdateLogCommand,
    CreateVersionCommand,
    DuplicateVersionEntity,
    MinecraftVersionEntity,
    UpdateVersionCommand,
    VersionStatsEntity,
    VersionUpdateLogEntity,
)


class VersionRepository(Protocol):
    """Persistence port for Minecraft version data.

    Concrete implementations: `SqlAlchemyVersionRepository` (production),
    `FakeVersionRepository` (unit tests).

    Repository methods **do not commit**. Wrap calls in a `UnitOfWork`
    context and call `await uow.commit()` once you are done.
    """

    # ----- Version reads -----

    async def get_all_active_versions(self) -> List[MinecraftVersionEntity]: ...

    async def get_versions_by_type(
        self, server_type: ServerType
    ) -> List[MinecraftVersionEntity]: ...

    async def get_version_by_type_and_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersionEntity]: ...

    # ----- Version writes -----

    async def create_version(
        self, command: CreateVersionCommand
    ) -> MinecraftVersionEntity: ...

    async def upsert_version(
        self, command: CreateVersionCommand
    ) -> MinecraftVersionEntity: ...

    async def update_version(
        self, version_id: int, command: UpdateVersionCommand
    ) -> Optional[MinecraftVersionEntity]: ...

    async def deactivate_versions(
        self, server_type: ServerType, keep_versions: List[str]
    ) -> int: ...

    async def cleanup_old_versions(self, days_old: int = 30) -> int: ...

    # ----- Statistics -----

    async def get_version_stats(self) -> VersionStatsEntity: ...

    # ----- Update log -----

    async def create_update_log(
        self, command: CreateUpdateLogCommand
    ) -> VersionUpdateLogEntity: ...

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
    ) -> Optional[VersionUpdateLogEntity]: ...

    async def get_latest_update_log(self) -> Optional[VersionUpdateLogEntity]: ...

    async def get_update_logs(
        self, limit: int = 10, update_type: Optional[str] = None
    ) -> List[VersionUpdateLogEntity]: ...

    # ----- Sync convenience for management/CLI -----

    def get_all_versions(
        self, limit: Optional[int] = None
    ) -> List[MinecraftVersionEntity]: ...

    def get_versions_by_server_type(
        self, server_type: str
    ) -> List[MinecraftVersionEntity]: ...

    def delete_version(self, version_id: int) -> bool: ...

    def find_duplicate_versions(self) -> List[DuplicateVersionEntity]: ...

    def get_versions_older_than(
        self, cutoff_date: datetime
    ) -> List[MinecraftVersionEntity]: ...


class UnitOfWork(Protocol):
    """Transactional boundary Port.

    Application services enter a UoW context, perform repository
    operations through the same session, then call `commit()` to persist
    atomically. Exiting the context without committing rolls back.
    """

    versions: VersionRepository

    async def __aenter__(self) -> "UnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
