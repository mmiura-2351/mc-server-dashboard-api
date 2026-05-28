"""File-domain database migrations.

Domain-specific DDL helpers for the `files` bounded context. These are
invoked from `app.main` during startup, after `Base.metadata.create_all`,
to perform idempotent schema upgrades that SQLAlchemy's
``create_all`` cannot express on its own (notably retro-fitting UNIQUE
constraints onto pre-existing tables).

Per `docs/app/ARCHITECTURE.md` Section 4.3, domain-specific DDL lives under
``app/<domain>/adapters/migrations.py`` rather than the cross-cutting
``app/core/`` package.
"""

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def migrate_file_history_unique_index(engine: Any) -> None:
    """Idempotent migration: ensure `uq_file_edit_history_server_path_version`
    is present on `file_edit_history (server_id, file_path, version_number)`.

    Behaviour:
    1. SELECT existing duplicate rows. If any are found, log a
       maintainer-actionable error listing the first 10 offenders and
       raise `RuntimeError` to abort startup before any DDL is issued
       — installing a UNIQUE index on a table with duplicates would
       fail anyway, but failing fast with a readable message saves
       operators from chasing a cryptic SQLite/MySQL error.
    2. If no duplicates exist, execute
       `CREATE UNIQUE INDEX IF NOT EXISTS` so the migration is safe
       to re-run on already-migrated databases.

    Called once during application startup, immediately after
    `Base.metadata.create_all`.
    """
    with engine.connect() as conn:
        # Pre-check: detect any existing duplicate (server_id, file_path,
        # version_number) tuples that would block the unique index.
        dup_check = conn.execute(
            text(
                "SELECT server_id, file_path, version_number, COUNT(*) AS cnt "
                "FROM file_edit_history "
                "GROUP BY server_id, file_path, version_number "
                "HAVING COUNT(*) > 1 "
                "LIMIT 10"
            )
        ).fetchall()

        if dup_check:
            # Total distinct duplicate-key groups, so the operator-facing
            # message can report "showing first 10 of N" instead of just
            # the first slice (operators were anchoring on the sample
            # length and underestimating the scope of the cleanup).
            total_dup_count = (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM ("
                        "  SELECT 1 FROM file_edit_history"
                        "   GROUP BY server_id, file_path, version_number"
                        "  HAVING COUNT(*) > 1"
                        ") AS dup_groups"
                    )
                ).scalar()
                or 0
            )

            sample = "\n".join(
                f"  server_id={row[0]}, file_path={row[1]!r}, "
                f"version_number={row[2]}, count={row[3]}"
                for row in dup_check
            )
            shown = min(len(dup_check), total_dup_count)
            error_msg = (
                f"Cannot create UNIQUE INDEX on file_edit_history: "
                f"{total_dup_count} duplicate row group(s) detected.\n"
                "Maintainer action required: manually deduplicate before "
                "next deploy.\n"
                f"Affected rows (showing first {shown} of {total_dup_count}):\n"
                f"{sample}\n\n"
                "Suggested inspection query:\n"
                "  SELECT * FROM file_edit_history\n"
                "   WHERE (server_id, file_path, version_number) IN (\n"
                "     SELECT server_id, file_path, version_number\n"
                "       FROM file_edit_history\n"
                "      GROUP BY server_id, file_path, version_number\n"
                "      HAVING COUNT(*) > 1\n"
                "   );\n"
            )
            logger.error(error_msg)
            raise RuntimeError(
                "file_edit_history contains duplicate (server_id, file_path, "
                "version_number) rows; migration aborted"
            )

        # No duplicates — safe to (re)create the unique index.
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_file_edit_history_server_path_version "
                "ON file_edit_history (server_id, file_path, version_number)"
            )
        )
        conn.commit()


# Performance indexes added in Issue #75 Phase 1. `editor_user_id`
# accelerates "edits by user" lookups in the audit UI; the column is
# also the FK target for `ON DELETE SET NULL`, where some engines
# (notably MySQL/InnoDB) require an index for cascade efficiency.
_FILE_HISTORY_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_file_edit_history_editor_user_id", "editor_user_id"),
)


def migrate_file_history_indexes(engine: Any) -> None:
    """Idempotent migration: ensure performance indexes exist on
    ``file_edit_history``.

    Distinct from :func:`migrate_file_history_unique_index`, which
    installs the correctness-critical UNIQUE constraint and aborts
    startup on duplicate rows. This helper only adds performance
    hints — failures are logged at WARNING and swallowed.

    Called once during application startup, immediately after
    ``Base.metadata.create_all``.
    """
    with engine.connect() as conn:
        for index_name, column in _FILE_HISTORY_INDEXES:
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON file_edit_history ({column})"
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to create index %s on file_edit_history(%s): %s",
                    index_name,
                    column,
                    exc,
                )
        conn.commit()
