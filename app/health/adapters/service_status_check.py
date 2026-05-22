"""Bridge from the legacy ``ServiceStatus`` tracker to ``HealthCheckPort``.

``ServiceStatus`` (in ``app.main``) tracks which startup phases
succeeded during lifespan. We mirror its
``database_integration_ready`` flag into a health component so the
detail endpoint can show *both* live readiness (from
``DatabaseHealthCheck``) and startup readiness (from the legacy
tracker).
"""

from __future__ import annotations

import time
from typing import Callable

from app.health.domain.entities import ComponentHealth, HealthStatus
from app.health.domain.ports import HealthCheckPort


class DatabaseIntegrationHealthCheck(HealthCheckPort):
    """Read-only mirror of ``service_status.database_integration_ready``.

    The flag flips at the end of ``_initialize_database_integration``
    and never moves again, so we treat ``False`` as ``DEGRADED`` (the
    rest of the app still works without it) rather than failing the
    probe outright.
    """

    name = "database_integration"
    critical = False

    def __init__(self, get_ready: Callable[[], bool]) -> None:
        self._get_ready = get_ready

    async def check(self) -> ComponentHealth:
        start = time.monotonic()
        try:
            ready = bool(self._get_ready())
        except Exception as exc:  # noqa: BLE001 — port contract
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                critical=self.critical,
                message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000.0,
            )
        latency_ms = (time.monotonic() - start) * 1000.0
        if ready:
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.HEALTHY,
                critical=self.critical,
                latency_ms=latency_ms,
                metadata={"ready": True},
            )
        return ComponentHealth(
            name=self.name,
            status=HealthStatus.DEGRADED,
            critical=self.critical,
            message="database integration not initialised",
            latency_ms=latency_ms,
            metadata={"ready": False},
        )
