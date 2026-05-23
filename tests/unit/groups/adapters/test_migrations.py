"""Tests for :mod:`app.groups.adapters.migrations` (Issue #75 Phase 1)."""

import pytest
from sqlalchemy import create_engine, text

from app.core.database import Base
from app.groups.adapters.migrations import (
    _GROUP_INDEXES,
    migrate_group_indexes,
)


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "groups_indexes.db"
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


def test_migrate_group_indexes_creates_expected_indexes(engine):
    migrate_group_indexes(engine)
    for table, expected, _ in _GROUP_INDEXES:
        names = _index_names(engine, table)
        assert expected in names, f"missing {expected} on {table}: {names}"


def test_migrate_group_indexes_is_idempotent(engine):
    migrate_group_indexes(engine)
    migrate_group_indexes(engine)
    for table, expected, _ in _GROUP_INDEXES:
        assert expected in _index_names(engine, table)
