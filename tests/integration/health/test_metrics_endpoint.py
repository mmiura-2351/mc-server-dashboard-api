"""Integration tests for the Prometheus `/metrics` endpoint (Issue #329).

The endpoint is mounted on the live FastAPI app; we stub the
`HealthCheckService` so the health gauges have deterministic
component shapes regardless of the real adapter state.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from prometheus_client import CONTENT_TYPE_LATEST

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
    """Bypass real adapters with a pre-computed ``OverallHealth``."""

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


def _override(components: list[ComponentHealth]) -> None:
    overall = OverallHealth(
        status=aggregate(components),
        components=components,
        checked_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_health_check_service] = lambda: _StubService(overall)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_health_check_service, None)


def test_metrics_endpoint_returns_prometheus_content_type(client) -> None:
    _override(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                critical=True,
                latency_ms=12.5,
            )
        ]
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    # `CONTENT_TYPE_LATEST` includes encoding / version params; the
    # endpoint should hand it back verbatim so scrapers do not have
    # to parse a non-standard content type.
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST


def test_metrics_endpoint_exposes_health_component_gauges(client) -> None:
    _override(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                critical=True,
                latency_ms=15.0,
            ),
            ComponentHealth(
                name="backup_scheduler",
                status=HealthStatus.DEGRADED,
                critical=False,
                latency_ms=5.0,
            ),
        ]
    )

    body = client.get("/metrics").text

    # Health status gauge: HEALTHY=2, DEGRADED=1.
    assert 'mc_health_component_status{component="database",critical="true"} 2.0' in body
    assert (
        'mc_health_component_status{component="backup_scheduler",critical="false"} 1.0'
        in body
    )
    # Latency exported in seconds (ms / 1000).
    assert 'mc_health_component_check_duration_seconds{component="database"}' in body
    assert "0.015" in body


def test_metrics_endpoint_exposes_business_gauges(client) -> None:
    _override(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                critical=True,
                latency_ms=1.0,
            )
        ]
    )

    body = client.get("/metrics").text

    # Every business gauge should appear at least once even when the
    # underlying tables are empty.
    assert "mc_servers_total" in body
    assert "mc_backups_pending_total" in body
    assert "mc_account_lockouts_active" in body
    # The login counter is registered eagerly via module import.
    assert "mc_login_attempts_total" in body


def test_metrics_endpoint_unauthenticated(client) -> None:
    """Prometheus scrape convention: no auth required."""
    _override(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                critical=True,
            )
        ]
    )
    # No Authorization header at all.
    response = client.get("/metrics")
    assert response.status_code == 200
