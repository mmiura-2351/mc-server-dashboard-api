import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import Role, User

logger = logging.getLogger(__name__)


class ServerService:
    """Service for server management operations"""

    def __init__(self):
        pass

    def list_servers_for_user(
        self, user: User, db: Session, page: int = 1, size: int = 50
    ) -> Dict[str, Any]:
        """List servers with pagination and user-based filtering

        Args:
            user: User requesting server list
            db: Database session (required for security)
            page: Page number for pagination
            size: Page size for pagination

        Returns:
            Dictionary containing servers and pagination info

        Raises:
            HTTPException: If database operations fail
        """
        try:
            if db is None:
                raise HTTPException(
                    status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session is required for security-critical operation",
                )

            # Calculate offset
            offset = (page - 1) * size

            # Base query
            query = db.query(Server).filter(~Server.is_deleted)

            # Apply user-based filtering
            if user.role != Role.admin:
                query = query.filter(Server.owner_id == user.id)

            # Get total count before pagination
            total = query.count()

            # Apply pagination
            servers = query.offset(offset).limit(size).all()

            return {
                "servers": servers,
                "total": total,
                "page": page,
                "size": size,
                "pages": (total + size - 1) // size if total > 0 else 0,
            }

        except Exception as e:
            logger.error(f"Failed to list servers for user {user.id}: {e}")
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list servers: {str(e)}",
            )

    def validate_server_operation(
        self, server_id: int, operation: str, db: Session
    ) -> bool:
        """Validate if a server operation can be performed

        Args:
            server_id: ID of the server to validate
            operation: Operation to validate
            db: Database session (required for security)

        Returns:
            True if operation is valid

        Raises:
            HTTPException: If server not found or operation invalid
        """
        try:
            if db is None:
                raise HTTPException(
                    status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session is required for security-critical operation",
                )

            server = db.query(Server).filter(Server.id == server_id).first()
            if not server:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND, detail="Server not found"
                )

            current_status = minecraft_server_manager.get_server_status(server_id)
            if not current_status:
                current_status = ServerStatus.stopped

            operation_rules = {
                "start": [ServerStatus.stopped, ServerStatus.error],
                "stop": [ServerStatus.running, ServerStatus.starting],
                "restart": [
                    ServerStatus.running,
                    ServerStatus.starting,
                    ServerStatus.stopped,
                ],
                "update": [ServerStatus.stopped],
                "delete": [ServerStatus.stopped],
                "backup": [
                    ServerStatus.stopped,
                    ServerStatus.running,
                ],  # Can backup while running
            }

            allowed_statuses = operation_rules.get(operation, [])
            if current_status not in allowed_statuses:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail=f"Cannot {operation} server in {current_status.value} state",
                )

            return True

        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            logger.error(
                f"Failed to validate operation {operation} for server {server_id}: {e}"
            )
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to validate operation: {str(e)}",
            )

    def get_server_with_access_check(
        self, server_id: int, user: User, db: Session
    ) -> Server:
        """Get server with user access validation

        Args:
            server_id: ID of the server to retrieve
            user: User requesting access
            db: Database session (required for security)

        Returns:
            Server object if access is granted

        Raises:
            HTTPException: If server not found or access denied
        """
        try:
            if db is None:
                raise HTTPException(
                    status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session is required for security-critical operation",
                )

            server = (
                db.query(Server)
                .filter(and_(Server.id == server_id, ~Server.is_deleted))
                .first()
            )

            if not server:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND, detail="Server not found"
                )

            # Check access permissions
            if user.role != Role.admin and server.owner_id != user.id:
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this server",
                )

            return server

        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            logger.error(f"Failed to get server {server_id} for user {user.id}: {e}")
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get server: {str(e)}",
            )

    def server_exists(self, server_id: int, db: Session) -> bool:
        """Check if server exists

        Args:
            server_id: ID of the server to check
            db: Database session (required for security)

        Returns:
            True if server exists and is not deleted
        """
        try:
            if db is None:
                logger.error(
                    f"Database session is required for server existence check {server_id}"
                )
                return False

            server = (
                db.query(Server)
                .filter(and_(Server.id == server_id, ~Server.is_deleted))
                .first()
            )
            return server is not None

        except Exception as e:
            logger.error(f"Failed to check server existence {server_id}: {e}")
            return False

    def get_server_statistics(self, user: User, db: Session) -> Dict[str, Any]:
        """Get server statistics for user

        Args:
            user: User requesting statistics
            db: Database session (required for security)

        Returns:
            Dictionary containing server statistics

        Raises:
            HTTPException: If database operations fail
        """
        try:
            if db is None:
                raise HTTPException(
                    status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database session is required for security-critical operation",
                )

            # Base query
            query = db.query(Server).filter(~Server.is_deleted)

            # Apply user-based filtering
            if user.role != Role.admin:
                query = query.filter(Server.owner_id == user.id)

            # Get counts by status
            total_servers = query.count()

            # Get status distribution
            status_counts = {}
            for status in ServerStatus:
                count = query.filter(Server.status == status).count()
                status_counts[status.value] = count

            # Get type distribution
            type_counts = {}
            for server_type in ServerType:
                count = query.filter(Server.server_type == server_type).count()
                type_counts[server_type.value] = count

            # Get version distribution
            version_query = query.with_entities(
                Server.minecraft_version, func.count(Server.id).label("count")
            ).group_by(Server.minecraft_version)

            version_counts = {version: count for version, count in version_query.all()}

            return {
                "total_servers": total_servers,
                "status_distribution": status_counts,
                "type_distribution": type_counts,
                "version_distribution": version_counts,
                "last_updated": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get server statistics for user {user.id}: {e}")
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get statistics: {str(e)}",
            )

    async def wait_for_server_status(
        self, server_id: int, target_status: ServerStatus, timeout: int = 30
    ) -> bool:
        """Wait for server to reach target status"""
        import asyncio

        try:
            for _ in range(timeout):
                current_status = minecraft_server_manager.get_server_status(server_id)
                if current_status == target_status:
                    return True
                await asyncio.sleep(1)

            return False

        except Exception as e:
            logger.error(f"Error waiting for server {server_id} status: {e}")
            return False

    def update_server_status(
        self, server_id: int, status: ServerStatus, db: Session
    ) -> bool:
        """Update server status in database

        Args:
            server_id: ID of the server to update
            status: New status to set
            db: Database session (required for security)

        Returns:
            True if update successful, False otherwise
        """
        try:
            if db is None:
                logger.error(
                    f"Database session is required for server status update {server_id}"
                )
                return False

            server = db.query(Server).filter(Server.id == server_id).first()
            if not server:
                return False

            server.status = status
            db.commit()
            return True

        except Exception as e:
            logger.error(f"Failed to update server {server_id} status: {e}")
            return False


server_service = ServerService()
