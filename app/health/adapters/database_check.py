"""Database connectivity health check.

Issues ``SELECT 1`` against the configured engine so we exercise the
real connection pool the rest of the app uses (not just process-level
liveness). Marked ``critical`` so a ``SELECT 1`` failure flips
``/readyz`` to 503 — the app is useless without its database.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.health.domain.entities import ComponentHealth, HealthStatus
from app.health.domain.ports import HealthCheckPort


class DatabaseHealthCheck(HealthCheckPort):
    name = "database"
    critical = True

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def check(self) -> ComponentHealth:
        # ``Engine.connect()`` is synchronous; offload to the default
        # executor so we do not block the event loop while the pool
        # may be exhausted.
        start = time.monotonic()
        try:
            await asyncio.to_thread(self._probe)
        except Exception as exc:  # noqa: BLE001 — port contract
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                critical=self.critical,
                message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000.0,
            )
        return ComponentHealth(
            name=self.name,
            status=HealthStatus.HEALTHY,
            critical=self.critical,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )

    def _probe(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
