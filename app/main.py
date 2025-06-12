import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router

# Import models to ensure they are registered with SQLAlchemy
from app.backups.router import router as backups_router
from app.backups.scheduler_router import router as scheduler_router
from app.core.config import settings
from app.core.database import Base, engine
from app.files.router import router as files_router
from app.groups.router import router as groups_router
from app.middleware.audit_middleware import AuditMiddleware
from app.middleware.performance_monitoring import (
    PerformanceMonitoringMiddleware,
    get_performance_metrics,
)
from app.servers.routers import router as servers_router
from app.templates.router import router as templates_router

# Import all models to ensure they are registered with SQLAlchemy
from app.users.router import router as users_router
from app.websockets.router import router as websockets_router

logger = logging.getLogger(__name__)


class ServiceStatus:
    """Track service initialization status for graceful degradation"""

    def __init__(self):
        self.database_ready = False
        self.database_integration_ready = False
        self.backup_scheduler_ready = False
        self.websocket_service_ready = False
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

    # 2. Initialize database integration (important but not critical)
    await _initialize_database_integration()

    # 3. Initialize backup scheduler (optional - can be started later)
    await _initialize_backup_scheduler()

    # 4. Initialize WebSocket service (optional - real-time features)
    await _initialize_websocket_service()


async def _initialize_database():
    """Initialize database tables - critical service"""
    try:
        logger.info("Initializing database tables...")
        Base.metadata.create_all(bind=engine)
        service_status.database_ready = True
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        service_status.failed_services.append("database")
        # Database failure is critical - re-raise to prevent startup
        raise RuntimeError(f"Critical database initialization failed: {e}") from e


async def _initialize_database_integration():
    """Initialize database integration - important but not critical"""
    try:
        logger.info("Initializing database integration service...")
        from app.services.database_integration import database_integration_service

        database_integration_service.initialize()
        logger.info("Database integration service initialized")

        # Sync server states with error handling
        try:
            database_integration_service.sync_server_states()
            logger.info("Server states synchronized successfully")
        except Exception as sync_error:
            logger.warning(
                f"Server state synchronization failed (will retry later): {sync_error}"
            )
            # Don't fail initialization for sync issues

        service_status.database_integration_ready = True

    except Exception as e:
        logger.error(f"Database integration initialization failed: {e}")
        service_status.failed_services.append("database_integration")
        # Continue startup - this is not critical for basic functionality


async def _initialize_backup_scheduler():
    """Initialize backup scheduler - optional service"""
    try:
        logger.info("Starting backup scheduler...")
        from app.services.backup_scheduler import backup_scheduler

        await backup_scheduler.start_scheduler()
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
        from app.services.websocket_service import websocket_service

        await websocket_service.start_monitoring()
        service_status.websocket_service_ready = True
        logger.info("WebSocket monitoring service started successfully")

    except Exception as e:
        logger.error(f"WebSocket service initialization failed: {e}")
        service_status.failed_services.append("websocket_service")
        # Continue startup - real-time features are optional


async def _cleanup_services():
    """Cleanup services during shutdown with error handling"""
    logger.info("Starting application shutdown sequence...")

    cleanup_errors = []

    # Stop Minecraft server manager
    try:
        logger.info("Shutting down Minecraft server manager...")
        from app.services.minecraft_server import minecraft_server_manager

        await minecraft_server_manager.shutdown_all()
        logger.info("Minecraft server manager shutdown completed")
    except Exception as e:
        logger.error(f"Error shutting down Minecraft server manager: {e}")
        cleanup_errors.append(f"minecraft_server_manager: {e}")

    # Stop backup scheduler
    if service_status.backup_scheduler_ready:
        try:
            logger.info("Stopping backup scheduler...")
            from app.services.backup_scheduler import backup_scheduler

            await backup_scheduler.stop_scheduler()
            logger.info("Backup scheduler stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping backup scheduler: {e}")
            cleanup_errors.append(f"backup_scheduler: {e}")

    # Stop WebSocket monitoring
    if service_status.websocket_service_ready:
        try:
            logger.info("Stopping WebSocket monitoring service...")
            from app.services.websocket_service import websocket_service

            await websocket_service.stop_monitoring()
            logger.info("WebSocket monitoring service stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping WebSocket service: {e}")
            cleanup_errors.append(f"websocket_service: {e}")

    if cleanup_errors:
        logger.warning(f"Shutdown completed with errors: {cleanup_errors}")
    else:
        logger.info("All services shut down cleanly")


app = FastAPI(lifespan=lifespan)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint with service status information"""
    import json
    from datetime import datetime

    from fastapi import Response

    status = service_status.get_status()

    response_data = {
        "status": "healthy" if status["healthy"] else "degraded",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "operational" if status["database"] else "failed",
            "database_integration": (
                "operational" if status["database_integration"] else "failed"
            ),
            "backup_scheduler": "operational" if status["backup_scheduler"] else "failed",
            "websocket_service": (
                "operational" if status["websocket_service"] else "failed"
            ),
        },
        "failed_services": status["failed_services"],
        "message": (
            "All services operational"
            if status["healthy"]
            else f"Running with degraded functionality: {', '.join(status['failed_services'])}"
        ),
    }

    # Return appropriate HTTP status based on service health
    if not status["healthy"]:
        return Response(
            content=json.dumps(response_data),
            status_code=503,
            media_type="application/json",
        )

    return response_data


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
app.include_router(scheduler_router, prefix="/api/v1/backups", tags=["backup-scheduler"])
app.include_router(backups_router, prefix="/api/v1/backups", tags=["backups"])
app.include_router(templates_router, prefix="/api/v1/templates", tags=["templates"])
app.include_router(files_router, prefix="/api/v1/files", tags=["files"])
app.include_router(websockets_router, prefix="/api/v1/ws", tags=["websockets"])
app.include_router(audit_router, tags=["audit"])
