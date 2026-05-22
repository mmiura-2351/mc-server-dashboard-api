"""WebSocket monitoring health check.

Reports whether the background ``WebSocketService._status_monitor_task``
is alive. The probe uses the public ``is_monitoring()`` getter
introduced by this change — adapters MUST NOT reach into the
service's private state.
"""

from __future__ import annotations

import time

from app.health.domain.entities import ComponentHealth, HealthStatus
from app.health.domain.ports import HealthCheckPort


class WebSocketHealthCheck(HealthCheckPort):
    name = "websocket_service"
    critical = False

    async def check(self) -> ComponentHealth:
        start = time.monotonic()
        try:
            from app.websockets.application.service import websocket_service

            monitoring = websocket_service.is_monitoring()
        except Exception as exc:  # noqa: BLE001 — port contract
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                critical=self.critical,
                message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000.0,
            )
        latency_ms = (time.monotonic() - start) * 1000.0
        if monitoring:
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.HEALTHY,
                critical=self.critical,
                latency_ms=latency_ms,
                metadata={"monitoring": True},
            )
        return ComponentHealth(
            name=self.name,
            status=HealthStatus.DEGRADED,
            critical=self.critical,
            message="monitor task not running",
            latency_ms=latency_ms,
            metadata={"monitoring": False},
        )
