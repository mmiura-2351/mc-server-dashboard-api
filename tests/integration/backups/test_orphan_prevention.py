"""Regression tests for Issue #228 Punch-list B (orphan-on-failure
backup files).

The pre-fix code wrote `backup_<server>_<id>_<ts>.tar.gz` directly
into the canonical backups directory and *then* committed the DB row;
any commit failure left an orphan tar.gz on disk forever (no row to
clean it up). The atomic-rename pattern in
`app.backups.application.service` now:

1. Writes the tar.gz to `.pending/.pending-<uuid>.tar.gz`
2. Commits the DB row (with the final path stored)
3. Atomically promotes the temp file with `os.replace()`

If step 2 fails, the temp file is unlinked and **no** file appears in
the canonical backups directory. These tests pin that contract.
"""

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork
from app.backups.application.service import BackupService
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.models import Server, ServerType


def _seed_server(db, owner_id: int, *, name: str, port: int, dir_path: Path) -> Server:
    row = Server(
        name=name,
        description=None,
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=port,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
        directory_path=str(dir_path),
        is_deleted=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _service(db, backups_directory: Path) -> BackupService:
    """Build a `BackupService` wired to the test DB session."""
    return BackupService(
        uow=SqlAlchemyBackupsUnitOfWork(db=db),
        server_read=SqlAlchemyServerReadPort(db),
        backups_directory=backups_directory,
    )


def _make_server_dir(tmp_path: Path, name: str) -> Path:
    """Create a minimal server directory with one file so tar creation
    has actual content."""
    server_dir = tmp_path / "servers" / name
    server_dir.mkdir(parents=True)
    (server_dir / "server.properties").write_text("level-name=world\n")
    return server_dir


@pytest.mark.asyncio
async def test_create_backup_orphan_unlinked_when_commit_fails(
    db, admin_user, tmp_path, monkeypatch
):
    """Punch-list B (create_backup): a DB commit failure must NOT
    leave any tar.gz file in the canonical backups directory.

    The atomic-rename pattern writes to `.pending/` and only promotes
    after commit succeeds — so a forced commit failure should leave
    `backups_directory` empty (of `.tar.gz` files).
    """
    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "ob_create")
    server = _seed_server(
        db, admin_user.id, name="ob_create", port=25801, dir_path=server_dir
    )

    service = _service(db, backups_dir)

    # Inject a commit failure into the underlying UoW. We patch the
    # *class* method so the per-call UoW instance built inside
    # `create_backup` picks it up.
    async def failing_commit(self) -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(SqlAlchemyBackupsUnitOfWork, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await service.create_backup(server_id=server.id, name="x")

    # Canonical directory must have NO tar.gz left behind.
    leftover_archives = list(backups_dir.glob("*.tar.gz"))
    assert leftover_archives == [], (
        f"Orphan tar.gz left in backups_directory: {leftover_archives}"
    )

    # The `.pending/` subdirectory must also be empty — the temp file
    # was unlinked in the cleanup branch.
    pending_dir = backups_dir / ".pending"
    if pending_dir.exists():
        leftover_pending = list(pending_dir.iterdir())
        assert leftover_pending == [], (
            f"Orphan temp file left in .pending/: {leftover_pending}"
        )


@pytest.mark.asyncio
async def test_create_backup_promotes_to_final_path_on_success(db, admin_user, tmp_path):
    """Sanity check for the atomic-rename happy path: after success
    the file lives at the canonical path and `.pending/` is empty."""
    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "ob_ok")
    server = _seed_server(
        db, admin_user.id, name="ob_ok", port=25802, dir_path=server_dir
    )

    service = _service(db, backups_dir)
    entity = await service.create_backup(server_id=server.id, name="happy")

    # Final tar.gz exists at the path stored on the entity.
    assert Path(entity.file_path).exists()
    assert Path(entity.file_path).parent == backups_dir

    # `.pending/` has been swept clean — atomic-rename moved the file
    # out of it.
    pending_dir = backups_dir / ".pending"
    if pending_dir.exists():
        assert list(pending_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_backup_orphan_unlinked_when_commit_fails(
    db, admin_user, tmp_path, monkeypatch
):
    """Punch-list B (upload_backup): a DB commit failure after
    validation must leave the canonical backups directory empty.

    We construct a minimal valid tar.gz in memory, hand it to
    `upload_backup`, then force the UoW commit to fail.
    """
    import tarfile

    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "ob_upload")
    server = _seed_server(
        db, admin_user.id, name="ob_upload", port=25803, dir_path=server_dir
    )

    # Build a tiny valid tar.gz in memory: a single regular file.
    archive_buf = BytesIO()
    with tarfile.open(fileobj=archive_buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="hello.txt")
        payload = b"hi\n"
        info.size = len(payload)
        tar.addfile(info, BytesIO(payload))
    archive_bytes = archive_buf.getvalue()

    upload = UploadFile(
        filename="upload.tar.gz",
        file=BytesIO(archive_bytes),
        headers={"content-length": str(len(archive_bytes))},
    )
    # `UploadFile.headers` is a Headers object; ensure header lookup
    # by the service yields the size string.
    upload.headers = {"content-length": str(len(archive_bytes))}

    service = _service(db, backups_dir)

    async def failing_commit(self) -> None:
        raise RuntimeError("simulated upload commit failure")

    monkeypatch.setattr(SqlAlchemyBackupsUnitOfWork, "commit", failing_commit)

    with pytest.raises(Exception):
        await service.upload_backup(server_id=server.id, file=upload, name="upl")

    # Canonical directory must contain NO promoted tar.gz file.
    leftover_archives = list(backups_dir.glob("*.tar.gz"))
    assert leftover_archives == [], (
        f"Orphan upload tar.gz left in backups_directory: {leftover_archives}"
    )


@pytest.mark.asyncio
async def test_create_backup_handles_write_failure_without_orphan(
    db, admin_user, tmp_path, monkeypatch
):
    """If the tar-write itself fails (before commit), the cleanup
    branch must still leave both the canonical and `.pending/`
    directories empty.
    """
    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "ob_writefail")
    server = _seed_server(
        db, admin_user.id, name="ob_writefail", port=25804, dir_path=server_dir
    )

    service = _service(db, backups_dir)

    # Force the tar-write to raise *after* the temp path is reserved.
    failing_write = AsyncMock(side_effect=RuntimeError("tar write boom"))
    monkeypatch.setattr(service._file_service, "write_backup_file_to", failing_write)

    with pytest.raises(RuntimeError, match="tar write boom"):
        await service.create_backup(server_id=server.id, name="wf")

    assert list(backups_dir.glob("*.tar.gz")) == []
    pending_dir = backups_dir / ".pending"
    if pending_dir.exists():
        assert list(pending_dir.iterdir()) == []
