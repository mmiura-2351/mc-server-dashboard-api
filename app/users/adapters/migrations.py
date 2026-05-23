"""User-domain database migrations.

Domain-specific DDL helpers for the `users` bounded context. These are
invoked from `app.main` during startup, after `Base.metadata.create_all`,
to perform idempotent schema upgrades that SQLAlchemy's ``create_all``
cannot express on its own (notably retro-fitting NOT NULL columns onto
pre-existing tables).

Per `docs/ARCHITECTURE.md` §4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py`` rather than the cross-cutting
``app/core/`` package.
"""

import logging
from typing import Any

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def migrate_users_token_version(engine: Any) -> None:
    """Idempotent migration: ensure ``users.token_version`` column exists.

    Issue #237 introduces the ``token_version`` column on ``users`` to
    support immediate JWT revocation on deactivation / password change.
    ``create_all`` only creates *missing* tables — it never adds new
    columns to existing tables — so we must perform an explicit
    ``ALTER TABLE`` for databases provisioned before this change.

    Behaviour:

    1. Use SQLAlchemy's ``Inspector`` to detect whether the
       ``token_version`` column is already present. If so, return
       without issuing DDL (safe to re-run on already-migrated
       databases).
    2. Otherwise execute ``ALTER TABLE users ADD COLUMN token_version
       INTEGER NOT NULL DEFAULT 0``. The ``DEFAULT 0`` clause both
       backfills existing rows and satisfies the ``NOT NULL``
       constraint without a separate ``UPDATE`` pass.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        # ``create_all`` has not yet run — nothing to migrate. The
        # column is part of the model definition so the freshly
        # created table will already have it.
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "token_version" in existing_columns:
        return

    with engine.connect() as conn:
        conn.execute(
            text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
        )
        conn.commit()

    logger.info("users.token_version column added (Issue #237 — JWT revocation support)")
