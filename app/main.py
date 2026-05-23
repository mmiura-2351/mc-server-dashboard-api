import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import settings
from app.core.logging import configure_logging

# Configure structured logging as early as possible so any module-level
# logger created during the imports below picks up the right handlers /
# formatters (issue #24).
configure_logging(settings)

from app.audit.router import router as audit_router  # noqa: E402
from app.auth.api.router import router as auth_router  # noqa: E402

# Import models to ensure they are registered with SQLAlchemy
from app.backups.router import router as backups_router  # noqa: E402
from app.backups.scheduler_router import router as scheduler_router  # noqa: E402
from app.core.database import Base, engine  # noqa: E402
from app.core.error_handlers import register_exception_handlers  # noqa: E402

# Import visibility models for Phase 2 resource access control
from app.core.visibility_router import router as visibility_router  # noqa: E402
from app.files.router import router as files_router  # noqa: E402
from app.groups.router import router as groups_router  # noqa: E402
from app.health.api.dependencies import get_health_check_service  # noqa: E402
from app.health.api.router import build_legacy_payload  # noqa: E402
from app.health.api.router import router as health_router  # noqa: E402
from app.health.application.service import HealthCheckService  # noqa: E402
from app.middleware.audit_middleware import AuditMiddleware  # noqa: E402
from app.middleware.performance_monitoring import (  # noqa: E402
    PerformanceMonitoringMiddleware,
    get_performance_metrics,
)
from app.servers.routers import router as servers_router  # noqa: E402
from app.templates.router import router as templates_router  # noqa: E402

# Import all models to ensure they are registered with SQLAlchemy
from app.users.api.router import router as users_router  # noqa: E402
from app.versions.api.router import router as versions_router  # noqa: E402
from app.websockets.router import router as websockets_router  # noqa: E402

logger = logging.getLogger(__name__)


class ServiceStatus:
    """Track service initialization status for graceful degradation"""

    def __init__(self):
        self.database_ready = False
        self.database_integration_ready = False
        self.backup_scheduler_ready = False
        self.websocket_service_ready = False
        self.version_update_scheduler_ready = False
        self.failed_services = []

    def is_healthy(self) -> bool:
        """Check if core services are healthy"""
        return self.database_ready

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive service status"""
        return {
            "database": self.database_ready,
            "database_integration": self.database_integration_ready,
            "backup_scheduler": self.backup_scheduler_ready,
            "websocket_service": self.websocket_service_ready,
            "version_update_scheduler": self.version_update_scheduler_ready,
            "failed_services": self.failed_services,
            "healthy": self.is_healthy(),
        }


# Global service status tracker
service_status = ServiceStatus()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with error handling and graceful degradation"""
    logger.info("Starting application startup sequence...")

    # Initialize services with error handling
    await _initialize_services()

    # Attach service status to app for health checks
    app.state.service_status = service_status

    if service_status.is_healthy():
        logger.info("Application startup completed successfully")
    else:
        logger.warning(
            f"Application started with degraded functionality. "
            f"Failed services: {service_status.failed_services}"
        )

    yield

    # Graceful shutdown with error handling
    await _cleanup_services()
    logger.info("Application shutdown completed")


async def _initialize_services():
    """Initialize all services with proper error handling"""

    # 1. Initialize database (critical - app cannot function without it)
    await _initialize_database()

    # 2. Backfill Phase 2 visibility rows for legacy resources (best-effort)
    await _initialize_visibility_migration()

    # 3. Initialize database integration (important but not critical)
    await _initialize_database_integration()

    # 4. Initialize backup scheduler (optional - can be started later)
    await _initialize_backup_scheduler()

    # 5. Initialize WebSocket service (optional - real-time features)
    await _initialize_websocket_service()

    # 6. Initialize version update scheduler (optional - background updates)
    await _initialize_version_update_scheduler()


