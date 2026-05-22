"""In-memory fakes for the files domain Ports.

`FakeFileHistoryRepository`, `FakeFilesUnitOfWork`, and
`FakeServerReadPort` structurally implement the Protocols in
`app.files.domain.ports` and `app.servers.domain.ports`. They let unit
tests exercise the file-history application service without a database.
"""

from dataclasses import replace
from datetime import datetime
from types import TracebackType
from typing import Dict, List, Optional, Tuple

from app.core.datetime_utils import utcnow
from app.files.domain.entities import (
    CreateHistoryCommand,
    FileHistoryEntity,
    FileHistoryStatsEntity,
)


class FakeFileHistoryRepository:
    """Dict-backed `FileHistoryRepository` for unit tests."""

    def __init__(self) -> None:
        self._records: Dict[int, FileHistoryEntity] = {}
        self._next_id = 1

    # ----- internal helpers -----

    def _key(self, e: FileHistoryEntity) -> Tuple[int, str, int]:
        return (e.server_id, e.file_path, e.version_number)

    # ----- Reads -----

    async def get_history_for_file(
        self, server_id: int, file_path: str, limit: int
    ) -> List[FileHistoryEntity]:
        matches = [
            e
            for e in self._records.values()
            if e.server_id == server_id and e.file_path == file_path
        ]
        matches.sort(key=lambda e: e.version_number, reverse=True)
        return matches[:limit]

    async def get_version(
        self, server_id: int, file_path: str, version_number: int
    ) -> Optional[FileHistoryEntity]:
        for e in self._records.values():
            if (
                e.server_id == server_id
                and e.file_path == file_path
                and e.version_number == version_number
            ):
                return e
        return None

    async def get_latest(
        self, server_id: int, file_path: str
    ) -> Optional[FileHistoryEntity]:
        matches = [
            e
            for e in self._records.values()
            if e.server_id == server_id and e.file_path == file_path
        ]
        if not matches:
            return None
        return max(matches, key=lambda e: e.version_number)

    async def get_max_version_number(self, server_id: int, file_path: str) -> int:
        latest = await self.get_latest(server_id, file_path)
        return latest.version_number if latest else 0

    async def reserve_next_version_number(self, server_id: int, file_path: str) -> int:
        """Mirror the SQL adapter's `MAX + 1` semantics in-memory."""
        return await self.get_max_version_number(server_id, file_path) + 1

    async def get_excess_versions(
        self, server_id: int, file_path: str, keep: int
    ) -> List[FileHistoryEntity]:
        matches = [
            e
            for e in self._records.values()
            if e.server_id == server_id and e.file_path == file_path
        ]
        matches.sort(key=lambda e: e.version_number, reverse=True)
        return matches[keep:]

    async def get_versions_older_than(
        self, cutoff: datetime, server_id: Optional[int] = None
    ) -> List[FileHistoryEntity]:
        results = [e for e in self._records.values() if e.created_at < cutoff]
        if server_id is not None:
            results = [e for e in results if e.server_id == server_id]
        return results

    async def get_server_statistics(self, server_id: int) -> FileHistoryStatsEntity:
        matches = [e for e in self._records.values() if e.server_id == server_id]
        if not matches:
            return FileHistoryStatsEntity(
                server_id=server_id,
                total_files_with_history=0,
                total_versions=0,
                total_storage_used=0,
                oldest_version_date=None,
                most_edited_file=None,
                most_edited_file_versions=None,
            )

        file_counts: Dict[str, int] = {}
        for e in matches:
            file_counts[e.file_path] = file_counts.get(e.file_path, 0) + 1
        most_edited_file = max(file_counts, key=lambda k: file_counts[k])

        return FileHistoryStatsEntity(
            server_id=server_id,
            total_files_with_history=len(file_counts),
            total_versions=len(matches),
            total_storage_used=sum(e.file_size for e in matches),
            oldest_version_date=min(e.created_at for e in matches),
            most_edited_file=most_edited_file,
            most_edited_file_versions=file_counts[most_edited_file],
        )

    # ----- Writes -----

    async def add(self, command: CreateHistoryCommand) -> FileHistoryEntity:
        entity = FileHistoryEntity(
            id=self._next_id,
            server_id=command.server_id,
            file_path=command.file_path,
            version_number=command.version_number,
            backup_file_path=command.backup_file_path,
            file_size=command.file_size,
            content_hash=command.content_hash,
            editor_user_id=command.editor_user_id,
            editor_username=None,
            created_at=utcnow(),
            description=command.description,
        )
        self._records[self._next_id] = entity
        self._next_id += 1
        return entity

    async def delete_by_id(self, record_id: int) -> bool:
        if record_id not in self._records:
            return False
        del self._records[record_id]
        return True

    # ----- Test helpers -----

    def seed(self, entity: FileHistoryEntity) -> FileHistoryEntity:
        """Insert a fully-formed entity (with id) for test fixtures."""
        assert entity.id is not None
        self._records[entity.id] = entity
        self._next_id = max(self._next_id, entity.id + 1)
        return entity

    def replace_record(self, record_id: int, **changes) -> FileHistoryEntity:
        """Mutate a seeded entity (frozen dataclass)."""
        existing = self._records[record_id]
        updated = replace(existing, **changes)
        self._records[record_id] = updated
        return updated


class FakeFilesUnitOfWork:
    """In-memory `FilesUnitOfWork` for unit tests.

    Re-uses a single `FakeFileHistoryRepository` instance across enters
    so test setup carries through into the code under test.

    **Caveat**: `rollback()` does NOT actually undo changes made to the
    in-memory store — assert on the `rolled_back` counter or use
    hand-snapshotted state for before/after comparisons. (Same pattern
    as `tests.unit.versions.fakes.FakeUnitOfWork`.)
    """

    def __init__(self, files_history: Optional[FakeFileHistoryRepository] = None) -> None:
        self.files_history: FakeFileHistoryRepository = (
            files_history or FakeFileHistoryRepository()
        )
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeFilesUnitOfWork":
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


# `FakeServerReadPort` is consolidated in `tests.unit.servers.fakes`
# (#168). Re-exported here so existing imports keep working.
from tests.unit.servers.fakes import FakeServerReadPort  # noqa: E402,F401
