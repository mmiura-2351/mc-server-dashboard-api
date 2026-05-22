"""Scheduler health checks (backup + version-update).

Both schedulers are *non-critical* — the app degrades gracefully if a
scheduler is not running (manual triggers still work). We therefore
report ``DEGRADED`` rather than ``UNHEALTHY`` when the scheduler is
not currently active. ``UNHEALTHY`` is reserved for the case where
the underlying holder raises (e.g. lifespan never initialised it).
"""

from __future__ import annotations

import time
from typing import Callable

from app.health.domain.entities import ComponentHealth, HealthStatus
from app.health.domain.ports import HealthCheckPort


class _SchedulerCheck(HealthCheckPort):
    critical = False

    def __init__(
        self,
        name: str,
        is_running: Callable[[], bool],
    ) -> None:
        self.name = name
        self._is_running = is_running

    async def check(self) -> ComponentHealth:
        start = time.monotonic()
        try:
            running = bool(self._is_running())
        except Exception as exc:  # noqa: BLE001 — port contract
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                critical=self.critical,
                message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000.0,
            )
        latency_ms = (time.monotonic() - start) * 1000.0
        if running:
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.HEALTHY,
                critical=self.critical,
                latency_ms=latency_ms,
                metadata={"running": True},
            )
        return ComponentHealth(
            name=self.name,
            status=HealthStatus.DEGRADED,
            critical=self.critical,
            message="scheduler not running",
            latency_ms=latency_ms,
            metadata={"running": False},
        )


class BackupSchedulerHealthCheck(_SchedulerCheck):
    """Pulls ``is_running`` lazily so a not-yet-initialised holder
    surfaces as UNHEALTHY rather than raising at import time."""

    def __init__(self) -> None:
        super().__init__(name="backup_scheduler", is_running=_backup_running)


class VersionUpdateSchedulerHealthCheck(_SchedulerCheck):
    def __init__(self) -> None:
        super().__init__(
            name="version_update_scheduler",
            is_running=_version_update_running,
        )


def _backup_running() -> bool:
    # Late import: ``backup_scheduler_instance`` is populated during
    # lifespan startup; importing at module load time would race the
    # `_initialize_backup_scheduler()` step.
    from app.backups import backup_scheduler_instance

    return bool(backup_scheduler_instance.get().is_running)


def _version_update_running() -> bool:
    from app.versions.scheduler import version_update_scheduler

    return bool(version_update_scheduler.is_running)
