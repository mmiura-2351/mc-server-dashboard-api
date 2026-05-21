"""TOCTOU / migration tests for `file_edit_history.version_number`.

Covers:
- Concurrent writers racing through `create_version_backup` do not
  produce duplicate `(server_id, file_path, version_number)` rows
  thanks to the UNIQUE constraint + application-layer retry.
- `migrate_file_history_unique_index` pre-checks for existing
  duplicate rows and aborts startup with a maintainer-actionable error
  instead of issuing DDL that would fail with a cryptic driver error.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, text

from app.core.database import Base
from app.core.database_utils import migrate_file_history_unique_index
from app.files.adapters.uow import SqlAlchemyFilesUnitOfWork
from app.files.application.service import FileHistoryService
from app.files.models import FileEditHistory
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.models import Server, ServerStatus, ServerType


@pytest.fixture
def server(db, admin_user) -> Server:
    s = Server(
        name="TOCTOU Test Server",
        description="for file-history TOCTOU tests",
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        status=ServerStatus.stopped,
        directory_path="./servers/toctou",
        port=25700,
        max_memory=1024,
        max_players=20,
        owner_id=admin_user.id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.mark.asyncio
async def test_concurrent_create_version_backup_no_duplicates(
    db, tmp_path, server, admin_user
):
    """20 concurrent writers share a session — they must produce
    distinct version numbers (no duplicate rows), and either succeed
    or raise after exhausting retries. The UNIQUE constraint plus the
    in-service retry are the only safety net.
    """
    # Build one service per writer, each with its own UoW bound to the
    # same SQLite session (matches per-request DI shape in production).
    uow = SqlAlchemyFilesUnitOfWork(db=db)
    server_read = SqlAlchemyServerReadPort(db=db)
    service = FileHistoryService(
        uow=uow,
        server_read=server_read,
        history_base_dir=tmp_path,
        max_versions_per_file=1000,
        auto_cleanup_days=999,
    )

    async def writer(i: int):
        try:
            return await service.create_version_backup(
                server_id=server.id,
                file_path="server.properties",
                content=f"writer-{i}-content",
                user_id=admin_user.id,
                description=f"writer-{i}",
            )
        except Exception as e:  # pragma: no cover - surfaced in assertions
            return e

    results = await asyncio.gather(*(writer(i) for i in range(20)))

    # No duplicate version_numbers landed.
    rows = (
        db.query(FileEditHistory)
        .filter_by(server_id=server.id, file_path="server.properties")
        .all()
    )
    version_numbers = [r.version_number for r in rows]
    assert len(version_numbers) == len(set(version_numbers)), (
        f"Duplicate version numbers persisted: {version_numbers}"
    )

    # SQLite + a shared synchronous session serialises writes, so at
    # least one writer must succeed; we keep the assertion permissive
    # because the retry policy may legitimately surface IntegrityError
    # to a few writers under contention.
    successful = [r for r in results if not isinstance(r, Exception)]
    assert successful, "Expected at least one writer to persist a backup"


@pytest.mark.asyncio
async def test_migrate_aborts_on_existing_duplicates(tmp_path):
    """`migrate_file_history_unique_index` must reject a table that
    already contains duplicate `(server_id, file_path, version_number)`
    rows so operators can deduplicate before re-running deploy.

    We hand-build a `file_edit_history` table *without* the UNIQUE
    constraint so we can seed the duplicates. SQLite cannot DROP a
    table-level UNIQUE constraint after the fact, so building the
    schema manually is simpler than tearing it down.
    """
    db_path = tmp_path / "dup.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE file_edit_history ("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  server_id INTEGER NOT NULL,"
                    "  file_path VARCHAR(500) NOT NULL,"
                    "  version_number INTEGER NOT NULL,"
                    "  backup_file_path VARCHAR(500) NOT NULL,"
                    "  file_size BIGINT NOT NULL,"
                    "  content_hash VARCHAR(64),"
                    "  editor_user_id INTEGER,"
                    "  created_at DATETIME NOT NULL,"
                    "  description TEXT"
                    ")"
                )
            )
            for _ in range(2):
                conn.execute(
                    text(
                        "INSERT INTO file_edit_history "
                        "(server_id, file_path, version_number, "
                        " backup_file_path, file_size, content_hash, "
                        " editor_user_id, created_at) "
                        "VALUES (1, 'x.txt', 1, '/tmp/x', 10, NULL, "
                        " NULL, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(RuntimeError, match="duplicate"):
            migrate_file_history_unique_index(engine)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_migrate_is_idempotent_on_clean_table(tmp_path):
    """Running the migration twice in a row is a no-op on a clean
    table — the second call must not raise."""
    db_path = tmp_path / "clean.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(bind=engine)
        migrate_file_history_unique_index(engine)
        migrate_file_history_unique_index(engine)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_toctou_retry_fires_on_sqlite_unique_violation(
    db, tmp_path, server, admin_user, monkeypatch
):
    """Regression: the retry loop must engage when SQLite reports a
    UNIQUE-constraint failure on `file_edit_history`.

    Reviewer feedback on PR #266 flagged that the original detector did
    a substring match for the index name
    `uq_file_edit_history_server_path_version`, which is fine for
    Postgres/MySQL (they name the constraint in the error message) but
    silently failed on SQLite — SQLite's message only lists the
    columns:

        UNIQUE constraint failed:
            file_edit_history.server_id,
            file_edit_history.file_path,
            file_edit_history.version_number

    With that substring-only matcher the retry path was effectively
    dead code on the project's development & test dialect. This test
    pins the SQLite shape by forcing `reserve_next_version_number` to
    return a colliding value on the first attempt and the next free
    one on the second; the persisted `version_number` and the call
    count together prove (a) the IntegrityError was recognised as a
    version-collision and (b) exactly one retry occurred.
    """
    from app.files.adapters.repository import SqlAlchemyFileHistoryRepository

    # Pre-seed (server_id=server.id, file_path="x.txt", version_number=1)
    # so that any insert reusing version_number=1 fails the UNIQUE check.
    db.add(
        FileEditHistory(
            server_id=server.id,
            file_path="x.txt",
            version_number=1,
            backup_file_path="/tmp/seed",
            file_size=1,
            content_hash="seed",
            editor_user_id=admin_user.id,
        )
    )
    db.commit()

    counter = {"n": 0}
    original_reserve = SqlAlchemyFileHistoryRepository.reserve_next_version_number

    async def fake_reserve(self, server_id: int, file_path: str) -> int:
        counter["n"] += 1
        if counter["n"] == 1:
            return 1  # collision with the seeded row
        # Defer to the real implementation for subsequent attempts so
        # we exercise the genuine MAX+1 path on retry.
        return await original_reserve(self, server_id, file_path)

    monkeypatch.setattr(
        SqlAlchemyFileHistoryRepository,
        "reserve_next_version_number",
        fake_reserve,
    )

    uow = SqlAlchemyFilesUnitOfWork(db=db)
    server_read = SqlAlchemyServerReadPort(db=db)
    service = FileHistoryService(
        uow=uow,
        server_read=server_read,
        history_base_dir=tmp_path,
        max_versions_per_file=1000,
        auto_cleanup_days=999,
    )

    result = await service.create_version_backup(
        server_id=server.id,
        file_path="x.txt",
        content="retry-me",
        user_id=admin_user.id,
    )

    assert result is not None, "Retry succeeded — second attempt should persist"
    assert result.version_number == 2, (
        "Second attempt must advance to the next free version number"
    )
    assert counter["n"] == 2, (
        f"Expected exactly 2 reservations (collision + retry); got {counter['n']}"
    )

    # Both the seeded row and the retried insert should be present, with
    # distinct version_numbers — no duplicates landed.
    rows = (
        db.query(FileEditHistory)
        .filter_by(server_id=server.id, file_path="x.txt")
        .order_by(FileEditHistory.version_number)
        .all()
    )
    assert [r.version_number for r in rows] == [1, 2]
