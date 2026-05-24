"""Version-domain database migrations.

Invoked from ``app.main._initialize_database`` during startup, after
``Base.metadata.create_all``.

Issue #354: backfill ``minecraft_versions.is_stable`` by re-evaluating
each row's version string against the pre-release detection regex.
"""

import logging
from typing import Any

from sqlalchemy import text

from app.versions.domain.stability import is_stable_version

logger = logging.getLogger(__name__)


def migrate_version_stability(engine: Any) -> None:
    """Idempotent backfill: set ``is_stable`` based on version string.

    Scans every row in ``minecraft_versions``, computes the expected
    stability flag via :func:`is_stable_version`, and batch-updates
    rows whose stored value disagrees.  Safe to re-run — a no-op when
    all values are already correct.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, version, is_stable FROM minecraft_versions")
            ).fetchall()

            updates: list[tuple[int, bool]] = []
            for row in rows:
                row_id, version_str, current_stable = row
                expected = is_stable_version(version_str)
                if bool(current_stable) != expected:
                    updates.append((row_id, expected))

            if updates:
                for row_id, expected in updates:
                    conn.execute(
                        text(
                            "UPDATE minecraft_versions "
                            "SET is_stable = :stable WHERE id = :id"
                        ),
                        {"stable": expected, "id": row_id},
                    )
                conn.commit()

            logger.info(
                "is_stable backfill: scanned %d versions, updated %d",
                len(rows),
                len(updates),
            )
    except Exception as exc:
        logger.warning("is_stable backfill failed: %s", exc)
