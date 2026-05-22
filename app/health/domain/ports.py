"""Ports exposed by the health domain.

The single ``HealthCheckPort`` is intentionally tiny: each component
adapter implements ``check()`` returning a ``ComponentHealth``. The
application service composes them, applies per-component timeouts,
and aggregates results.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.health.domain.entities import ComponentHealth


@runtime_checkable
class HealthCheckPort(Protocol):
    """Single-component health probe.

    Implementations MUST NOT raise — translate failures into a
    ``ComponentHealth`` carrying ``HealthStatus.UNHEALTHY`` and a
    diagnostic ``message``. The aggregating service relies on this
    invariant to avoid one flaky adapter taking down the whole probe.
    """

    name: str
    critical: bool

    async def check(self) -> ComponentHealth: ...
