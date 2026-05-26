"""Business-metric collection for the Prometheus `/metrics` endpoint.

The collector is intentionally pull-based: when Prometheus scrapes
`/metrics` the route calls `BusinessMetricsCollector.collect()` which
refreshes the relevant Gauges with current values. This keeps DB I/O
proportional to scrape frequency rather than to request volume.

All queries are deliberately cheap (`COUNT(*)` aggregates only) so
that scrape latency stays well under the typical 10s Prometheus
default. No N+1 traversal; the collector touches the DB at most
three times per scrape.

Filesystem-derived gauges (`mc_backups_pending_total`) are exposed as
a best-effort count of `*.tar.gz` files in `backups/.pending/` — that
directory is the source of truth for in-flight backup uploads (see
`app/backups/application/service.py`). Errors during a scrape are
logged and swallowed so a transient stat failure cannot poison the
endpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path

from prometheus_client import Gauge
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import AccountLockout
from app.backups.models import Backup
from app.core.datetime_utils import utcnow
from app.servers.domain.value_objects import BackupStatus, ServerStatus
from app.servers.models import Server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gauges (module-level so they share the default REGISTRY)
# ---------------------------------------------------------------------------
#
# Naming convention: `mc_` prefix scopes every metric to this project
# so operators running multiple exporters in the same Prometheus
# instance do not collide with stock libraries (e.g. `process_*`,
# `python_*`).

servers_total = Gauge(
    "mc_servers_total",
    "Number of Minecraft servers grouped by lifecycle status.",
    ["status"],
)

backups_pending_total = Gauge(
    "mc_backups_pending_total",
    (
        "Backups currently in the `creating` state (in-flight + leftover "
        "`.pending/*.tar.gz` files awaiting cleanup)."
    ),
)

account_lockouts_active = Gauge(
    "mc_account_lockouts_active",
    "Active account lockouts (rows where locked_until is in the future).",
)

semaphore_in_use = Gauge(
    "mc_semaphore_in_use",
    "Current number of acquired slots for a concurrency semaphore.",
    ["semaphore"],
)

semaphore_limit = Gauge(
    "mc_semaphore_limit",
    "Configured upper limit for a concurrency semaphore.",
    ["semaphore"],
)


class BusinessMetricsCollector:
    """Refresh business-level Prometheus gauges on demand.

    Construction is cheap; instantiation per scrape is fine. The
    collector deliberately owns no state — gauges live at module
    scope on the default registry.
    """

    def __init__(self, db: Session, backups_directory: Path) -> None:
        self._db = db
        self._backups_directory = backups_directory

    def collect(self) -> None:
        """Refresh every business gauge.

        Individual metric collection is wrapped so a partial failure
        (e.g. the lockouts table missing during a transitional
        migration) does not blank the entire scrape.
        """
        self._collect_server_status_counts()
        self._collect_pending_backups()
        self._collect_active_lockouts()
        self._collect_semaphore_stats()

    # ------------------------------------------------------------------
    # Individual collectors
    # ------------------------------------------------------------------

    def _collect_server_status_counts(self) -> None:
        try:
            rows = (
                self._db.query(Server.status, func.count(Server.id))
                .group_by(Server.status)
                .all()
            )
            counts = {status: count for status, count in rows}
            # Always emit a sample for every known status so Prometheus
            # range vectors (`rate`, `increase`) do not have to deal
            # with gauges that disappear between scrapes.
            for status in ServerStatus:
                value = counts.get(status, 0)
                servers_total.labels(status=status.value).set(value)
        except Exception:  # noqa: BLE001 — see module docstring
            logger.exception("Failed to collect mc_servers_total")

    def _collect_pending_backups(self) -> None:
        try:
            db_pending = (
                self._db.query(func.count(Backup.id))
                .filter(Backup.status == BackupStatus.creating)
                .scalar()
                or 0
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to query Backup rows for mc_backups_pending_total")
            db_pending = 0

        fs_pending = 0
        pending_dir = self._backups_directory / ".pending"
        try:
            if pending_dir.exists():
                fs_pending = sum(1 for _ in pending_dir.glob("*.tar.gz"))
        except OSError:
            logger.exception("Failed to list %s for pending backups", pending_dir)

        backups_pending_total.set(db_pending + fs_pending)

    def _collect_active_lockouts(self) -> None:
        try:
            now = utcnow()
            count = (
                self._db.query(func.count(AccountLockout.id))
                .filter(AccountLockout.locked_until > now)
                .scalar()
                or 0
            )
            account_lockouts_active.set(count)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to collect mc_account_lockouts_active")
            # Leave the gauge at its previous value so the metric does
            # not flap to 0 during a transient DB blip.

    def _collect_semaphore_stats(self) -> None:
        try:
            from app.core.concurrency import get_semaphores

            registry = get_semaphores()
            for name in ("backup", "websocket", "file_io"):
                sema = getattr(registry, name, None)
                if sema is not None:
                    semaphore_in_use.labels(semaphore=name).set(sema.in_use)
                    semaphore_limit.labels(semaphore=name).set(sema.limit)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to collect mc_semaphore_* metrics")


__all__ = [
    "BusinessMetricsCollector",
    "account_lockouts_active",
    "backups_pending_total",
    "semaphore_in_use",
    "semaphore_limit",
    "servers_total",
]
