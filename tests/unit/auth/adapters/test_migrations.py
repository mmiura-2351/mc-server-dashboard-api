"""Tests for :mod:`app.auth.adapters.migrations` (Issue #75 Phase 1)."""

import pytest
from sqlalchemy import create_engine, text

from app.auth.adapters.migrations import (
    _LOGIN_ATTEMPT_COMPOSITE_INDEXES,
    migrate_login_attempt_indexes,
)
from app.core.database import Base


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "auth_indexes.db"
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


def test_migrate_login_attempt_indexes_creates_expected_indexes(engine):
    migrate_login_attempt_indexes(engine)
    names = _index_names(engine, "login_attempts")
    for expected, _ in _LOGIN_ATTEMPT_COMPOSITE_INDEXES:
        assert expected in names, f"missing index {expected}: {names}"


def test_migrate_login_attempt_indexes_is_idempotent(engine):
    migrate_login_attempt_indexes(engine)
    migrate_login_attempt_indexes(engine)
    names = _index_names(engine, "login_attempts")
    for expected, _ in _LOGIN_ATTEMPT_COMPOSITE_INDEXES:
        assert expected in names
