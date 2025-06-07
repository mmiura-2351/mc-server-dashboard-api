import logging
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.servers.models import Server, ServerStatus
from app.services.minecraft_server import minecraft_server_manager

logger = logging.getLogger(__name__)


class DatabaseIntegrationService:
    """Service for integrating MinecraftServerManager with database operations"""

    def __init__(self):
        # Create a separate engine for background operations
        self.engine = create_engine(settings.DATABASE_URL)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def initialize(self):
        """Initialize database integration with MinecraftServerManager"""
        # Set the callback for status updates
        minecraft_server_manager.set_status_update_callback(self.update_server_status)
        logger.info("Database integration initialized")

    def update_server_status(self, server_id: int, status: ServerStatus):
        """Update server status in database"""
        try:
            with self.SessionLocal() as db:
                server = db.query(Server).filter(Server.id == server_id).first()
                if server:
                    old_status = server.status
                    server.status = status
                    db.commit()
                    logger.info(
                        f"Updated server {server_id} status: {old_status} -> {status}"
                    )
                else:
                    logger.warning(f"Server {server_id} not found in database")
        except Exception as e:
            logger.error(f"Failed to update server {server_id} status in database: {e}")

    def sync_server_states(self):
        """Synchronize server states between database and MinecraftServerManager"""
        try:
            with self.SessionLocal() as db:
                # Get all servers from database
                servers = db.query(Server).filter(Server.is_deleted == False).all()

                # Get currently running servers from manager
                running_server_ids = set(minecraft_server_manager.list_running_servers())

                for server in servers:
                    db_status = server.status
                    is_actually_running = server.id in running_server_ids

                    # Check for inconsistencies
                    if is_actually_running and db_status in [
                        ServerStatus.stopped,
                        ServerStatus.error,
                    ]:
                        # Server is running but DB says it's stopped/error
                        logger.info(
                            f"Correcting server {server.id} status: {db_status} -> running"
                        )
                        server.status = ServerStatus.running
                    elif not is_actually_running and db_status in [
                        ServerStatus.starting,
                        ServerStatus.running,
                        ServerStatus.stopping,
                    ]:
                        # Server is not running but DB says it should be
                        logger.info(
                            f"Correcting server {server.id} status: {db_status} -> stopped"
                        )
                        server.status = ServerStatus.stopped

                db.commit()
                logger.info("Server state synchronization completed")

        except Exception as e:
            logger.error(f"Failed to sync server states: {e}")

    def get_server_process_info(self, server_id: int) -> Optional[dict]:
        """Get process information for a server"""
        return minecraft_server_manager.get_server_info(server_id)

    def is_server_running(self, server_id: int) -> bool:
        """Check if server is currently running"""
        return server_id in minecraft_server_manager.list_running_servers()

    def get_all_running_servers(self) -> list[int]:
        """Get list of all currently running server IDs"""
        return minecraft_server_manager.list_running_servers()


# Global database integration service
database_integration_service = DatabaseIntegrationService()
