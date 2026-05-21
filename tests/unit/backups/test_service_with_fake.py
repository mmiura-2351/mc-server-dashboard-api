"""Unit tests for `BackupService` use cases (with file-IO mocked).

Focuses on the orchestration logic: server-not-found path, list/get/
statistics pass-through, restore-not-completed guard, delete sequencing,
and the orphan-archive cleanup contract.
"""

from pathlib import Path

import pytest

from app.backups.application.service import BackupService
from app.core.exceptions import (
    BackupNotFoundException,
    ServerNotFoundException,
    ServerStateException,
)
from app.servers.models import BackupStatus, BackupType
from tests.unit.backups.fakes import (
    FakeBackupsUnitOfWork,
    FakeServerReadPort,
    make_backup_entity,
)


@pytest.fixture
def uow() -> FakeBackupsUnitOfWork:
    return FakeBackupsUnitOfWork()


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort()


@pytest.fixture
def tmp_backup_dir(tmp_path) -> Path:
    return tmp_path / "backups"


def _make_service(
    uow: FakeBackupsUnitOfWork,
    server_read: FakeServerReadPort,
    backups_dir: Path,
) -> BackupService:
    return BackupService(uow=uow, server_read=server_read, backups_directory=backups_dir)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    @pytest.mark.asyncio
    async def test_list_backups_pass_through(self, uow, server_read, tmp_backup_dir):
        uow.backups.seed(make_backup_entity(id=1, server_id=1, name="a"))
        uow.backups.seed(make_backup_entity(id=2, server_id=1, name="b"))
        svc = _make_service(uow, server_read, tmp_backup_dir)
        page = await svc.list_backups(server_id=1)
        assert page.total == 2

    @pytest.mark.asyncio
    async def test_get_backup(self, uow, server_read, tmp_backup_dir):
        uow.backups.seed(make_backup_entity(id=1, server_id=1))
        svc = _make_service(uow, server_read, tmp_backup_dir)
        entity = await svc.get_backup(1)
        assert entity is not None
        assert entity.id == 1

    @pytest.mark.asyncio
    async def test_get_statistics(self, uow, server_read, tmp_backup_dir):
        uow.backups.seed(
            make_backup_entity(
                id=1, server_id=1, status=BackupStatus.completed, file_size=100
            )
        )
        uow.backups.seed(
            make_backup_entity(
                id=2, server_id=1, status=BackupStatus.failed, file_size=50
            )
        )
        svc = _make_service(uow, server_read, tmp_backup_dir)
        stats = await svc.get_backup_statistics()
        assert stats.total_backups == 2
        assert stats.completed_backups == 1
        assert stats.failed_backups == 1
        assert stats.total_size_bytes == 100


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_unknown_raises(self, uow, server_read, tmp_backup_dir):
        svc = _make_service(uow, server_read, tmp_backup_dir)
        with pytest.raises(BackupNotFoundException):
            await svc.restore_backup(99)

    @pytest.mark.asyncio
    async def test_restore_non_completed_raises(self, uow, server_read, tmp_backup_dir):
        uow.backups.seed(
            make_backup_entity(id=1, server_id=1, status=BackupStatus.creating)
        )
        svc = _make_service(uow, server_read, tmp_backup_dir)
        with pytest.raises(ServerStateException):
            await svc.restore_backup(1)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_unknown_raises(self, uow, server_read, tmp_backup_dir):
        svc = _make_service(uow, server_read, tmp_backup_dir)
        with pytest.raises(BackupNotFoundException):
            await svc.delete_backup(99)

    @pytest.mark.asyncio
    async def test_delete_calls_file_then_db(
        self, uow, server_read, tmp_backup_dir, monkeypatch
    ):
        uow.backups.seed(
            make_backup_entity(
                id=1,
                server_id=1,
                file_path=str(tmp_backup_dir / "x.tar.gz"),
            )
        )
        svc = _make_service(uow, server_read, tmp_backup_dir)

        # Pre-create the file so delete_backup_file can succeed
        tmp_backup_dir.mkdir(parents=True, exist_ok=True)
        (tmp_backup_dir / "x.tar.gz").write_bytes(b"x")

        result = await svc.delete_backup(1)
        assert result is True
        assert (tmp_backup_dir / "x.tar.gz").exists() is False
        # Row removed
        assert await uow.backups.get(1) is None


# ---------------------------------------------------------------------------
# Scheduled backup (server-not-found returns None)
# ---------------------------------------------------------------------------


class TestScheduledBackup:
    @pytest.mark.asyncio
    async def test_unknown_server_returns_none(self, uow, server_read, tmp_backup_dir):
        svc = _make_service(uow, server_read, tmp_backup_dir)
        result = await svc.create_scheduled_backup(99)
        assert result is None


# ---------------------------------------------------------------------------
# create_backup orchestration (mocks the file service tar.gz creation)
# ---------------------------------------------------------------------------


class TestCreateBackup:
    @pytest.mark.asyncio
    async def test_unknown_server_raises(self, uow, server_read, tmp_backup_dir):
        svc = _make_service(uow, server_read, tmp_backup_dir)
        with pytest.raises(ServerNotFoundException):
            await svc.create_backup(server_id=99, name="x")

    @pytest.mark.asyncio
    async def test_happy_path_creates_row_and_commits(
        self, uow, server_read, tmp_backup_dir, monkeypatch
    ):
        server_read.seed(id=1, directory_path=str(tmp_backup_dir / "src"))
        svc = _make_service(uow, server_read, tmp_backup_dir)

        # Stub the tar.gz creation; emit a file we can stat.
        archive_name = "backup_1_1_test.tar.gz"
        archive_path = tmp_backup_dir / archive_name

        async def fake_create(server, backup_id, backup_type, progress_callback=None):
            archive_path.write_bytes(b"fake-data")
            return archive_name

        svc._file_service.create_backup_file = fake_create
        # Disable running-server warning (no manager call needed)
        monkeypatch.setattr(svc, "_log_running_server_warning", lambda sid: None)

        entity = await svc.create_backup(
            server_id=1, name="b", backup_type=BackupType.manual
        )
        assert entity is not None
        assert entity.status == BackupStatus.completed
        assert entity.file_size > 0
        assert uow.committed == 1

    @pytest.mark.asyncio
    async def test_post_file_failure_cleans_up_archive(
        self, uow, server_read, tmp_backup_dir, monkeypatch
    ):
        """If update_file_info / commit fails after the tar.gz exists,
        orphan archive is cleaned up (legacy parity)."""
        server_read.seed(id=1, directory_path=str(tmp_backup_dir / "src"))
        svc = _make_service(uow, server_read, tmp_backup_dir)

        archive_name = "orphan.tar.gz"
        archive_path = tmp_backup_dir / archive_name

        async def fake_create(server, backup_id, backup_type, progress_callback=None):
            archive_path.write_bytes(b"x")
            return archive_name

        svc._file_service.create_backup_file = fake_create
        monkeypatch.setattr(svc, "_log_running_server_warning", lambda sid: None)

        # Force commit() to raise — runs AFTER backup_path is set
        async def fail_commit():
            raise RuntimeError("commit-failed")

        uow.commit = fail_commit  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="commit-failed"):
            await svc.create_backup(server_id=1, name="b")
        assert archive_path.exists() is False
