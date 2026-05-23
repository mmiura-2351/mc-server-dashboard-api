"""Template-domain database migrations.

Domain-specific DDL helpers for the `templates` bounded context.
Invoked from `app.main` during startup after
``Base.metadata.create_all`` to retro-fit indexes onto pre-existing
tables.

Per `docs/ARCHITECTURE.md` §4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py``.

Issue #75 Phase 1: adds performance indexes for creator-scoped
template listings, server-type filters, and the public/private
visibility predicate.
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_TEMPLATE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_templates_created_by", "created_by"),
    ("ix_templates_server_type", "server_type"),
    ("ix_templates_is_public", "is_public"),
)


def migrate_template_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on
    ``templates``.

    Behaviour:

    1. For each ``(index_name, column)`` in :data:`_TEMPLATE_INDEXES`,
       issue ``CREATE INDEX IF NOT EXISTS``. Safe to re-run.
    2. Failures on individual indexes are logged at WARNING and
       swallowed — these are performance hints, not correctness
       constraints.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for index_name, column in _TEMPLATE_INDEXES:
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON templates ({column})"
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create index %s on templates(%s): %s",
                    index_name,
                    column,
                    exc,
                )
        conn.commit()
