"""HealthCheckService — aggregates per-component probes.

Responsibilities:

* Run every registered ``HealthCheckPort`` with a per-component
  timeout so a single slow check cannot block the whole probe.
* Cache the last aggregated result for a short TTL — k8s probes us at
  ~1 Hz and a flood of liveness traffic should not amplify into a
  flood of database connections.
* Provide a separate liveness path that does *not* touch dependencies
  (kubelet liveness probes must remain cheap and self-contained).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.health.domain.entities import (
    ComponentHealth,
    HealthStatus,
    OverallHealth,
    aggregate,
)
from app.health.domain.ports import HealthCheckPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthCheckConfig:
    """Service-level knobs.

    All values come from ``app.core.config.settings`` — this dataclass
    just bundles them so the service stays decoupled from pydantic.
    """

    per_component_timeout_seconds: float = 2.0
    global_timeout_seconds: float = 5.0
    cache_ttl_seconds: float = 2.0


class HealthCheckService:
    """Composes ``HealthCheckPort`` adapters into an ``OverallHealth``.

    The service is meant to be instantiated once per process (it owns
    the cache). Tests should construct a fresh instance per scenario.
    """

    def __init__(
        self,
        checks: Sequence[HealthCheckPort],
        config: HealthCheckConfig | None = None,
    ) -> None:
        self._checks = list(checks)
        self._config = config or HealthCheckConfig()
        # Cache stores ``(monotonic_timestamp, OverallHealth)`` so
        # eviction stays oblivious to wall-clock jumps.
        self._cache: tuple[float, OverallHealth] | None = None
        self._cache_lock = asyncio.Lock()

    @property
    def config(self) -> HealthCheckConfig:
        return self._config

    @property
    def checks(self) -> list[HealthCheckPort]:
        """Expose registered checks for debugging / introspection."""
        return list(self._checks)

    def liveness(self) -> OverallHealth:
        """Cheap synchronous liveness signal.

        Returns ``HEALTHY`` as long as the process is responsive enough
        to execute Python. No dependency I/O is performed. The
        component list is intentionally empty — ``/healthz`` only needs
        the top-level status code.
        """
        now = datetime.now(timezone.utc)
        return OverallHealth(
            status=HealthStatus.HEALTHY,
            components=[],
            checked_at=now,
        )

    async def readiness(self, *, use_cache: bool = True) -> OverallHealth:
        """Run every registered check and return the aggregate.

        Args:
            use_cache: ``True`` (default) honours the configured TTL;
                ``False`` forces a fresh evaluation (used by
                ``/api/v1/health/detail`` so admins always see live
                data when debugging).
        """
        if use_cache:
            cached = self._read_cache()
            if cached is not None:
                return cached

        async with self._cache_lock:
            # Re-check after acquiring the lock — another coroutine
            # may have populated the cache while we waited.
            if use_cache:
                cached = self._read_cache()
                if cached is not None:
                    return cached

            components = await self._run_all()
            overall = OverallHealth(
                status=aggregate(components),
                components=components,
                checked_at=datetime.now(timezone.utc),
            )
            self._cache = (time.monotonic(), overall)
            return overall

    def _read_cache(self) -> OverallHealth | None:
        if self._cache is None:
            return None
        stored_at, value = self._cache
        if (time.monotonic() - stored_at) <= self._config.cache_ttl_seconds:
            return value
        return None

    async def _run_all(self) -> list[ComponentHealth]:
        """Run all checks concurrently with a global guardrail.

        Each probe is also wrapped in its own ``wait_for`` so a slow
        adapter degrades gracefully without dragging down its peers.
        """

        async def _run_one(check: HealthCheckPort) -> ComponentHealth:
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    check.check(),
                    timeout=self._config.per_component_timeout_seconds,
                )
                return result
            except asyncio.TimeoutError:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                logger.warning(
                    "Health check timed out: name=%s timeout=%.2fs",
                    check.name,
                    self._config.per_component_timeout_seconds,
                )
                return ComponentHealth(
                    name=check.name,
                    status=HealthStatus.UNHEALTHY,
                    critical=check.critical,
                    message=(
                        f"timeout after {self._config.per_component_timeout_seconds:.2f}s"
                    ),
                    latency_ms=elapsed_ms,
                )
            except Exception as exc:  # noqa: BLE001 — adapter contract
                # Adapters SHOULD NOT raise (see HealthCheckPort
                # contract); if one does, surface the failure rather
                # than poisoning the whole probe.
                elapsed_ms = (time.monotonic() - start) * 1000.0
                logger.exception("Health check raised unexpectedly: name=%s", check.name)
                return ComponentHealth(
                    name=check.name,
                    status=HealthStatus.UNHEALTHY,
                    critical=check.critical,
                    message=f"{type(exc).__name__}: {exc}",
                    latency_ms=elapsed_ms,
                )

        try:
            return await asyncio.wait_for(
                asyncio.gather(*[_run_one(c) for c in self._checks]),
                timeout=self._config.global_timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Global guardrail tripped — synthesize an UNHEALTHY
            # component per registered check so the response still
            # carries useful diagnostic shape.
            logger.error(
                "Global health check timed out after %.2fs",
                self._config.global_timeout_seconds,
            )
            return [
                ComponentHealth(
                    name=check.name,
                    status=HealthStatus.UNHEALTHY,
                    critical=check.critical,
                    message=(
                        f"global timeout after {self._config.global_timeout_seconds:.2f}s"
                    ),
                )
                for check in self._checks
            ]
