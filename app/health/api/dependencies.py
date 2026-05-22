"""FastAPI dependency wiring for the health domain.

A single module-level ``HealthCheckService`` instance is cached
between requests so the in-memory TTL cache survives — k8s probes
hit at ~1 Hz and re-instantiating per request would defeat the
point.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.database import engine
from app.health.adapters.database_check import DatabaseHealthCheck
from app.health.adapters.filesystem_check import FilesystemHealthCheck
from app.health.adapters.scheduler_check import (
    BackupSchedulerHealthCheck,
    VersionUpdateSchedulerHealthCheck,
)
from app.health.adapters.service_status_check import DatabaseIntegrationHealthCheck
from app.health.adapters.websocket_check import WebSocketHealthCheck
from app.health.application.service import HealthCheckConfig, HealthCheckService


def _build_config() -> HealthCheckConfig:
    return HealthCheckConfig(
        per_component_timeout_seconds=settings.HEALTH_CHECK_PER_COMPONENT_TIMEOUT_SECONDS,
        global_timeout_seconds=settings.HEALTH_CHECK_GLOBAL_TIMEOUT_SECONDS,
        cache_ttl_seconds=settings.HEALTH_CHECK_CACHE_TTL_SECONDS,
    )


def _resolve_database_integration_ready() -> bool:
    """Late-bind to ``app.main.service_status`` to avoid an import
    cycle (``app.main`` already imports ``app.health.api.router``).
    """
    from app.main import service_status

    return bool(service_status.database_integration_ready)


@lru_cache(maxsize=1)
def get_health_check_service() -> HealthCheckService:
    """Return the process-wide ``HealthCheckService`` singleton.

    Lazy construction means tests can swap the adapters via
    ``app.dependency_overrides`` without paying for unused probes.
    """
    return HealthCheckService(
        checks=[
            DatabaseHealthCheck(engine),
            FilesystemHealthCheck(
                paths=[Path("servers"), Path("backups")],
                probe_writability=False,
            ),
            DatabaseIntegrationHealthCheck(_resolve_database_integration_ready),
            BackupSchedulerHealthCheck(),
            WebSocketHealthCheck(),
            VersionUpdateSchedulerHealthCheck(),
        ],
        config=_build_config(),
    )


def reset_health_check_service_cache() -> None:
    """Reset the singleton — used by tests that mutate settings."""
    get_health_check_service.cache_clear()