async def _initialize_database():
    """Initialize database tables - critical service"""
    try:
        logger.info("Initializing database tables...")
        Base.metadata.create_all(bind=engine)

        # Idempotent migration: add UNIQUE index protecting
        # file_edit_history.version_number against TOCTOU races.
        # Aborts startup if pre-existing duplicates are detected so
        # operators can deduplicate before retrying.
        from app.files.adapters.migrations import migrate_file_history_unique_index

        migrate_file_history_unique_index(engine)

        # Issue #237: backfill `users.token_version` on pre-existing
        # databases so the JWT-revocation logic in
        # `app.auth.dependencies._authenticate` can rely on the
        # column being present.
        from app.users.adapters.migrations import migrate_users_token_version

        migrate_users_token_version(engine)

        service_status.database_ready = True
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        service_status.failed_services.append("database")
        # Database failure is critical - re-raise to prevent startup
        raise RuntimeError(f"Critical database initialization failed: {e}") from e


async def _initialize_visibility_migration():
    """Backfill Phase 2 visibility rows for legacy servers/groups.

    Runs `VisibilityMigrationService.migrate_all_resources` at lifespan
    startup so that resources created before the Phase 2 visibility
    feature landed (or by a code path that forgot to assign a default
    row) receive the canonical PUBLIC default. The underlying service is
    idempotent: the cross-domain query (`list_missing_*`) returns the
    empty set once every resource already has a visibility row, so
    re-running on every boot is cheap when the system is steady-state
    (see `app/core/visibility/application/migration.py`).

    Failure handling: this is a best-effort backfill, not a critical
    boot step. Any exception is logged at WARNING and startup continues;
    operators can re-trigger manually through the
    ``POST /api/v1/visibility/migration/execute`` admin endpoint
    (mounted by #312).
    """
    try:
        logger.info("Running visibility migration backfill...")
        import time

        from app.core.database import SessionLocal
        from app.core.visibility.api.dependencies import (
            make_visibility_migration_service,
        )

        db = SessionLocal()
        try:
            service = make_visibility_migration_service(db)
            started = time.monotonic()
            counts = await service.migrate_all_resources()
            elapsed = time.monotonic() - started
        finally:
            db.close()

        # Slow-startup guard: flag boots where the backfill noticeably
        # delays startup so operators investigating long lifespans have
        # a breadcrumb. Threshold mirrors the
        # `PerformanceMonitoringMiddleware` slow-request default.
        if elapsed >= 1.0:
            logger.warning(
                "Visibility migration backfill took %.2fs "
                "(servers=%d, groups=%d, total=%d)",
                elapsed,
                counts.get("servers", 0),
                counts.get("groups", 0),
                counts.get("total", 0),
            )
        else:
            logger.info(
                "Visibility migration backfill completed in %.2fs "
                "(servers=%d, groups=%d, total=%d)",
                elapsed,
                counts.get("servers", 0),
                counts.get("groups", 0),
                counts.get("total", 0),
            )
    except Exception as e:
        logger.warning(
            "Visibility migration backfill failed; startup continues. "
            "Re-trigger manually via POST /api/v1/visibility/migration/execute. "
            "error=%s",
            e,
        )
        # Intentionally not added to `failed_services`: this is a
        # best-effort backfill, not a tracked service. Health checks
        # remain unaffected.


async def _initialize_database_integration():
    """Initialize database integration - important but not critical"""
    try:
        logger.info("Initializing database integration service...")
        from app.servers.application.database_integration import (
            database_integration_instance,
            make_database_integration_service,
        )

        # Build a fresh integration service inside the running loop so
        # `initialize()` captures the correct loop for its sync→async
        # bridge, then publish it on the holder so legacy importers (the
        # ``app.services.database_integration`` shim) resolve to the
        # lifecycle-aware singleton via the module's ``__getattr__``.
        service = make_database_integration_service()
        try:
            service.initialize()
        except Exception:
            # Initialize failed before publishing — make sure the holder
            # stays empty so accessors raise the explicit "not
            # initialised" error instead of returning a half-built
            # instance.
            database_integration_instance.clear()
            raise
        database_integration_instance.set(service)
        logger.info("Database integration service initialized")

        # Sync server states with error handling (enhanced with process restoration)
        try:
            await service.sync_server_states_with_restore()
            logger.info("Enhanced server states synchronized successfully")
        except Exception as sync_error:
            logger.warning(
                f"Enhanced server state synchronization failed (will retry later): {sync_error}"
            )
            # Don't fail initialization for sync issues

        service_status.database_integration_ready = True

    except Exception as e:
        logger.error(f"Database integration initialization failed: {e}")
        service_status.failed_services.append("database_integration")
        # Continue startup - this is not critical for basic functionality


