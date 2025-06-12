import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.database_utils import (
    RetryExhaustedException,
    TransactionException,
    transactional,
    with_transaction,
)
from app.servers.models import Server, ServerStatus
from app.services.minecraft_server import minecraft_server_manager

logger = logging.getLogger(__name__)


class DatabaseIntegrationService:
    """Service for integrating MinecraftServerManager with database operations"""

    def __init__(self):
        # Reuse the main application's database session maker for efficiency
        # This avoids creating duplicate connection pools and ensures consistent configuration
        self.SessionLocal = SessionLocal

    def initialize(self):
        """Initialize database integration with MinecraftServerManager"""
        # Set the callback for status updates
        minecraft_server_manager.set_status_update_callback(self.update_server_status)
        logger.info("Database integration initialized")

    def update_server_status(self, server_id: int, status: ServerStatus) -> bool:
        """
        Update server status in database with transaction management and retry logic.

        Args:
            server_id: ID of the server to update
            status: New server status

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            with self.SessionLocal() as session:

                def update_status(session: Session, server_id: int, status: ServerStatus):
                    server = session.query(Server).filter(Server.id == server_id).first()
                    if server:
                        old_status = server.status
                        server.status = status
                        logger.info(
                            f"Updated server {server_id} status: {old_status} -> {status}"
                        )
                        return True
                    else:
                        logger.warning(f"Server {server_id} not found in database")
                        return False

                return with_transaction(
                    session,
                    update_status,
                    server_id,
                    status,
                    max_retries=settings.DATABASE_MAX_RETRIES,
                    backoff_factor=settings.DATABASE_RETRY_BACKOFF,
                )
        except RetryExhaustedException:
            logger.error(
                f"Failed to update server {server_id} status after all retry attempts"
            )
            return False
        except TransactionException as e:
            logger.error(f"Transaction error updating server {server_id} status: {e}")
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error updating server {server_id} status: {e}", exc_info=True
            )
            return False

    def sync_server_states(self) -> bool:
        """
        Synchronize server states between database and MinecraftServerManager.

        Uses batch operations and proper transaction management to ensure consistency.

        Returns:
            True if synchronization succeeded, False otherwise
        """
        try:
            with self.SessionLocal() as session:

                def sync_states(session: Session):
                    # Get all active servers from database in a single query
                    servers = (
                        session.query(Server).filter(Server.is_deleted.is_(False)).all()
                    )

                    if not servers:
                        logger.info("No servers to synchronize")
                        return True

                    # Get currently running servers from manager
                    running_server_ids = set(
                        minecraft_server_manager.list_running_servers()
                    )

                    # Track servers that need updates
                    servers_to_update = []

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
                            servers_to_update.append(server)

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
                            servers_to_update.append(server)

                    # Batch update modified servers
                    if servers_to_update:
                        logger.info(f"Updating {len(servers_to_update)} server statuses")
                        # The session will track and update all modified objects on commit

                    logger.info("Server state synchronization completed")
                    return True

                return with_transaction(
                    session,
                    sync_states,
                    max_retries=settings.DATABASE_MAX_RETRIES,
                    backoff_factor=settings.DATABASE_RETRY_BACKOFF,
                )

        except RetryExhaustedException:
            logger.error("Failed to sync server states after all retry attempts")
            return False
        except TransactionException as e:
            logger.error(f"Transaction error syncing server states: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error syncing server states: {e}", exc_info=True)
            return False

    def get_server_process_info(self, server_id: int) -> Optional[dict]:
        """Get process information for a server"""
        return minecraft_server_manager.get_server_info(server_id)

    def is_server_running(self, server_id: int) -> bool:
        """Check if server is currently running"""
        return server_id in minecraft_server_manager.list_running_servers()

    def get_all_running_servers(self) -> list[int]:
        """Get list of all currently running server IDs"""
        return minecraft_server_manager.list_running_servers()

    @transactional(max_retries=3, propagate_errors=False)
    def batch_update_server_statuses(
        self, session: Session, status_updates: dict[int, ServerStatus]
    ) -> dict[int, bool]:
        """
        Update multiple server statuses in a single transaction.

        Args:
            session: Database session (provided by decorator)
            status_updates: Dictionary mapping server_id to new status

        Returns:
            Dictionary mapping server_id to success status
        """
        results = {}

        # Get all servers that need updates in a single query
        server_ids = list(status_updates.keys())
        servers = session.query(Server).filter(Server.id.in_(server_ids)).all()

        # Create a mapping for quick lookup
        server_map = {server.id: server for server in servers}

        # Update each server
        for server_id, new_status in status_updates.items():
            if server_id in server_map:
                server = server_map[server_id]
                old_status = server.status
                server.status = new_status
                results[server_id] = True
                logger.info(
                    f"Batch update: Server {server_id} status: {old_status} -> {new_status}"
                )
            else:
                results[server_id] = False
                logger.warning(f"Batch update: Server {server_id} not found")

        return results

    def get_servers_by_status(self, status: ServerStatus) -> list[Server]:
        """
        Get all servers with a specific status.

        Args:
            status: Server status to filter by

        Returns:
            List of Server objects
        """
        try:
            with self.SessionLocal() as session:
                servers = (
                    session.query(Server)
                    .filter(Server.status == status, Server.is_deleted.is_(False))
                    .all()
                )

                # Detach from session to use outside of context
                session.expunge_all()
                return servers

        except Exception as e:
            logger.error(f"Failed to get servers by status {status}: {e}", exc_info=True)
            return []


# Global database integration service
database_integration_service = DatabaseIntegrationService()
