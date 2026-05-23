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
