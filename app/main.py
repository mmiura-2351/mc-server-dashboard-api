from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router

# Import models to ensure they are registered with SQLAlchemy
from app.backups.router import router as backups_router
from app.backups.scheduler_router import router as scheduler_router
from app.core.database import Base, engine
from app.files.router import router as files_router
from app.groups.router import router as groups_router
from app.servers.router import router as servers_router
from app.templates.router import router as templates_router

# Import all models to ensure they are registered with SQLAlchemy
from app.users.router import router as users_router
from app.websockets.router import router as websockets_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    Base.metadata.create_all(bind=engine)

    # Initialize database integration with MinecraftServerManager
    from app.services.database_integration import database_integration_service

    database_integration_service.initialize()

    # Sync server states on startup
    database_integration_service.sync_server_states()

    # Start backup scheduler
    from app.services.backup_scheduler import backup_scheduler

    await backup_scheduler.start_scheduler()

    # Start WebSocket monitoring
    from app.services.websocket_service import websocket_service

    await websocket_service.start_monitoring()

    yield

    # Cleanup on shutdown
    from app.services.minecraft_server import minecraft_server_manager

    await minecraft_server_manager.shutdown_all()

    # Stop backup scheduler
    await backup_scheduler.stop_scheduler()

    # Stop WebSocket monitoring
    await websocket_service.stop_monitoring()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://127.0.0.1:3000",
        "*",
    ],
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