async def _initialize_backup_scheduler():
    """Initialize backup scheduler - optional service.

    Builds a hexagonal `BackupSchedulerService` from
    `make_backup_scheduler()` and stores it in
    `backup_scheduler_instance` so request handlers and the legacy
    `_SchedulerProxy` shim both resolve the same singleton.
    """
    try:
        logger.info("Starting backup scheduler...")
        from app.backups import backup_scheduler_instance
        from app.backups.api.dependencies import make_backup_scheduler

        scheduler = make_backup_scheduler()
        backup_scheduler_instance.set(scheduler)
        try:
            await scheduler.start_scheduler()
        except Exception:
            # Partial-failure recovery: the holder was already populated
            # above. If `start_scheduler` fails we must clear it so the
            # next health-check / dependency lookup raises the explicit
            # "not initialised" RuntimeError rather than returning a
            # half-constructed scheduler.
            backup_scheduler_instance.clear()
            raise
        service_status.backup_scheduler_ready = True
        logger.info("Backup scheduler started successfully")

    except Exception as e:
        logger.error(f"Backup scheduler initialization failed: {e}")
        service_status.failed_services.append("backup_scheduler")
        # Continue startup - backups can be managed manually if needed


async def _initialize_websocket_service():
    """Initialize WebSocket service - optional service"""
    try:
        logger.info("Starting WebSocket monitoring service...")
        from app.websockets.application.service import websocket_service

        await websocket_service.start_monitoring()
        service_status.websocket_service_ready = True
        logger.info("WebSocket monitoring service started successfully")

    except Exception as e:
        logger.error(f"WebSocket service initialization failed: {e}")
        service_status.failed_services.append("websocket_service")
        # Continue startup - real-time features are optional


async def _initialize_version_update_scheduler():
    """Initialize version update scheduler - optional service"""
    try:
        logger.info("Starting version update scheduler...")
        from app.versions.scheduler import version_update_scheduler

        await version_update_scheduler.start_scheduler()
        service_status.version_update_scheduler_ready = True
        logger.info("Version update scheduler started successfully")

    except Exception as e:
        logger.error(f"Version update scheduler initialization failed: {e}")
        service_status.failed_services.append("version_update_scheduler")
        # Continue startup - background updates are optional


async def _cleanup_services():
    """Cleanup services during shutdown with error handling"""
    logger.info("Starting application shutdown sequence...")

    cleanup_errors = []

    # Stop Minecraft server manager (with configurable behavior)
    try:
        logger.info("Shutting down Minecraft server manager...")
        from app.servers.application.minecraft_server import minecraft_server_manager

        await minecraft_server_manager.shutdown_all()
        if settings.KEEP_SERVERS_ON_SHUTDOWN:
            logger.info(
                "Minecraft server manager shutdown completed (servers kept running)"
            )
        else:
            logger.info(
                "Minecraft server manager shutdown completed (all servers stopped)"
            )
    except Exception as e:
        logger.error(f"Error shutting down Minecraft server manager: {e}")
        cleanup_errors.append(f"minecraft_server_manager: {e}")

    # Stop backup scheduler
    if service_status.backup_scheduler_ready:
        try:
            logger.info("Stopping backup scheduler...")
            from app.backups import backup_scheduler_instance

            scheduler = backup_scheduler_instance.get()
            await scheduler.stop_scheduler()
            backup_scheduler_instance.clear()
            logger.info("Backup scheduler stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping backup scheduler: {e}")
            cleanup_errors.append(f"backup_scheduler: {e}")

    # Stop WebSocket monitoring
    if service_status.websocket_service_ready:
        try:
            logger.info("Stopping WebSocket monitoring service...")
            from app.websockets.application.service import websocket_service

            await websocket_service.stop_monitoring()
            logger.info("WebSocket monitoring service stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping WebSocket service: {e}")
            cleanup_errors.append(f"websocket_service: {e}")

    # Stop version update scheduler
    if service_status.version_update_scheduler_ready:
        try:
            logger.info("Stopping version update scheduler...")
            from app.versions.scheduler import version_update_scheduler

            await version_update_scheduler.stop_scheduler()
            logger.info("Version update scheduler stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping version update scheduler: {e}")
            cleanup_errors.append(f"version_update_scheduler: {e}")

    if cleanup_errors:
        logger.warning(f"Shutdown completed with errors: {cleanup_errors}")
    else:
        logger.info("All services shut down cleanly")


