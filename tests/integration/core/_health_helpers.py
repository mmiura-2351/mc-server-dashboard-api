"""Test helpers for the legacy ``/health`` / ``/api/v1/health`` endpoints.

Post-#21 the legacy endpoints delegate to ``HealthCheckService`` while
keeping their pre-existing wire format. These helpers build canned
component fixtures and the ``override_health_service`` context
manager that swaps the FastAPI dependency for the duration of a test.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Iterator

from app.health.api.dependencies import get_health_check_service
from app.health.application.service import HealthCheckConfig, HealthCheckService
from app.health.domain.entities import (
    ComponentHealth,
    HealthStatus,
    OverallHealth,
    aggregate,
)
from app.main import app


class _StubService(HealthCheckService):
    def __init__(self, overall: OverallHealth) -> None:
        super().__init__(
            checks=[],
            config=HealthCheckConfig(
                per_component_timeout_seconds=1.0,
                global_timeout_seconds=2.0,
                cache_ttl_seconds=0.0,
            ),
        )
        self._overall = overall

    async def readiness(self, *, use_cache: bool = True) -> OverallHealth:
        return self._overall


@contextmanager
def override_health_service(
    components: Iterable[ComponentHealth],
) -> Iterator[None]:
    """Override ``get_health_check_service`` for the duration of a test."""
    comp_list = list(components)
    overall = OverallHealth(
        status=aggregate(comp_list),
        components=comp_list,
        checked_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_health_check_service] = lambda: _StubService(overall)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_health_check_service, None)


def unhealthy_database_components() -> list[ComponentHealth]:
    return [
        ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            critical=True,
            message="connection refused",
        ),
        ComponentHealth(name="filesystem", status=HealthStatus.HEALTHY, critical=True),
    ]


def partial_failure_components() -> list[ComponentHealth]:
    """Database healthy, two non-critical subsystems down."""
    return [
        ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True),
        ComponentHealth(name="filesystem", status=HealthStatus.HEALTHY, critical=True),
        ComponentHealth(
            name="database_integration",
            status=HealthStatus.DEGRADED,
            critical=False,
        ),
        ComponentHealth(
            name="backup_scheduler",
            status=HealthStatus.DEGRADED,
            critical=False,
        ),
    ]
