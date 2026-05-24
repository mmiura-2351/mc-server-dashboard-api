"""Server-domain database migrations.

Domain-specific DDL helpers for the `servers` bounded context. These
are invoked from `app.main` during startup, after
`Base.metadata.create_all`, to perform idempotent schema upgrades that
SQLAlchemy's ``create_all`` cannot express on its own (notably
retro-fitting indexes onto pre-existing tables — `create_all` only
creates indexes when it creates the parent table).

Per `docs/ARCHITECTURE.md` §4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py`` rather than the cross-cutting
``app/core/`` package.

Issue #75 Phase 1: adds performance indexes for the hot query paths
on ``servers`` (owner-scoped listings, status / type filters,
soft-delete predicate).

Issue #352: drops the ``templates`` table and the ``servers.template_id``
FK column (SQLite multi-step rebuild for the column drop).
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Index names must match SQLAlchemy's auto-generated convention
# (``ix_<table>_<column>``) so that newly provisioned databases
# (where ``create_all`` emits the indexes) and pre-existing databases
# (where this helper emits them) end up with identical catalogs.
_SERVER_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_servers_owner_id", "owner_id"),
    ("ix_servers_status", "status"),
    ("ix_servers_server_type", "server_type"),
    ("ix_servers_is_deleted", "is_deleted"),
)


def migrate_server_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on
    ``servers``.

    Behaviour:

    1. For each ``(index_name, column)`` in :data:`_SERVER_INDEXES`,
       issue ``CREATE INDEX IF NOT EXISTS`` so the migration is safe
       to re-run on already-migrated databases.
    2. Failures on individual indexes are logged at WARNING and
       swallowed — these are performance hints, not correctness
       constraints, so startup must not be aborted by a missing
       index.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for index_name, column in _SERVER_INDEXES:
            try:
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON servers ({column})")
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create index %s on servers(%s): %s",
                    index_name,
                    column,
                    exc,
                )
        conn.commit()


def migrate_drop_templates(engine: Any) -> None:
    """Idempotent migration: drop the ``templates`` table and
    ``servers.template_id`` FK column (#352).

    SQLite does not support ``ALTER TABLE ... DROP COLUMN`` on columns
    that carry a foreign-key constraint, so the column removal uses a
    4-step table-rebuild (create new → copy → drop old → rename).

    Steps:

    1. Drop ``servers.template_id`` via table rebuild (if column exists).
    2. Drop ``templates`` table (if it exists).

    Each step is individually idempotent and swallows errors at WARNING
    so a partial prior run can be completed on the next startup.
    """
    with engine.connect() as conn:
        # Step 1: check whether servers.template_id still exists
        try:
            cols = conn.execute(text("PRAGMA table_info(servers)")).fetchall()
            col_names = [c[1] for c in cols]
        except Exception as exc:
            logger.warning("Cannot inspect servers schema: %s", exc)
            return

        if "template_id" in col_names:
            try:
                conn.execute(text("DROP TABLE IF EXISTS servers_new"))
                keep_cols = [c for c in col_names if c != "template_id"]
                cols_csv = ", ".join(keep_cols)

                col_defs = []
                for c in cols:
                    cname, ctype, notnull, dflt, pk = c[1], c[2], c[3], c[4], c[5]
                    if cname == "template_id":
                        continue
                    parts = [cname, ctype]
                    if pk:
                        parts.append("PRIMARY KEY")
                    if notnull and not pk:
                        parts.append("NOT NULL")
                    if dflt is not None:
                        parts.append(f"DEFAULT {dflt}")
                    col_defs.append(" ".join(parts))

                # Recreate indexes & FK for owner_id
                fk_clause = "FOREIGN KEY (owner_id) REFERENCES users(id)"
                create_sql = (
                    f"CREATE TABLE servers_new ({', '.join(col_defs)}, {fk_clause})"
                )

                conn.execute(text(create_sql))
                conn.execute(
                    text(
                        f"INSERT INTO servers_new ({cols_csv}) SELECT {cols_csv} FROM servers"
                    )
                )
                conn.execute(text("DROP TABLE servers"))
                conn.execute(text("ALTER TABLE servers_new RENAME TO servers"))

                for index_name, column in _SERVER_INDEXES:
                    try:
                        conn.execute(
                            text(
                                f"CREATE INDEX IF NOT EXISTS {index_name} ON servers ({column})"
                            )
                        )
                    except Exception:
                        pass

                logger.info("Dropped servers.template_id column")
            except Exception as exc:
                logger.warning("Failed to drop servers.template_id: %s", exc)

        # Step 2: drop the templates table
        try:
            conn.execute(text("DROP TABLE IF EXISTS templates"))
            logger.info("Dropped templates table")
        except Exception as exc:
            logger.warning("Failed to drop templates table: %s", exc)

        conn.commit()
