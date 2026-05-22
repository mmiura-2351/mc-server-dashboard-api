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

import errno
import random
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork
from app.backups.application import service as backup_service_module
from app.backups.application.service import BackupService
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.models import Backup, Server, ServerType


@pytest.fixture
def ephemeral_port() -> int:
    """Return a random ephemeral-range port (N-7).

    Earlier revisions of this file hard-coded 25801–25804, which
    collides under xdist when tests share a worker DB. The actual
    `port` value is only inserted into the seeded `Server` row to
    satisfy the NOT NULL constraint — no socket is opened — so any
    valid port number works.
    """
    return random.randint(49152, 65535)


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
    db, admin_user, tmp_path, monkeypatch, ephemeral_port
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
        db, admin_user.id, name="ob_create", port=ephemeral_port, dir_path=server_dir
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
async def test_create_backup_promotes_to_final_path_on_success(
    db, admin_user, tmp_path, ephemeral_port
):
    """Sanity check for the atomic-rename happy path: after success
    the file lives at the canonical path and `.pending/` is empty."""
    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "ob_ok")
    server = _seed_server(
        db, admin_user.id, name="ob_ok", port=ephemeral_port, dir_path=server_dir
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
    db, admin_user, tmp_path, monkeypatch, ephemeral_port
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
        db, admin_user.id, name="ob_upload", port=ephemeral_port, dir_path=server_dir
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
    db, admin_user, tmp_path, monkeypatch, ephemeral_port
):
    """If the tar-write itself fails (before commit), the cleanup
    branch must still leave both the canonical and `.pending/`
    directories empty.
    """
    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "ob_writefail")
    server = _seed_server(
        db, admin_user.id, name="ob_writefail", port=ephemeral_port, dir_path=server_dir
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


# ---------------------------------------------------------------------------
# Review feedback B-1 / B-2 regression tests — atomic-rename data loss bugs
# ---------------------------------------------------------------------------


def _make_replace_first_call_fails(errno_code: int = errno.EXDEV):
    """Build an `os.replace` shim that raises on its FIRST call only.

    Used to simulate post-commit rename failure: the first `os.replace`
    inside `create_backup` / `upload_backup` is the post-commit
    promotion (the one we want to fail); the second call (made by
    `_preserve_post_commit_temp`) moves the temp file into `.failed/`
    and must succeed so the test can assert recovery.
    """
    import os as _os

    real_replace = _os.replace
    state = {"calls": 0}

    def replace_then_fail(src, dst):
        state["calls"] += 1
        if state["calls"] == 1:
            raise OSError(errno_code, "simulated post-commit rename failure")
        return real_replace(src, dst)

    return replace_then_fail, state


@pytest.mark.asyncio
async def test_create_backup_preserves_data_when_replace_fails_after_commit(
    db, admin_user, tmp_path, monkeypatch, ephemeral_port
):
    """B-2 regression: when `os.replace` raises AFTER `uow.commit()`
    succeeded, the temp file MUST be moved to `.failed/` (not
    unlinked) so the user-supplied backup data is recoverable.
    Pre-fix, the cleanup branch called `temp_path.unlink()`, silently
    losing data while leaving a DB row pointing at a non-existent
    file.
    """
    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "b2_create")
    server = _seed_server(
        db, admin_user.id, name="b2_create", port=ephemeral_port, dir_path=server_dir
    )

    service = _service(db, backups_dir)
    replace_shim, state = _make_replace_first_call_fails()
    monkeypatch.setattr(backup_service_module.os, "replace", replace_shim)

    with pytest.raises(OSError, match="simulated post-commit rename failure"):
        await service.create_backup(server_id=server.id, name="b2c")

    # Recovery: the temp file was moved into `.failed/` by the
    # post-commit handler — NOT deleted.
    failed_dir = backups_dir / ".failed"
    assert failed_dir.exists(), (
        f"Expected .failed/ to exist after post-commit failure; "
        f"backups_dir contents: {list(backups_dir.iterdir())}"
    )
    recovered = list(failed_dir.glob("*.tar.gz"))
    assert len(recovered) == 1, (
        f"Expected exactly 1 recovered file in .failed/, got: "
        f"{[str(p) for p in failed_dir.iterdir()]}"
    )
    assert recovered[0].stat().st_size > 0, "Recovered file is empty"

    # `.pending/` is empty — the file moved out, not stayed.
    pending_dir = backups_dir / ".pending"
    if pending_dir.exists():
        assert list(pending_dir.iterdir()) == []

    # DB row exists (commit succeeded before the rename failure).
    db.expire_all()
    backup = db.query(Backup).filter_by(server_id=server.id).first()
    assert backup is not None, "DB row should persist — commit succeeded"

    # We exercised the failing-then-succeeding replace shim at least
    # twice: once for the post-commit promotion (failed), once for
    # the move into `.failed/` (succeeded).
    assert state["calls"] >= 2


