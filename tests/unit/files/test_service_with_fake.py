"""Behavioural tests for `FileHistoryService` using in-memory fakes.

Exercises the use cases without a real DB or filesystem: each test
points `history_base_dir` at `tmp_path` and lets the service write
backup files there. The fakes act as the persistence layer.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from app.core.datetime_utils import utcnow
from app.core.exceptions import (
    FileOperationException,
    InvalidRequestException,
    ServerNotFoundException,
)
from app.files.application.service import FileHistoryService
from app.files.domain.entities import FileHistoryEntity
from tests.unit.files.fakes import (
    FakeFileHistoryRepository,
    FakeFilesUnitOfWork,
    FakeServerReadPort,
)


@pytest.fixture
def repo() -> FakeFileHistoryRepository:
    return FakeFileHistoryRepository()


@pytest.fixture
def uow(repo: FakeFileHistoryRepository) -> FakeFilesUnitOfWork:
    return FakeFilesUnitOfWork(files_history=repo)


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort({1: "./servers/1"})


@pytest.fixture
def service(
    uow: FakeFilesUnitOfWork,
    server_read: FakeServerReadPort,
    tmp_path: Path,
) -> FileHistoryService:
    return FileHistoryService(
        uow=uow,
        server_read=server_read,
        history_base_dir=tmp_path / "file_history",
        max_versions_per_file=3,
        auto_cleanup_days=30,
    )


# ----- create_version_backup -----


@pytest.mark.asyncio
async def test_create_version_backup_creates_first_version(
    service: FileHistoryService, repo: FakeFileHistoryRepository, uow: FakeFilesUnitOfWork
):
    entity = await service.create_version_backup(
        server_id=1,
        file_path="server.properties",
        content="line=1\n",
        user_id=42,
        description="first",
    )

    assert entity is not None
    assert entity.version_number == 1
    assert entity.editor_user_id == 42
    assert entity.description == "first"
    # backup file written to disk
    assert Path(entity.backup_file_path).read_text() == "line=1\n"
    assert uow.committed >= 1


@pytest.mark.asyncio
async def test_create_version_backup_skips_duplicate_content(
    service: FileHistoryService, uow: FakeFilesUnitOfWork
):
    first = await service.create_version_backup(
        server_id=1, file_path="server.properties", content="x=1\n"
    )
    assert first is not None
    commits_after_first = uow.committed

    second = await service.create_version_backup(
        server_id=1, file_path="server.properties", content="x=1\n"
    )

    assert second is None
    # No new write transaction should have committed
    assert uow.committed == commits_after_first


@pytest.mark.asyncio
async def test_version_number_is_monotonic(service: FileHistoryService):
    for i in range(3):
        entity = await service.create_version_backup(
            server_id=1, file_path="x.txt", content=f"v{i}\n"
        )
        assert entity is not None
        assert entity.version_number == i + 1


@pytest.mark.asyncio
async def test_excess_versions_cleaned_up(
    service: FileHistoryService, repo: FakeFileHistoryRepository
):
    # max_versions_per_file=3 in the fixture
    for i in range(5):
        await service.create_version_backup(
            server_id=1, file_path="x.txt", content=f"v{i}\n"
        )

    remaining = await repo.get_history_for_file(1, "x.txt", limit=100)
    assert len(remaining) == 3
    # Newest three kept
    assert [r.version_number for r in remaining] == [5, 4, 3]


# ----- get_file_history / get_version_content -----


@pytest.mark.asyncio
async def test_get_file_history_returns_newest_first(
    service: FileHistoryService,
):
    for i in range(3):
        await service.create_version_backup(
            server_id=1, file_path="a.txt", content=f"v{i}\n"
        )

    history = await service.get_file_history(1, "a.txt", limit=10)
    assert [h.version_number for h in history] == [3, 2, 1]


@pytest.mark.asyncio
async def test_get_version_content_raises_when_version_missing(
    service: FileHistoryService,
):
    with pytest.raises(InvalidRequestException):
        await service.get_version_content(1, "missing.txt", 99)


@pytest.mark.asyncio
async def test_get_version_content_raises_when_backup_file_missing(
    service: FileHistoryService, repo: FakeFileHistoryRepository
):
    repo.seed(
        FileHistoryEntity(
            id=1,
            server_id=1,
            file_path="ghost.txt",
            version_number=1,
            backup_file_path="/nonexistent/path/v001.txt",
            file_size=10,
            content_hash="aaa",
            editor_user_id=None,
            editor_username=None,
            created_at=utcnow(),
            description=None,
        )
    )
    with pytest.raises(FileOperationException):
        await service.get_version_content(1, "ghost.txt", 1)


# ----- restore_from_history -----


@pytest.mark.asyncio
async def test_restore_creates_backup_of_current_then_restores(
    service: FileHistoryService,
    server_read: FakeServerReadPort,
    tmp_path: Path,
):
    server_dir = tmp_path / "server1"
    server_dir.mkdir()
    server_read.set_path(1, str(server_dir))

    # Seed: an original version exists in history
    backup_entity = await service.create_version_backup(
        server_id=1, file_path="config.txt", content="original\n"
    )
    assert backup_entity is not None

    # Live file currently has different content
    live_file = server_dir / "config.txt"
    live_file.write_text("changed\n")

    content, backup_created = await service.restore_from_history(
        server_id=1,
        file_path="config.txt",
        version_number=1,
        user_id=99,
    )

    assert content == "original\n"
    assert backup_created is True
    assert live_file.read_text() == "original\n"


@pytest.mark.asyncio
async def test_restore_raises_server_not_found_for_unknown_server(
    service: FileHistoryService, server_read: FakeServerReadPort
):
    # Seed a version so we get past get_version_content
    entity = await service.create_version_backup(
        server_id=1, file_path="a.txt", content="x\n"
    )
    assert entity is not None

    server_read.set_path(1, None)  # server no longer resolvable

    with pytest.raises(ServerNotFoundException):
        await service.restore_from_history(
            server_id=1, file_path="a.txt", version_number=1, user_id=99
        )


# ----- delete_version -----


@pytest.mark.asyncio
async def test_delete_version_removes_record_and_file(
    service: FileHistoryService, repo: FakeFileHistoryRepository
):
    entity = await service.create_version_backup(
        server_id=1, file_path="d.txt", content="bye\n"
    )
    assert entity is not None
    backup_path = Path(entity.backup_file_path)
    assert backup_path.exists()

    ok = await service.delete_version(1, "d.txt", 1)
    assert ok is True
    assert not backup_path.exists()
    assert await repo.get_version(1, "d.txt", 1) is None


@pytest.mark.asyncio
async def test_delete_version_raises_when_missing(service: FileHistoryService):
    with pytest.raises(InvalidRequestException):
        await service.delete_version(1, "missing.txt", 1)


# ----- get_server_statistics -----


@pytest.mark.asyncio
async def test_statistics_rollup(service: FileHistoryService):
    await service.create_version_backup(server_id=1, file_path="a.txt", content="a1\n")
    await service.create_version_backup(server_id=1, file_path="a.txt", content="a2\n")
    await service.create_version_backup(server_id=1, file_path="b.txt", content="b1\n")

    stats = await service.get_server_statistics(1)

    assert stats.server_id == 1
    assert stats.total_files_with_history == 2
    assert stats.total_versions == 3
    assert stats.total_storage_used > 0
    assert stats.most_edited_file == "a.txt"
    assert stats.most_edited_file_versions == 2


# ----- cleanup_old_versions -----


@pytest.mark.asyncio
async def test_cleanup_old_versions_by_age(
    service: FileHistoryService,
    repo: FakeFileHistoryRepository,
    tmp_path: Path,
):
    # Create a backup, then back-date it past the cutoff
    entity = await service.create_version_backup(
        server_id=1, file_path="old.txt", content="old\n"
    )
    assert entity is not None and entity.id is not None
    backup_path = Path(entity.backup_file_path)
    assert backup_path.exists()
    repo.replace_record(entity.id, created_at=utcnow() - timedelta(days=60))

    result = await service.cleanup_old_versions(days=30, server_id=1)

    assert result.deleted_versions == 1
    assert result.freed_storage > 0
    assert not backup_path.exists()


@pytest.mark.asyncio
async def test_cleanup_old_versions_keeps_recent(
    service: FileHistoryService,
):
    await service.create_version_backup(
        server_id=1, file_path="recent.txt", content="new\n"
    )
    result = await service.cleanup_old_versions(days=30, server_id=1)
    assert result.deleted_versions == 0
    assert result.freed_storage == 0
