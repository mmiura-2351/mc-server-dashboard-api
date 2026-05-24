"""Tests for ``migrate_drop_templates`` (Issue #352).

Verifies that:

* ``servers.template_id`` column is dropped via table rebuild.
* ``templates`` table is dropped.
* The migration is idempotent (second run is a no-op).
* Partial failure recovery: a leftover ``servers_new`` table from a
  prior interrupted run is cleaned up before retrying.
"""

import pytest
from sqlalchemy import create_engine, text

from app.servers.adapters.migrations import migrate_drop_templates


@pytest.fixture
def engine(tmp_path):
    """Per-test SQLite engine with a legacy schema that includes
    ``templates`` table and ``servers.template_id`` FK column.
    """
    db_path = tmp_path / "drop_templates.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    with eng.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE users ("
                "  id INTEGER PRIMARY KEY,"
                "  username VARCHAR(50) NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE templates ("
                "  id INTEGER PRIMARY KEY,"
                "  name VARCHAR(100) NOT NULL,"
                "  created_by INTEGER,"
                "  FOREIGN KEY (created_by) REFERENCES users(id)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE servers ("
                "  id INTEGER PRIMARY KEY,"
                "  name VARCHAR(100) NOT NULL,"
                "  owner_id INTEGER NOT NULL,"
                "  template_id INTEGER,"
                "  is_deleted BOOLEAN DEFAULT 0,"
                "  status VARCHAR(20) DEFAULT 'stopped',"
                "  server_type VARCHAR(20) DEFAULT 'vanilla',"
                "  FOREIGN KEY (owner_id) REFERENCES users(id),"
                "  FOREIGN KEY (template_id) REFERENCES templates(id)"
                ")"
            )
        )
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'admin')"))
        conn.execute(
            text("INSERT INTO templates (id, name, created_by) VALUES (1, 'test-tpl', 1)")
        )
        conn.execute(
            text(
                "INSERT INTO servers (id, name, owner_id, template_id) "
                "VALUES (1, 'srv1', 1, 1)"
            )
        )
        conn.commit()
    try:
        yield eng
    finally:
        eng.dispose()


def _col_names(engine, table: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return [r[1] for r in rows]


def _table_exists(engine, table: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        ).fetchone()
    return row[0] > 0


def test_drops_template_id_column(engine):
    migrate_drop_templates(engine)

    cols = _col_names(engine, "servers")
    assert "template_id" not in cols
    assert "name" in cols
    assert "owner_id" in cols


def test_drops_templates_table(engine):
    migrate_drop_templates(engine)

    assert not _table_exists(engine, "templates")


def test_preserves_server_data(engine):
    migrate_drop_templates(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, name, owner_id FROM servers WHERE id = 1")
        ).fetchone()
    assert row is not None
    assert row[1] == "srv1"
    assert row[2] == 1


def test_idempotent_second_run(engine):
    migrate_drop_templates(engine)
    migrate_drop_templates(engine)

    cols = _col_names(engine, "servers")
    assert "template_id" not in cols
    assert not _table_exists(engine, "templates")


def test_recovers_from_leftover_servers_new(engine):
    """Simulate a partial prior run that left ``servers_new`` behind."""
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE servers_new (id INTEGER PRIMARY KEY)"))
        conn.commit()

    migrate_drop_templates(engine)

    assert not _table_exists(engine, "servers_new")
    cols = _col_names(engine, "servers")
    assert "template_id" not in cols
