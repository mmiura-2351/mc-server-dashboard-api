"""Pydantic DTOs for the health/readiness endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field

from app.health.domain.entities import HealthStatus


class ComponentHealthResponse(BaseModel):
    name: str
    status: HealthStatus
    critical: bool
    message: Optional[str] = None
    latency_ms: Optional[float] = None
    checked_at: datetime
    metadata: Mapping[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Standard response shape for liveness / readiness / detail."""

    status: HealthStatus
    checked_at: datetime
    components: list[ComponentHealthResponse] = Field(default_factory=list)


class LegacyHealthResponse(BaseModel):
    """Back-compat shape returned by ``/health`` and ``/api/v1/health``.

    Matches the structure emitted by the pre-#21 endpoints so existing
    dashboards keep working. Internally the values come from the new
    ``HealthCheckService``, but the wire format does not change.
    """

    status: str
    timestamp: datetime
    services: dict[str, str]
    failed_services: list[str]
    message: str
