"""Auth-domain database migrations.

Domain-specific DDL helpers for the `auth` bounded context.
Invoked from `app.main` during startup after
``Base.metadata.create_all`` to retro-fit indexes onto pre-existing
tables.

Per `docs/ARCHITECTURE.md` §4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py``.

Issue #75 Phase 1: adds a composite ``(username, attempted_at)``
index to ``login_attempts`` so the brute-force sliding-window
COUNT query can be served from a single index range scan.
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_LOGIN_ATTEMPT_COMPOSITE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_login_attempts_username_attempted", "username, attempted_at"),
)


def migrate_login_attempt_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on
    ``login_attempts``.

    Behaviour:

    1. For each ``(index_name, columns)`` in
       :data:`_LOGIN_ATTEMPT_COMPOSITE_INDEXES`, issue
       ``CREATE INDEX IF NOT EXISTS``. Safe to re-run.
    2. Failures on individual indexes are logged at WARNING and
       swallowed — these are performance hints, not correctness
       constraints.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for index_name, columns in _LOGIN_ATTEMPT_COMPOSITE_INDEXES:
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON login_attempts ({columns})"
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create composite index %s on login_attempts(%s): %s",
                    index_name,
                    columns,
                    exc,
                )
        conn.commit()
