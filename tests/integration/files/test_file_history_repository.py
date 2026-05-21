"""Integration tests for `SqlAlchemyFileHistoryRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not** commit
on its own (the UoW owns transactions in production), so write-path
tests call `db.commit()` explicitly after staging changes.
"""

from datetime import timedelta

import pytest

from app.core.datetime_utils import utcnow
from app.files.adapters.repository import SqlAlchemyFileHistoryRepository
from app.files.domain.entities import CreateHistoryCommand
from app.files.models import FileEditHistory
from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import User


@pytest.fixture
def server(db, admin_user) -> Server:
    s = Server(
        name="History Test Server",
        description="for file-history tests",
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        status=ServerStatus.stopped,
        directory_path="./servers/hist",
        port=25600,
        max_memory=1024,
        max_players=20,
        owner_id=admin_user.id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture
def repository(db) -> SqlAlchemyFileHistoryRepository:
    return SqlAlchemyFileHistoryRepository(db)


def _seed_history(
    db,
    server: Server,
    user: User,
    file_path: str,
    versions: int,
    created_offsets_days: list[int] | None = None,
) -> list[FileEditHistory]:
    """Insert `versions` rows for the same file. created_offsets_days
    optionally back-dates each row by N days from now."""
    rows: list[FileEditHistory] = []
    offsets = created_offsets_days or [0] * versions
    for i in range(versions):
        row = FileEditHistory(
            server_id=server.id,
            file_path=file_path,
            version_number=i + 1,
            backup_file_path=f"/tmp/file_history/{server.id}/{file_path}/v{i + 1:03d}.dat",
            file_size=100 * (i + 1),
            content_hash=f"hash-{i + 1}",
            editor_user_id=user.id,
            description=f"v{i + 1}",
            created_at=utcnow() - timedelta(days=offsets[i]),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


class TestFileHistoryRepository:
    # ----- Reads -----

    @pytest.mark.asyncio
    async def test_get_history_for_file_orders_newest_first(
        self, repository, db, server, admin_user
    ):
        _seed_history(db, server, admin_user, "server.properties", versions=3)

        history = await repository.get_history_for_file(
            server.id, "server.properties", limit=10
        )
        assert [h.version_number for h in history] == [3, 2, 1]
        # editor_username eagerly resolved
        assert all(h.editor_username == admin_user.username for h in history)

    @pytest.mark.asyncio
    async def test_get_history_respects_limit(self, repository, db, server, admin_user):
        _seed_history(db, server, admin_user, "x.txt", versions=5)
        history = await repository.get_history_for_file(server.id, "x.txt", limit=2)
        assert len(history) == 2
        assert [h.version_number for h in history] == [5, 4]

    @pytest.mark.asyncio
    async def test_get_version_returns_match(self, repository, db, server, admin_user):
        _seed_history(db, server, admin_user, "y.txt", versions=3)
        got = await repository.get_version(server.id, "y.txt", 2)
        assert got is not None
        assert got.version_number == 2

    @pytest.mark.asyncio
    async def test_get_version_returns_none_when_missing(
        self, repository, db, server, admin_user
    ):
        _seed_history(db, server, admin_user, "y.txt", versions=1)
        assert await repository.get_version(server.id, "y.txt", 99) is None

    @pytest.mark.asyncio
    async def test_get_latest_returns_highest_version(
        self, repository, db, server, admin_user
    ):
        _seed_history(db, server, admin_user, "z.txt", versions=4)
        latest = await repository.get_latest(server.id, "z.txt")
        assert latest is not None
        assert latest.version_number == 4

    @pytest.mark.asyncio
    async def test_get_latest_returns_none_for_unknown_file(self, repository, server):
        assert await repository.get_latest(server.id, "never.txt") is None

    @pytest.mark.asyncio
    async def test_get_max_version_number(self, repository, db, server, admin_user):
        _seed_history(db, server, admin_user, "max.txt", versions=7)
        assert await repository.get_max_version_number(server.id, "max.txt") == 7
        assert await repository.get_max_version_number(server.id, "no.txt") == 0

    @pytest.mark.asyncio
    async def test_get_excess_versions(self, repository, db, server, admin_user):
        _seed_history(db, server, admin_user, "e.txt", versions=5)
        excess = await repository.get_excess_versions(server.id, "e.txt", keep=3)
        # Newest 3 are versions 5,4,3; excess are 2 and 1
        assert [e.version_number for e in excess] == [2, 1]

    @pytest.mark.asyncio
    async def test_get_versions_older_than(self, repository, db, server, admin_user):
        _seed_history(
            db,
            server,
            admin_user,
            "age.txt",
            versions=3,
            created_offsets_days=[60, 10, 0],
        )
        cutoff = utcnow() - timedelta(days=30)
        old = await repository.get_versions_older_than(cutoff)
        assert len(old) == 1
        assert old[0].version_number == 1  # the 60-day-old one

    @pytest.mark.asyncio
    async def test_get_versions_older_than_filtered_by_server(
        self, repository, db, server, admin_user
    ):
        _seed_history(
            db,
            server,
            admin_user,
            "f.txt",
            versions=2,
            created_offsets_days=[60, 60],
        )
        cutoff = utcnow() - timedelta(days=30)
        same = await repository.get_versions_older_than(cutoff, server_id=server.id)
        other = await repository.get_versions_older_than(cutoff, server_id=99999)
        assert len(same) == 2
        assert other == []

    @pytest.mark.asyncio
    async def test_get_server_statistics(self, repository, db, server, admin_user):
        _seed_history(db, server, admin_user, "a.txt", versions=3)
        _seed_history(db, server, admin_user, "b.txt", versions=2)

        stats = await repository.get_server_statistics(server.id)
        assert stats.server_id == server.id
        assert stats.total_versions == 5
        assert stats.total_files_with_history == 2
        assert stats.total_storage_used > 0
        assert stats.most_edited_file == "a.txt"
        assert stats.most_edited_file_versions == 3
        assert stats.oldest_version_date is not None

    @pytest.mark.asyncio
    async def test_get_server_statistics_empty(self, repository, server):
        stats = await repository.get_server_statistics(server.id)
        assert stats.total_versions == 0
        assert stats.total_files_with_history == 0
        assert stats.total_storage_used == 0
        assert stats.most_edited_file is None
        assert stats.most_edited_file_versions is None
        assert stats.oldest_version_date is None

    # ----- Writes -----

    @pytest.mark.asyncio
    async def test_add_persists_record_and_resolves_editor(
        self, repository, db, server, admin_user
    ):
        command = CreateHistoryCommand(
            server_id=server.id,
            file_path="new.txt",
            version_number=1,
            backup_file_path="/tmp/file_history/x/v001.dat",
            file_size=42,
            content_hash="aaa",
            editor_user_id=admin_user.id,
            description="initial",
        )
        entity = await repository.add(command)
        db.commit()

        assert entity.id is not None
        assert entity.editor_username == admin_user.username
        assert entity.description == "initial"

        # Verify persisted
        persisted = (
            db.query(FileEditHistory).filter(FileEditHistory.id == entity.id).first()
        )
        assert persisted is not None
        assert persisted.file_path == "new.txt"

    @pytest.mark.asyncio
    async def test_add_with_no_editor(self, repository, db, server):
        command = CreateHistoryCommand(
            server_id=server.id,
            file_path="anon.txt",
            version_number=1,
            backup_file_path="/tmp/anon/v001.dat",
            file_size=1,
            content_hash=None,
            editor_user_id=None,
            description=None,
        )
        entity = await repository.add(command)
        db.commit()
        assert entity.editor_user_id is None
        assert entity.editor_username is None

    @pytest.mark.asyncio
    async def test_delete_by_id_removes_row(self, repository, db, server, admin_user):
        [row] = _seed_history(db, server, admin_user, "del.txt", versions=1)
        ok = await repository.delete_by_id(row.id)
        db.commit()
        assert ok is True
        assert (
            db.query(FileEditHistory).filter(FileEditHistory.id == row.id).first() is None
        )

    @pytest.mark.asyncio
    async def test_delete_by_id_returns_false_when_missing(self, repository):
        assert await repository.delete_by_id(999999) is False
