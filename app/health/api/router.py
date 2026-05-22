"""Health / readiness HTTP router.

Endpoint matrix (see PR description for the full table):

* ``GET /healthz``                 — k8s liveness, no DB I/O.
* ``GET /readyz`` / ``GET /ready`` — k8s readiness (alias), runs all
  registered checks.
* ``GET /api/v1/health/detail``    — admin-only verbose report.

The legacy back-compat endpoints (``/health`` and ``/api/v1/health``)
live in ``app.main`` so existing imports keep working; they now
delegate to ``HealthCheckService`` via ``build_legacy_payload``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth.dependencies import get_current_user
from app.health.api.dependencies import get_health_check_service
from app.health.api.schemas import (
    ComponentHealthResponse,
    HealthResponse,
    LegacyHealthResponse,
)
from app.health.application.service import HealthCheckService
from app.health.domain.entities import HealthStatus, OverallHealth
from app.servers.application.authorization import AuthorizationService
from app.users.models import User

router = APIRouter(tags=["health"])


def _to_response(overall: OverallHealth) -> HealthResponse:
    return HealthResponse(
        status=overall.status,
        checked_at=overall.checked_at,
        components=[
            ComponentHealthResponse(
                name=c.name,
                status=c.status,
                critical=c.critical,
                message=c.message,
                latency_ms=c.latency_ms,
                checked_at=c.checked_at,
                metadata=dict(c.metadata),
            )
            for c in overall.components
        ],
    )


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Kubernetes liveness probe",
)
async def liveness(
    service: HealthCheckService = Depends(get_health_check_service),
) -> HealthResponse:
    """Cheap liveness probe — never touches the database."""
    return _to_response(service.liveness())


async def _readiness_response(service: HealthCheckService) -> Response:
    overall = await service.readiness()
    payload = _to_response(overall).model_dump(mode="json")
    status_code = 200 if overall.is_ready else 503
    return Response(
        content=json.dumps(payload),
        status_code=status_code,
        media_type="application/json",
    )


@router.get(
    "/readyz",
    summary="Kubernetes readiness probe",
    responses={200: {"model": HealthResponse}, 503: {"model": HealthResponse}},
)
async def readiness(
    service: HealthCheckService = Depends(get_health_check_service),
) -> Response:
    """Aggregates every registered check; 503 if any critical component fails."""
    return await _readiness_response(service)


@router.get(
    "/ready",
    summary="Readiness probe (alias of /readyz)",
    responses={200: {"model": HealthResponse}, 503: {"model": HealthResponse}},
)
async def readiness_alias(
    service: HealthCheckService = Depends(get_health_check_service),
) -> Response:
    return await _readiness_response(service)


@router.get(
    "/api/v1/health/detail",
    response_model=HealthResponse,
    summary="Detailed health report (admin only)",
)
async def health_detail(
    current_user: User = Depends(get_current_user),
    service: HealthCheckService = Depends(get_health_check_service),
) -> HealthResponse:
    """Admin-only verbose report.

    Bypasses the TTL cache so the operator always sees live data, and
    returns 200 regardless of readiness — the response body carries
    the diagnostic status so admins can inspect a failing system
    without the 503 short-circuiting downstream tooling.
    """
    if not AuthorizationService.is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only administrators can view detailed health data",
        )
    overall = await service.readiness(use_cache=False)
    return _to_response(overall)


# ---------------------------------------------------------------------------
# Legacy back-compat helper
# ---------------------------------------------------------------------------


_LEGACY_NAME_MAP = {
    "database": "database",
    "database_integration": "database_integration",
    "backup_scheduler": "backup_scheduler",
    "websocket_service": "websocket_service",
    "version_update_scheduler": "version_update_scheduler",
}


async def build_legacy_payload(service: HealthCheckService) -> tuple[dict[str, Any], int]:
    """Render an ``OverallHealth`` into the pre-#21 ``LegacyHealthResponse`` shape.

    Returns ``(payload, status_code)``. The status code rules match
    the previous implementation: 503 when the database (the only
    truly critical component) is failing, 200 otherwise — including
    ``status="degraded"``.
    """
    overall = await service.readiness()
    by_name = {c.name: c for c in overall.components}

    services: dict[str, str] = {}
    failed_services: list[str] = []
    for legacy_key, component_name in _LEGACY_NAME_MAP.items():
        component = by_name.get(component_name)
        if component is None or component.status is HealthStatus.HEALTHY:
            services[legacy_key] = "operational"
        else:
            services[legacy_key] = "failed"
            failed_services.append(legacy_key)

    db_component = by_name.get("database")
    db_healthy = db_component is not None and db_component.status is HealthStatus.HEALTHY

    if db_healthy:
        top_status = "healthy"
        message = (
            "All services operational"
            if not failed_services
            else "Running with degraded functionality: " + ", ".join(failed_services)
        )
        status_code = 200
    else:
        top_status = "degraded"
        message = (
            "Running with degraded functionality: " + ", ".join(failed_services)
            if failed_services
            else "Database unavailable"
        )
        status_code = 503

    payload = LegacyHealthResponse(
        status=top_status,
        timestamp=datetime.now(timezone.utc),
        services=services,
        failed_services=failed_services,
        message=message,
    ).model_dump(mode="json")
    return payload, status_code
