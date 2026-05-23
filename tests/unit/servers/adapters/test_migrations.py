"""Tests for :mod:`app.servers.adapters.migrations` (Issue #75 Phase 1).

Verifies that:

* Each performance index is created with the expected name.
* The helper is idempotent: a second call must not raise.
"""

import pytest
from sqlalchemy import create_engine, text

from app.core.database import Base
from app.servers.adapters.migrations import (
    _SERVER_INDEXES,
    migrate_server_indexes,
)


@pytest.fixture
def engine(tmp_path):
    """Per-test SQLite engine with the full `Base.metadata` schema applied."""
    db_path = tmp_path / "servers_indexes.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _index_names(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :t"),
            {"t": table},
        ).fetchall()
    return {row[0] for row in rows}


def test_migrate_server_indexes_creates_expected_indexes(engine):
    migrate_server_indexes(engine)

    names = _index_names(engine, "servers")
    for expected, _ in _SERVER_INDEXES:
        assert expected in names, f"missing index {expected}: {names}"


def test_migrate_server_indexes_is_idempotent(engine):
    """Running the migration twice in a row must be a no-op."""
    migrate_server_indexes(engine)
    migrate_server_indexes(engine)

    names = _index_names(engine, "servers")
    for expected, _ in _SERVER_INDEXES:
        assert expected in names
