"""Tests for `app.core.db_ddl.create_index_if_not_exists` (Issue #412).

The helper is the single choke point that all domain index migrations route
through, so it must (a) create the requested index, (b) be idempotent, (c)
handle composite columns, (d) quote reserved-word identifiers, and (e) reject
any identifier that is not a plain SQL identifier *before* running SQL.
"""

import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)

from app.core.db_ddl import create_index_if_not_exists

metadata = MetaData()

# Includes a reserved-word table name (`groups`) and a multi-column table so
# composite-index and quoting behaviour can be exercised end to end.
groups_table = Table(
    "groups",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", Integer),
    Column("created_at", String(40)),
)


@pytest.fixture
def conn():
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    connection = engine.connect()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def _index_names(conn, table: str) -> set[str]:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :t"),
        {"t": table},
    ).fetchall()
    return {row[0] for row in rows}


def test_creates_single_column_index(conn):
    create_index_if_not_exists(
        conn, index_name="ix_groups_owner_id", table="groups", columns="owner_id"
    )
    assert "ix_groups_owner_id" in _index_names(conn, "groups")


def test_is_idempotent(conn):
    for _ in range(2):
        create_index_if_not_exists(
            conn, index_name="ix_groups_owner_id", table="groups", columns="owner_id"
        )
    assert "ix_groups_owner_id" in _index_names(conn, "groups")


def test_composite_columns_from_comma_string(conn):
    create_index_if_not_exists(
        conn,
        index_name="ix_groups_owner_created",
        table="groups",
        columns="owner_id, created_at",
    )
    assert "ix_groups_owner_created" in _index_names(conn, "groups")


def test_composite_columns_from_iterable(conn):
    create_index_if_not_exists(
        conn,
        index_name="ix_groups_created_owner",
        table="groups",
        columns=["created_at", "owner_id"],
    )
    assert "ix_groups_created_owner" in _index_names(conn, "groups")


def test_reserved_word_table_is_quoted(conn):
    """A reserved-word table name (`groups`) must not raise — it is quoted."""
    create_index_if_not_exists(
        conn, index_name="ix_groups_id", table="groups", columns="id"
    )
    assert "ix_groups_id" in _index_names(conn, "groups")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"index_name": "ix); DROP TABLE groups;--", "table": "groups", "columns": "id"},
        {"index_name": "ix_ok", "table": "groups) --", "columns": "id"},
        {"index_name": "ix_ok", "table": "groups", "columns": "id); DROP TABLE x;--"},
        {"index_name": "ix_ok", "table": "groups", "columns": "owner_id) --"},
        {"index_name": "1bad", "table": "groups", "columns": "id"},
        {"index_name": "ix_ok", "table": "", "columns": "id"},
    ],
)
def test_rejects_unsafe_identifiers_before_executing(conn, kwargs):
    before = _index_names(conn, "groups")
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        create_index_if_not_exists(conn, **kwargs)
    # Nothing was executed.
    assert _index_names(conn, "groups") == before


def test_rejects_empty_columns(conn):
    with pytest.raises(ValueError):
        create_index_if_not_exists(
            conn, index_name="ix_ok", table="groups", columns=[]
        )
