"""Prometheus exposition endpoint (`/metrics`).

Phase 2 of Issue #21 / #329. We export two families of metrics:

1. **Health gauges** — re-projects the per-component results from the
   existing `HealthCheckService` so dashboards and alerting can use
   the same probes that drive the k8s readiness probe.
2. **Business gauges** — counts of servers / pending backups / active
   account lockouts, refreshed on every scrape via
   `BusinessMetricsCollector`.

Counters (cumulative) live alongside the gauges so they participate
in the same `/metrics` page. Currently we ship `mc_login_attempts_total`
which is incremented from the brute-force service whenever an
authentication attempt is processed.

The endpoint is intentionally **unauthenticated** — that is the
Prometheus convention. Network-layer ACLs (k8s `NetworkPolicy`, GCP
firewall rules, etc.) are expected to gate scraping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.health.api.dependencies import get_health_check_service
from app.health.application.metrics_collector import BusinessMetricsCollector
from app.health.application.service import HealthCheckService
from app.health.domain.entities import HealthStatus, OverallHealth

metrics_router = APIRouter()


# ---------------------------------------------------------------------------
# Health-derived metrics
# ---------------------------------------------------------------------------
#
# The numeric encoding mirrors the traffic-light convention used in
# the domain (`HealthStatus`): higher = better. Picking 0/1/2 lets
# operators write alerting rules like `min_over_time(...) < 2` to
# catch any non-HEALTHY sample in a window.

_STATUS_VALUE: Mapping[HealthStatus, int] = {
    HealthStatus.UNHEALTHY: 0,
    HealthStatus.DEGRADED: 1,
    HealthStatus.HEALTHY: 2,
}

health_component_status = Gauge(
    "mc_health_component_status",
    (
        "Per-component health status: 0=unhealthy, 1=degraded, 2=healthy. "
        "Mirrors the components exposed by /api/v1/health/detail."
    ),
    ["component", "critical"],
)

health_component_latency_seconds = Gauge(
    "mc_health_component_check_duration_seconds",
    "Latency of the most recent successful per-component health check, in seconds.",
    ["component"],
)


# ---------------------------------------------------------------------------
# Counters (cumulative). These are incremented from the producing
# domain (e.g. the auth brute-force service) and read by the scrape
# handler via the default registry.
# ---------------------------------------------------------------------------

login_attempts_total = Counter(
    "mc_login_attempts_total",
    "Authentication attempts grouped by outcome.",
    ["result"],
)


def _refresh_health_metrics(overall: OverallHealth) -> None:
    """Project ``OverallHealth`` into the Prometheus gauges."""
    for component in overall.components:
        health_component_status.labels(
            component=component.name,
            critical=str(component.critical).lower(),
        ).set(_STATUS_VALUE[component.status])

        if component.latency_ms is not None:
            health_component_latency_seconds.labels(component=component.name).set(
                component.latency_ms / 1000.0
            )


def _resolve_backups_directory() -> Path:
    """Late-bind to avoid importing the backups package at module load."""
    return Path("backups")


@metrics_router.get(
    "/metrics",
    include_in_schema=False,
    response_class=Response,
)
async def metrics(
    service: HealthCheckService = Depends(get_health_check_service),
    db: Session = Depends(get_db),
) -> Response:
    """Render the Prometheus exposition payload.

    Bypasses the health-service TTL cache so each scrape returns a
    fresh snapshot — Prometheus already controls scrape cadence via
    its own `scrape_interval`, and we do not want to compound that
    with an in-process cache that could quietly stale.
    """
    overall = await service.readiness(use_cache=False)
    _refresh_health_metrics(overall)

    collector = BusinessMetricsCollector(
        db=db,
        backups_directory=_resolve_backups_directory(),
    )
    collector.collect()

    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


__all__ = [
    "health_component_latency_seconds",
    "health_component_status",
    "login_attempts_total",
    "metrics_router",
]
