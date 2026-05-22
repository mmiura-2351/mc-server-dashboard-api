"""Filesystem writability health check.

Validates that the ``servers/`` and ``backups/`` directories are
present and writable. We probe with ``os.access(W_OK)`` rather than
actually touching a file because:

* probes happen on every ``/readyz`` call; even nanosecond-grade write
  amplification adds up;
* the underlying file systems may be network mounts where an actual
  ``open(...,"w")`` would have side effects (e.g. atime updates).

The detailed endpoint (``/api/v1/health/detail``) can opt into a
real write test through ``probe_writability=True``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

from app.health.domain.entities import ComponentHealth, HealthStatus
from app.health.domain.ports import HealthCheckPort


class FilesystemHealthCheck(HealthCheckPort):
    name = "filesystem"
    critical = True

    def __init__(
        self,
        paths: list[Path] | None = None,
        *,
        probe_writability: bool = False,
    ) -> None:
        self._paths = paths or [Path("servers"), Path("backups")]
        self._probe_writability = probe_writability

    async def check(self) -> ComponentHealth:
        start = time.monotonic()
        try:
            failing: list[str] = []
            await asyncio.to_thread(self._inspect, failing)
        except Exception as exc:  # noqa: BLE001 — port contract
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                critical=self.critical,
                message=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.monotonic() - start) * 1000.0,
            )

        latency_ms = (time.monotonic() - start) * 1000.0
        if failing:
            return ComponentHealth(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                critical=self.critical,
                message="; ".join(failing),
                latency_ms=latency_ms,
                metadata={"failing_paths": failing},
            )
        return ComponentHealth(
            name=self.name,
            status=HealthStatus.HEALTHY,
            critical=self.critical,
            latency_ms=latency_ms,
            metadata={"paths": [str(p) for p in self._paths]},
        )

    def _inspect(self, failing: list[str]) -> None:
        for p in self._paths:
            if not p.exists():
                failing.append(f"{p}: missing")
                continue
            if not p.is_dir():
                failing.append(f"{p}: not a directory")
                continue
            if not os.access(p, os.W_OK):
                failing.append(f"{p}: not writable (os.access W_OK)")
                continue
            if self._probe_writability:
                # Best-effort real write probe (used by /health/detail).
                try:
                    with tempfile.NamedTemporaryFile(dir=p, delete=True):
                        pass
                except OSError as exc:
                    failing.append(f"{p}: write probe failed ({exc})")
