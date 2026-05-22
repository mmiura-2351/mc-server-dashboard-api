"""Integration tests for `SqlAlchemyBackupRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not** commit
on its own (the UoW owns transactions in production), so write-path
tests call `db.commit()` explicitly after staging changes.
"""

import pytest
from sqlalchemy import inspect

from app.backups.adapters.repository import SqlAlchemyBackupRepository
from app.backups.domain.entities import (
    BackupListSpec,
    CreateBackupCommand,
    UpdateBackupFileCommand,
)
from app.backups.models import Backup, BackupStatus, BackupType
from app.servers.models import Server, ServerType


@pytest.fixture
def repository(db) -> SqlAlchemyBackupRepository:
    return SqlAlchemyBackupRepository(db)


def _seed_server(db, owner_id: int, *, name: str = "srv", port: int = 25565) -> Server:
    row = Server(
        name=name,
        description=None,
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=port,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
        directory_path=f"/servers/{name}",
        is_deleted=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_backup(
    db,
    server_id: int,
    *,
    name: str = "b",
    file_size: int = 0,
    status: BackupStatus = BackupStatus.creating,
    backup_type: BackupType = BackupType.manual,
    file_path: str = "",
) -> Backup:
    row = Backup(
        server_id=server_id,
        name=name,
        description=None,
        file_path=file_path,
        file_size=file_size,
        backup_type=backup_type,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestBackupRepositoryReads:
    @pytest.mark.asyncio
    async def test_get_returns_entity_with_server_eager_loaded(
        self, repository, db, admin_user
    ):
        server = _seed_server(db, admin_user.id, name="A", port=25566)
        row = _seed_backup(db, server.id, name="B1")

        entity = await repository.get(row.id)
        assert entity is not None
        assert entity.name == "B1"
        assert entity.server_id == server.id
        # joinedload should populate server fields
        assert entity.server_name == "A"
        assert entity.minecraft_version == "1.20.1"

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self, repository):
        assert await repository.get(99999) is None

    @pytest.mark.asyncio
    async def test_list_paged_filters_by_server(self, repository, db, admin_user):
        s1 = _seed_server(db, admin_user.id, name="L1", port=25567)
        s2 = _seed_server(db, admin_user.id, name="L2", port=25568)
        _seed_backup(db, s1.id, name="b-s1-a")
        _seed_backup(db, s1.id, name="b-s1-b")
        _seed_backup(db, s2.id, name="b-s2")

        page = await repository.list_paged(
            BackupListSpec(server_id=s1.id, page=1, size=10)
        )
        assert page.total == 2
        assert {e.name for e in page.entities} == {"b-s1-a", "b-s1-b"}

    @pytest.mark.asyncio
    async def test_list_paged_filters_by_type_and_status(
        self, repository, db, admin_user
    ):
        server = _seed_server(db, admin_user.id, name="LT", port=25569)
        _seed_backup(
            db,
            server.id,
            name="manual-done",
            backup_type=BackupType.manual,
            status=BackupStatus.completed,
        )
        _seed_backup(
            db,
            server.id,
            name="sched-done",
            backup_type=BackupType.scheduled,
            status=BackupStatus.completed,
        )
        _seed_backup(
            db,
            server.id,
            name="manual-fail",
            backup_type=BackupType.manual,
            status=BackupStatus.failed,
        )

        page = await repository.list_paged(
            BackupListSpec(
                server_id=server.id,
                backup_type=BackupType.manual,
                status=BackupStatus.completed,
            )
        )
        assert page.total == 1
        assert page.entities[0].name == "manual-done"

    @pytest.mark.asyncio
    async def test_list_paged_pagination(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="LP", port=25570)
        for i in range(5):
            _seed_backup(db, server.id, name=f"b{i}")

        page1 = await repository.list_paged(
            BackupListSpec(server_id=server.id, page=1, size=2)
        )
        assert page1.total == 5
        assert len(page1.entities) == 2
        page3 = await repository.list_paged(
            BackupListSpec(server_id=server.id, page=3, size=2)
        )
        assert len(page3.entities) == 1

    @pytest.mark.asyncio
    async def test_get_statistics_aggregates(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="ST", port=25571)
        _seed_backup(
            db, server.id, name="c1", file_size=100, status=BackupStatus.completed
        )
        _seed_backup(
            db, server.id, name="c2", file_size=200, status=BackupStatus.completed
        )
        _seed_backup(db, server.id, name="f1", file_size=50, status=BackupStatus.failed)

        stats = await repository.get_statistics(server_id=server.id)
        assert stats.total_backups == 3
        assert stats.completed_backups == 2
        assert stats.failed_backups == 1
        assert stats.total_size_bytes == 300


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


class TestBackupRepositoryWrites:
    @pytest.mark.asyncio
    async def test_add_inserts_row(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="W1", port=25572)

        entity = await repository.add(
            CreateBackupCommand(
                server_id=server.id,
                name="created",
                description="desc",
                backup_type=BackupType.manual,
            )
        )
        db.commit()  # adapter does not commit

        assert entity.id is not None
        assert entity.status == BackupStatus.creating
        assert entity.file_path == ""
        # `server_name` must be populated via refresh() so wire response works
        assert entity.server_name == "W1"

    @pytest.mark.asyncio
    async def test_add_completed_one_shot(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="W2", port=25573)
        entity = await repository.add(
            CreateBackupCommand(
                server_id=server.id,
                name="upload",
                description=None,
                backup_type=BackupType.manual,
                status=BackupStatus.completed,
                file_path="/p/x.tar.gz",
                file_size=1024,
            )
        )
        db.commit()
        assert entity.status == BackupStatus.completed
        assert entity.file_path == "/p/x.tar.gz"
        assert entity.file_size == 1024

    @pytest.mark.asyncio
    async def test_update_file_info(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="UF", port=25574)
        row = _seed_backup(db, server.id, name="creating")

        updated = await repository.update_file_info(
            row.id,
            UpdateBackupFileCommand(
                file_path="/data/a.tar.gz",
                file_size=4096,
                status=BackupStatus.completed,
            ),
        )
        db.commit()
        assert updated is not None
        assert updated.file_path == "/data/a.tar.gz"
        assert updated.file_size == 4096
        assert updated.status == BackupStatus.completed

    @pytest.mark.asyncio
    async def test_update_file_info_unknown_returns_none(self, repository):
        result = await repository.update_file_info(
            99999,
            UpdateBackupFileCommand(
                file_path="x", file_size=0, status=BackupStatus.failed
            ),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_status(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="US", port=25575)
        row = _seed_backup(db, server.id, name="creating")
        updated = await repository.update_status(row.id, BackupStatus.failed)
        db.commit()
        assert updated is not None
        assert updated.status == BackupStatus.failed

    @pytest.mark.asyncio
    async def test_delete_removes_row(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, name="DR", port=25576)
        row = _seed_backup(db, server.id, name="gone")
        backup_id = row.id

        assert await repository.delete(backup_id) is True
        db.commit()
        assert await repository.get(backup_id) is None

    @pytest.mark.asyncio
    async def test_delete_unknown_returns_false(self, repository):
        assert await repository.delete(99999) is False


# ---------------------------------------------------------------------------
# Adapter-level sanity
# ---------------------------------------------------------------------------


class TestBackupRepositorySanity:
    def test_adapter_does_not_subclass_anything_surprising(self):
        # Pure structural impl — must not inherit from ABCs etc.
        assert SqlAlchemyBackupRepository.__bases__ == (object,)

    def test_orm_columns_unchanged(self, db):
        # Pin the wire shape — if columns change, the entity/converter
        # need to be reviewed.
        mapper = inspect(Backup)
        names = {c.key for c in mapper.columns}
        assert {
            "id",
            "server_id",
            "name",
            "description",
            "file_path",
            "file_size",
            "backup_type",
            "status",
            "created_at",
        }.issubset(names)
