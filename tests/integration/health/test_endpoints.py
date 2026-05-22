"""Integration tests for the health/readiness endpoints.

Uses ``app.dependency_overrides`` to swap the ``HealthCheckService``
for a stub whose readiness payload we control directly. This avoids
flakiness from probing real schedulers / WebSocket task state during
unit-style integration tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import pytest

from app.health.api.dependencies import get_health_check_service
from app.health.application.service import HealthCheckConfig, HealthCheckService
from app.health.domain.entities import (
    ComponentHealth,
    HealthStatus,
    OverallHealth,
)
from app.main import app


class _StubService(HealthCheckService):
    """Minimal stub: pre-computed ``OverallHealth`` short-circuits readiness."""

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


def _make_overall(*components: ComponentHealth) -> OverallHealth:
    from app.health.domain.entities import aggregate

    return OverallHealth(
        status=aggregate(list(components)),
        components=list(components),
        checked_at=datetime.now(timezone.utc),
    )


def _override_with(components: Sequence[ComponentHealth]):
    overall = _make_overall(*components)
    app.dependency_overrides[get_health_check_service] = lambda: _StubService(overall)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_health_check_service, None)


# ---------------------------------------------------------------------------
# /healthz — liveness
# ---------------------------------------------------------------------------


def test_healthz_returns_200_without_db_check(client):
    # Even with a failing DB stub, liveness must not run readiness.
    _override_with(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                critical=True,
            )
        ]
    )
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["components"] == []


# ---------------------------------------------------------------------------
# /readyz and its alias /ready
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/readyz", "/ready"])
def test_readiness_200_when_all_healthy(client, path):
    _override_with(
        [
            ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(
                name="filesystem", status=HealthStatus.HEALTHY, critical=True
            ),
        ]
    )
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert {c["name"] for c in body["components"]} == {"database", "filesystem"}


@pytest.mark.parametrize("path", ["/readyz", "/ready"])
def test_readiness_503_when_critical_fails(client, path):
    _override_with(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                critical=True,
                message="connection refused",
            ),
        ]
    )
    response = client.get(path)
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"


@pytest.mark.parametrize("path", ["/readyz", "/ready"])
def test_readiness_200_when_only_non_critical_fails(client, path):
    _override_with(
        [
            ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(
                name="backup_scheduler",
                status=HealthStatus.DEGRADED,
                critical=False,
            ),
        ]
    )
    response = client.get(path)
    # Non-critical degradation does not flip status code to 503.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# /api/v1/health/detail — admin only
# ---------------------------------------------------------------------------


def test_detail_requires_auth(client):
    response = client.get("/api/v1/health/detail")
    assert response.status_code in (401, 403)


def test_detail_rejects_non_admin(client, user_headers):
    _override_with(
        [ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True)]
    )
    response = client.get("/api/v1/health/detail", headers=user_headers)
    assert response.status_code == 403


def test_detail_allows_admin(client, admin_headers):
    _override_with(
        [
            ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(
                name="backup_scheduler",
                status=HealthStatus.DEGRADED,
                critical=False,
                message="not running",
            ),
        ]
    )
    response = client.get("/api/v1/health/detail", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    names = {c["name"] for c in body["components"]}
    assert names == {"database", "backup_scheduler"}
    # Detail endpoint returns 200 even with degraded components so
    # admins can inspect a failing system; the body carries the state.
    assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# Legacy /health and /api/v1/health — wire format preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_legacy_health_shape_when_healthy(client, path):
    _override_with(
        [
            ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(
                name="filesystem", status=HealthStatus.HEALTHY, critical=True
            ),
            ComponentHealth(
                name="database_integration",
                status=HealthStatus.HEALTHY,
                critical=False,
            ),
            ComponentHealth(
                name="backup_scheduler",
                status=HealthStatus.HEALTHY,
                critical=False,
            ),
            ComponentHealth(
                name="websocket_service",
                status=HealthStatus.HEALTHY,
                critical=False,
            ),
            ComponentHealth(
                name="version_update_scheduler",
                status=HealthStatus.HEALTHY,
                critical=False,
            ),
        ]
    )
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["services"]["database"] == "operational"
    assert body["services"]["backup_scheduler"] == "operational"
    assert body["failed_services"] == []
    assert "All services operational" in body["message"]


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_legacy_health_503_when_db_fails(client, path):
    _override_with(
        [
            ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                critical=True,
            ),
        ]
    )
    response = client.get(path)
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "database" in body["failed_services"]


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_legacy_health_200_when_only_non_critical_fails(client, path):
    _override_with(
        [
            ComponentHealth(name="database", status=HealthStatus.HEALTHY, critical=True),
            ComponentHealth(
                name="backup_scheduler",
                status=HealthStatus.UNHEALTHY,
                critical=False,
            ),
        ]
    )
    response = client.get(path)
    # Pre-#21 behaviour: DB-up means 200 even if subsystems failed.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["services"]["backup_scheduler"] == "failed"
    assert body["failed_services"] == ["backup_scheduler"]
