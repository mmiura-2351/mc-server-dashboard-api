"""Port (Protocol) definitions for the files domain.

Per `docs/ARCHITECTURE.md` §4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types crossing
these Protocols are pure domain entities defined in `entities.py`.

Two Ports are defined:
- `FileHistoryRepository`: persistence Port for file edit history.
- `FilesUnitOfWork`: transactional boundary Port. Application code wraps
  a set of Repository calls in `async with uow:` and calls
  `await uow.commit()` to finalize. Concrete adapters drive the
  SQLAlchemy session lifecycle.
"""

from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol

from app.files.domain.entities import (
    CreateHistoryCommand,
    FileHistoryEntity,
    FileHistoryStatsEntity,
)


class FileHistoryRepository(Protocol):
    """Persistence port for file edit history.

    Concrete implementations: `SqlAlchemyFileHistoryRepository`
    (production), `FakeFileHistoryRepository` (unit tests).

    Repository methods **do not commit**. Wrap calls in a
    `FilesUnitOfWork` context and call `await uow.commit()` once you
    are done.
    """

    # ----- Reads -----

    async def get_history_for_file(
        self, server_id: int, file_path: str, limit: int
    ) -> List[FileHistoryEntity]: ...

    async def get_version(
        self, server_id: int, file_path: str, version_number: int
    ) -> Optional[FileHistoryEntity]: ...

    async def get_latest(
        self, server_id: int, file_path: str
    ) -> Optional[FileHistoryEntity]: ...

    async def get_max_version_number(self, server_id: int, file_path: str) -> int: ...

    async def reserve_next_version_number(self, server_id: int, file_path: str) -> int:
        """Compute the next available `version_number` for the given
        (server_id, file_path).

        Callers MUST use this inside an active `FilesUnitOfWork`
        transaction. The returned value is race-free at the time of
        CALL, but the surrounding UoW commit may still raise
        `IntegrityError` if a concurrent writer reserves the same
        number first — the UNIQUE constraint
        `uq_file_edit_history_server_path_version` is the final guard.

        Application code is expected to catch that `IntegrityError`
        and retry. See `FileHistoryService.create_version_backup`
        for the canonical retry pattern.
        """
        ...

    async def get_excess_versions(
        self, server_id: int, file_path: str, keep: int
    ) -> List[FileHistoryEntity]: ...

    async def get_versions_older_than(
        self, cutoff: datetime, server_id: Optional[int] = None
    ) -> List[FileHistoryEntity]: ...

    async def get_server_statistics(self, server_id: int) -> FileHistoryStatsEntity: ...

    # ----- Writes -----

    async def add(self, command: CreateHistoryCommand) -> FileHistoryEntity: ...

    async def delete_by_id(self, record_id: int) -> bool: ...


class FilesUnitOfWork(Protocol):
    """Transactional boundary Port for the files domain.

    Application services enter a UoW context, perform repository
    operations through the same session, then call `commit()` to
    persist atomically. Exiting the context without committing rolls
    back.
    """

    files_history: FileHistoryRepository

    async def __aenter__(self) -> "FilesUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