app = FastAPI(
    title="mc-server-dashboard-api",
    version=__version__,
    lifespan=lifespan,
)

# Map framework-agnostic domain exceptions (raised by application-layer
# services such as ``AuthorizationService``) to HTTP responses.
register_exception_handlers(app)


@app.get("/health", tags=["health"])
async def health_check(
    service: HealthCheckService = Depends(get_health_check_service),
):
    """Legacy health check endpoint.

    Wire format is preserved for backward compatibility; the actual
    component evaluation is delegated to ``HealthCheckService`` (Issue
    #21). New consumers should prefer ``/healthz``, ``/readyz``, or
    ``/api/v1/health/detail``.
    """
    import json

    from fastapi import Response

    payload, status_code = await build_legacy_payload(service)
    return Response(
        content=json.dumps(payload),
        status_code=status_code,
        media_type="application/json",
    )


@app.get("/api/v1/health", tags=["health"])
async def health_check_v1(
    service: HealthCheckService = Depends(get_health_check_service),
):
    """Legacy ``/api/v1/health`` alias — see :func:`health_check`."""
    import json

    from fastapi import Response

    payload, status_code = await build_legacy_payload(service)
    return Response(
        content=json.dumps(payload),
        status_code=status_code,
        media_type="application/json",
    )


@app.get("/metrics", tags=["monitoring"])
async def get_metrics():
    """Get performance metrics and statistics"""
    from datetime import datetime

    metrics = get_performance_metrics()

    return {
        "timestamp": datetime.now().isoformat(),
        "performance": metrics,
        "service_status": service_status.get_status(),
        "message": "Performance metrics collected successfully",
    }


@app.get("/api/v1/metrics", tags=["monitoring"])
async def get_metrics_v1():
    """Get performance metrics and statistics"""
    from datetime import datetime

    metrics = get_performance_metrics()

    return {
        "timestamp": datetime.now().isoformat(),
        "performance": metrics,
        "service_status": service_status.get_status(),
        "message": "Performance metrics collected successfully",
    }


# Add audit middleware (before performance monitoring for complete request tracking)
app.add_middleware(
    AuditMiddleware,
    enabled=True,
    log_all_requests=False,  # Only log specific auditable endpoints
    exclude_health_checks=True,
)

# Add performance monitoring middleware
app.add_middleware(
    PerformanceMonitoringMiddleware,
    enabled=True,
    log_slow_requests=True,
    slow_request_threshold=1.0,  # Log requests slower than 1 second
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(servers_router, prefix="/api/v1/servers", tags=["servers"])
app.include_router(groups_router, prefix="/api/v1/groups", tags=["groups"])
app.include_router(
    scheduler_router, prefix="/api/v1/backup-scheduler", tags=["backup-scheduler"]
)
app.include_router(backups_router, prefix="/api/v1/backups", tags=["backups"])
app.include_router(templates_router, prefix="/api/v1/templates", tags=["templates"])
app.include_router(files_router, prefix="/api/v1/files", tags=["files"])
app.include_router(versions_router, prefix="/api/v1/versions", tags=["versions"])
app.include_router(websockets_router, prefix="/api/v1/ws", tags=["websockets"])
app.include_router(visibility_router, prefix="/api/v1", tags=["visibility"])
app.include_router(audit_router, tags=["audit"])

# Health / readiness endpoints (Issue #21). Mounted without a prefix
# so ``/healthz``, ``/readyz`` and ``/ready`` keep their canonical
# k8s paths; the admin detail endpoint declares its own
# ``/api/v1/health/detail`` path on the route.
app.include_router(health_router)
