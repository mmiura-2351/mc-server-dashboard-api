"""Tests for :mod:`app.audit.adapters.migrations` (Issue #75 Phase 1)."""

import pytest
from sqlalchemy import create_engine, text

from app.audit.adapters.migrations import (
    _AUDIT_COMPOSITE_INDEXES,
    _AUDIT_SINGLE_INDEXES,
    migrate_audit_indexes,
)
from app.core.database import Base


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "audit_indexes.db"
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


def test_migrate_audit_indexes_creates_expected_indexes(engine):
    migrate_audit_indexes(engine)
    names = _index_names(engine, "audit_logs")
    for expected, _ in _AUDIT_SINGLE_INDEXES + _AUDIT_COMPOSITE_INDEXES:
        assert expected in names, f"missing index {expected}: {names}"


def test_migrate_audit_indexes_is_idempotent(engine):
    migrate_audit_indexes(engine)
    migrate_audit_indexes(engine)
    names = _index_names(engine, "audit_logs")
    for expected, _ in _AUDIT_SINGLE_INDEXES + _AUDIT_COMPOSITE_INDEXES:
        assert expected in names
