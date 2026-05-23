"""Tests for the performance-index helper added to
:mod:`app.files.adapters.migrations` in Issue #75 Phase 1.

Note: :func:`migrate_file_history_unique_index` (the correctness-critical
UNIQUE constraint installer) is covered by
``tests/integration/files/test_toctou.py``.
"""

import pytest
from sqlalchemy import create_engine, text

from app.core.database import Base
from app.files.adapters.migrations import (
    _FILE_HISTORY_INDEXES,
    migrate_file_history_indexes,
)


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "file_history_indexes.db"
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


def test_migrate_file_history_indexes_creates_expected_indexes(engine):
    migrate_file_history_indexes(engine)
    names = _index_names(engine, "file_edit_history")
    for expected, _ in _FILE_HISTORY_INDEXES:
        assert expected in names, f"missing index {expected}: {names}"


def test_migrate_file_history_indexes_is_idempotent(engine):
    migrate_file_history_indexes(engine)
    migrate_file_history_indexes(engine)
    names = _index_names(engine, "file_edit_history")
    for expected, _ in _FILE_HISTORY_INDEXES:
        assert expected in names
