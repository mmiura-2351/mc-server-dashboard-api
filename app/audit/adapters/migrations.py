"""Audit-domain database migrations.

Domain-specific DDL helpers for the `audit` bounded context.
Invoked from `app.main` during startup after
``Base.metadata.create_all`` to retro-fit indexes onto pre-existing
tables.

Per `docs/ARCHITECTURE.md` §4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py``.

Issue #75 Phase 1: adds performance indexes for the audit log's hot
query paths (per-user timeline, action/resource-type filters,
time-window scans).

Caveat: ``audit_logs.action`` is frequently queried with ``LIKE``
patterns (e.g. ``action LIKE 'server.%'``). A plain b-tree index
only accelerates left-anchored ``LIKE`` predicates and only when
the SQLite database uses the default ``BINARY`` collation. Full-
text indexing for richer action search is intentionally out of
scope for Phase 1 and tracked as a follow-up.
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_AUDIT_SINGLE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_audit_logs_user_id", "user_id"),
    ("ix_audit_logs_action", "action"),
    ("ix_audit_logs_resource_type", "resource_type"),
)

_AUDIT_COMPOSITE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_audit_logs_created_at", "created_at"),
    ("ix_audit_logs_user_created", "user_id, created_at"),
)


def migrate_audit_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on
    ``audit_logs``.

    Behaviour:

    1. For each entry in :data:`_AUDIT_SINGLE_INDEXES` and
       :data:`_AUDIT_COMPOSITE_INDEXES`, issue
       ``CREATE INDEX IF NOT EXISTS``. Safe to re-run.
    2. Failures on individual indexes are logged at WARNING and
       swallowed — these are performance hints, not correctness
       constraints.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for index_name, column in _AUDIT_SINGLE_INDEXES:
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON audit_logs ({column})"
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create index %s on audit_logs(%s): %s",
                    index_name,
                    column,
                    exc,
                )
        for index_name, columns in _AUDIT_COMPOSITE_INDEXES:
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON audit_logs ({columns})"
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create composite index %s on audit_logs(%s): %s",
                    index_name,
                    columns,
                    exc,
                )
        conn.commit()
