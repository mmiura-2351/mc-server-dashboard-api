"""Group-domain database migrations.

Domain-specific DDL helpers for the `groups` bounded context.
Invoked from `app.main` during startup after
``Base.metadata.create_all`` to retro-fit indexes onto pre-existing
tables.

Per `docs/ARCHITECTURE.md` §4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py``.

Issue #75 Phase 1: adds performance indexes for owner-scoped group
listings and the per-group server-attachment join.
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# (table, index_name, column).
_GROUP_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("groups", "ix_groups_owner_id", "owner_id"),
    ("server_groups", "ix_server_groups_group_id", "group_id"),
)


def migrate_group_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on the
    ``groups`` and ``server_groups`` tables.

    Behaviour:

    1. For each ``(table, index_name, column)`` in :data:`_GROUP_INDEXES`,
       issue ``CREATE INDEX IF NOT EXISTS``. Safe to re-run.
    2. Failures on individual indexes are logged at WARNING and
       swallowed — these are performance hints, not correctness
       constraints.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for table, index_name, column in _GROUP_INDEXES:
            try:
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})")
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create index %s on %s(%s): %s",
                    index_name,
                    table,
                    column,
                    exc,
                )
        conn.commit()
