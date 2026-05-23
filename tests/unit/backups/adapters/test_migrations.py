"""Tests for :mod:`app.backups.adapters.migrations` (Issue #75 Phase 1)."""

import pytest
from sqlalchemy import create_engine, text

from app.backups.adapters.migrations import (
    _BACKUP_COMPOSITE_INDEXES,
    _BACKUP_SINGLE_INDEXES,
    migrate_backup_indexes,
)
from app.core.database import Base


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "backups_indexes.db"
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


def test_migrate_backup_indexes_creates_expected_indexes(engine):
    migrate_backup_indexes(engine)
    names = _index_names(engine, "backups")
    for expected, _ in _BACKUP_SINGLE_INDEXES:
        assert expected in names, f"missing single index {expected}: {names}"
    for expected, _ in _BACKUP_COMPOSITE_INDEXES:
        assert expected in names, f"missing composite index {expected}: {names}"


def test_migrate_backup_indexes_is_idempotent(engine):
    migrate_backup_indexes(engine)
    migrate_backup_indexes(engine)
    names = _index_names(engine, "backups")
    for expected, _ in _BACKUP_SINGLE_INDEXES + _BACKUP_COMPOSITE_INDEXES:
        assert expected in names