@pytest.mark.asyncio
async def test_upload_backup_preserves_data_when_replace_fails_after_commit(
    db, admin_user, tmp_path, monkeypatch, ephemeral_port
):
    """B-2 regression for the upload path: post-commit `os.replace`
    failure must move the validated upload tar into `.failed/`, never
    unlink it.
    """
    import tarfile

    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "b2_upload")
    server = _seed_server(
        db, admin_user.id, name="b2_upload", port=ephemeral_port, dir_path=server_dir
    )

    archive_buf = BytesIO()
    with tarfile.open(fileobj=archive_buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="hello.txt")
        payload = b"hi\n"
        info.size = len(payload)
        tar.addfile(info, BytesIO(payload))
    archive_bytes = archive_buf.getvalue()

    upload = UploadFile(
        filename="b2_upload.tar.gz",
        file=BytesIO(archive_bytes),
        headers={"content-length": str(len(archive_bytes))},
    )
    upload.headers = {"content-length": str(len(archive_bytes))}

    service = _service(db, backups_dir)
    replace_shim, state = _make_replace_first_call_fails()
    monkeypatch.setattr(backup_service_module.os, "replace", replace_shim)

    # The router wraps non-known exceptions in DatabaseOperationException
    # before re-raising. We only care that something raised.
    with pytest.raises(Exception):
        await service.upload_backup(server_id=server.id, file=upload, name="b2u")

    failed_dir = backups_dir / ".failed"
    assert failed_dir.exists(), (
        f"Expected .failed/ to exist after post-commit upload failure; "
        f"backups_dir contents: {list(backups_dir.iterdir())}"
    )
    recovered = list(failed_dir.glob("*.tar.gz"))
    assert len(recovered) == 1, (
        f"Expected exactly 1 recovered file in .failed/, got: "
        f"{[str(p) for p in failed_dir.iterdir()]}"
    )
    assert recovered[0].stat().st_size == len(archive_bytes), (
        "Recovered file size mismatch — data corruption?"
    )

    # DB row persists (commit succeeded).
    db.expire_all()
    backup = db.query(Backup).filter_by(server_id=server.id).first()
    assert backup is not None
    assert state["calls"] >= 2


