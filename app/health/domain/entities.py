"""Framework-agnostic health entities.

Three statuses model the typical traffic-light readiness convention:

* ``HEALTHY``    — the component answered within its budget.
* ``DEGRADED``   — the component answered but reported a non-fatal
  warning (e.g. a non-critical scheduler is not running).
* ``UNHEALTHY``  — the component failed or timed out.

``OverallHealth.status`` is derived from the worst component status,
constrained by ``critical``:

* any critical component ``UNHEALTHY`` => overall ``UNHEALTHY``
* otherwise, if any component ``UNHEALTHY`` or ``DEGRADED`` => overall
  ``DEGRADED``
* else ``HEALTHY``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


_EMPTY_METADATA: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class ComponentHealth:
    """Result of a single ``HealthCheckPort.check()`` invocation."""

    name: str
    status: HealthStatus
    critical: bool
    message: str | None = None
    latency_ms: float | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_METADATA)


@dataclass(frozen=True)
class OverallHealth:
    """Aggregate readiness result returned by ``HealthCheckService``."""

    status: HealthStatus
    components: list[ComponentHealth]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_ready(self) -> bool:
        """True iff no critical component is unhealthy.

        Used by ``/readyz`` to decide between 200 and 503. Degraded
        non-critical components keep the probe at 200 so kubelet does
        not yank traffic during a transient backup-scheduler hiccup.
        """
        return not any(
            c.critical and c.status is HealthStatus.UNHEALTHY for c in self.components
        )


def aggregate(components: list[ComponentHealth]) -> HealthStatus:
    """Reduce per-component statuses to an overall status.

    See module docstring for the rules.
    """
    if any(c.critical and c.status is HealthStatus.UNHEALTHY for c in components):
        return HealthStatus.UNHEALTHY
    if any(
        c.status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED) for c in components
    ):
        return HealthStatus.DEGRADED
    return HealthStatus.HEALTHY
