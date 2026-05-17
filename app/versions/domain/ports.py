"""Port (Protocol) definitions for the versions domain.

These Protocols describe the interface that the application layer depends on.
Concrete implementations live in `app/versions/adapters/`.
"""

from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable

from app.servers.models import ServerType
from app.versions.models import MinecraftVersion, VersionUpdateLog
from app.versions.schemas import (
    MinecraftVersionCreate,
    MinecraftVersionUpdate,
    VersionUpdateLogCreate,
)


@runtime_checkable
class VersionRepository(Protocol):
    """Persistence port for Minecraft version data.

    Implementations: `SqlAlchemyVersionRepository` (production),
    `FakeVersionRepository` (unit tests).
    """

    # ----- Version CRUD -----

    async def get_all_active_versions(self) -> List[MinecraftVersion]: ...

    async def get_versions_by_type(
        self, server_type: ServerType
    ) -> List[MinecraftVersion]: ...

    async def get_version_by_type_and_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersion]: ...

    async def create_version(
        self, version_data: MinecraftVersionCreate
    ) -> MinecraftVersion: ...

    async def upsert_version(
        self, version_data: MinecraftVersionCreate
    ) -> MinecraftVersion: ...

    async def update_version(
        self, version_id: int, version_data: MinecraftVersionUpdate
    ) -> Optional[MinecraftVersion]: ...

    async def deactivate_versions(
        self, server_type: ServerType, keep_versions: List[str]
    ) -> int: ...

    async def cleanup_old_versions(self, days_old: int = 30) -> int: ...

    # ----- Statistics -----

    async def get_version_stats(self) -> dict: ...

    # ----- Update log -----

    async def create_update_log(
        self, log_data: VersionUpdateLogCreate
    ) -> VersionUpdateLog: ...

    async def complete_update_log(
        self,
        log_id: int,
        status: str,
        execution_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[VersionUpdateLog]: ...

    async def update_log_counts(
        self,
        log_id: int,
        versions_added: int,
        versions_updated: int,
        versions_removed: int,
        external_api_calls: int,
    ) -> None: ...

    async def get_latest_update_log(self) -> Optional[VersionUpdateLog]: ...

    async def get_update_logs(
        self, limit: int = 10, update_type: Optional[str] = None
    ) -> List[VersionUpdateLog]: ...

    # ----- Sync convenience (management/CLI) -----

    def get_all_versions(self, limit: Optional[int] = None) -> List[MinecraftVersion]: ...

    def get_versions_by_server_type(self, server_type: str) -> List[MinecraftVersion]: ...

    def delete_version(self, version_id: int) -> bool: ...

    def find_duplicate_versions(self) -> List[tuple]: ...

    def get_versions_older_than(
        self, cutoff_date: datetime
    ) -> List[MinecraftVersion]: ...