@pytest.mark.asyncio
async def test_upload_backup_temp_file_is_on_backups_filesystem(
    db, admin_user, tmp_path, monkeypatch, ephemeral_port
):
    """B-1 regression: the upload temp file MUST be created under
    `backups_directory/.pending/`, not `$TMPDIR`. Pre-fix the temp
    lived in `$TMPDIR` and the post-commit `os.replace` could raise
    `EXDEV` whenever `/tmp` and `backups_directory` lived on
    different filesystems, deleting the uploaded data.
    """
    import tarfile

    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "b1_upload")
    server = _seed_server(
        db, admin_user.id, name="b1_upload", port=ephemeral_port, dir_path=server_dir
    )

    captured_dirs: list = []
    real_NamedTemporaryFile = tempfile.NamedTemporaryFile

    def spy_NamedTemporaryFile(*args, **kwargs):
        captured_dirs.append(kwargs.get("dir"))
        return real_NamedTemporaryFile(*args, **kwargs)

    monkeypatch.setattr(
        backup_service_module.tempfile, "NamedTemporaryFile", spy_NamedTemporaryFile
    )

    archive_buf = BytesIO()
    with tarfile.open(fileobj=archive_buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="hello.txt")
        payload = b"hi\n"
        info.size = len(payload)
        tar.addfile(info, BytesIO(payload))
    archive_bytes = archive_buf.getvalue()

    upload = UploadFile(
        filename="b1_upload.tar.gz",
        file=BytesIO(archive_bytes),
        headers={"content-length": str(len(archive_bytes))},
    )
    upload.headers = {"content-length": str(len(archive_bytes))}

    service = _service(db, backups_dir)
    entity = await service.upload_backup(server_id=server.id, file=upload, name="b1u")
    assert entity is not None

    # Every `NamedTemporaryFile` call inside `upload_backup` must pass
    # `dir=<backups_directory>/.pending` (or at minimum a path under
    # `backups_directory`) — never `dir=None` (which would default to
    # `$TMPDIR` and reintroduce the EXDEV bug).
    assert captured_dirs, "service.upload_backup did not call NamedTemporaryFile"
    for d in captured_dirs:
        assert d is not None, (
            f"upload_backup called NamedTemporaryFile with dir=None "
            f"(would default to $TMPDIR; reintroduces B-1 EXDEV bug). "
            f"All dir= args: {captured_dirs}"
        )
        assert Path(d).resolve().is_relative_to(backups_dir.resolve()), (
            f"upload_backup created temp file outside backups_directory "
            f"({backups_dir!r}); dir= arg was {d!r}. This breaks the "
            f"same-filesystem guarantee for os.replace."
        )


@pytest.mark.asyncio
async def test_create_backup_preserves_data_when_replace_fails_and_recovery_also_fails(
    db, admin_user, tmp_path, monkeypatch, ephemeral_port, caplog
):
    """B-2 worst-case edge: BOTH the post-commit `os.replace` AND the
    move-to-`.failed/` rename raise. The service must NOT crash with
    an unhandled error — it must log CRITICAL and re-raise the
    original exception so the caller sees the failure.
    """
    import logging
    import os as _os

    backups_dir = tmp_path / "backups"
    server_dir = _make_server_dir(tmp_path, "b2_double_fail")
    server = _seed_server(
        db,
        admin_user.id,
        name="b2_double_fail",
        port=ephemeral_port,
        dir_path=server_dir,
    )

    service = _service(db, backups_dir)

    real_replace = _os.replace

    def always_fail_replace(src, dst):
        # First call = post-commit promotion. Second call = move to
        # `.failed/`. Both must raise to exercise the edge case;
        # rmtree-cleanup of the test tmp_path uses os.unlink (not
        # os.replace), so this shim is safe.
        raise OSError(errno.EROFS, "simulated read-only filesystem")

    monkeypatch.setattr(backup_service_module.os, "replace", always_fail_replace)

    with caplog.at_level(logging.CRITICAL, logger="app.backups.application.service"):
        with pytest.raises(OSError):
            await service.create_backup(server_id=server.id, name="b2_double")

    # Critical log emitted naming the failure mode.
    critical_msgs = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.CRITICAL and r.name == "app.backups.application.service"
    ]
    assert any("PUNCH-LIST B FAILURE" in m for m in critical_msgs), (
        f"Expected a CRITICAL 'PUNCH-LIST B FAILURE' log; got: {critical_msgs}"
    )

    # DB row persists (commit succeeded).
    db.expire_all()
    backup = db.query(Backup).filter_by(server_id=server.id).first()
    assert backup is not None

    # Belt-and-braces: restore the real os.replace so tmp_path teardown
    # (which does NOT use os.replace, but defensive) is unaffected.
    monkeypatch.setattr(backup_service_module.os, "replace", real_replace)
