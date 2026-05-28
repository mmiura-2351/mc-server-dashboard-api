"""Backup-domain database migrations.

Domain-specific DDL helpers for the `backups` bounded context.
Invoked from `app.main` during startup after
``Base.metadata.create_all`` to retro-fit indexes onto pre-existing
tables (``create_all`` only emits indexes when it creates the parent
table).

Per `docs/app/ARCHITECTURE.md` Section 4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py``.

Issue #75 Phase 1: adds performance indexes for the hot query paths
on ``backups`` (per-server listings ordered by recency, status
filters).
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Single-column indexes (name, column). The names mirror
# SQLAlchemy's ``ix_<table>_<column>`` convention.
_BACKUP_SINGLE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_backups_server_id", "server_id"),
    ("ix_backups_status", "status"),
)

# Composite indexes (name, comma-separated columns). The
# ``(server_id, created_at)`` composite serves the dominant
# "list a server's backups newest first" path.
_BACKUP_COMPOSITE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_backups_server_id_created_at", "server_id, created_at"),
)


def migrate_backup_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on
    ``backups``.

    Behaviour:

    1. For each entry in :data:`_BACKUP_SINGLE_INDEXES` and
       :data:`_BACKUP_COMPOSITE_INDEXES`, issue
       ``CREATE INDEX IF NOT EXISTS`` so the migration is safe to
       re-run on already-migrated databases.
    2. Failures on individual indexes are logged at WARNING and
       swallowed — these are performance hints, not correctness
       constraints.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for index_name, column in _BACKUP_SINGLE_INDEXES:
            try:
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON backups ({column})")
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create index %s on backups(%s): %s",
                    index_name,
                    column,
                    exc,
                )
        for index_name, columns in _BACKUP_COMPOSITE_INDEXES:
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON backups ({columns})"
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create composite index %s on backups(%s): %s",
                    index_name,
                    columns,
                    exc,
                )
        conn.commit()
