"""Legacy direct-ORM helpers retained for backward compatibility.

These helpers carry the historic `db.query(Server)` callsites that
existed in the pre-#228 `app.servers.service` and
`app.services.server_service` modules. They are quarantined into this
private module so the canonical `app.servers.application.service`
module is free of `db.query(...)` per the #228 PR 2c gate.

Existing unit tests inject a `Mock(db)` directly into the methods on
this module — that contract is preserved verbatim. New code SHOULD NOT
import from here; instead, use the `ServerRepository` Port and the
`ServerService` constructor DI in `app.servers.application.service`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    InvalidRequestException,
    ServerNotFoundException,
    handle_database_error,
)
from app.core.security import PathValidator, SecurityError
from app.servers.models import Server, ServerStatus, ServerType
from app.servers.schemas import ServerCreateRequest, ServerResponse
from app.services.minecraft_server import minecraft_server_manager
from app.users.domain.value_objects import Role
from app.users.models import User

logger = logging.getLogger(__name__)


__all__ = [
    "ServerValidationService",
    "list_servers_legacy_db",
    "list_servers_for_user_legacy",
    "validate_server_operation_legacy",
    "get_server_with_access_check_legacy",
    "server_exists_legacy",
    "get_server_statistics_legacy",
    "update_server_status_legacy",
]


class ServerValidationService:
    """SQLAlchemy-backed legacy validation service.

    Kept for backward compatibility with the existing unit tests that
    instantiate it directly and pass a `Mock(db)`. New code should use
    the `ServerRepository` Port via `ServerService` DI.
    """

    def __init__(self) -> None:
        self.base_directory = Path("servers")

    async def validate_server_uniqueness(
        self, request: ServerCreateRequest, db: Session
    ) -> None:
        existing_name = (
            db.query(Server)
            .filter(and_(Server.name == request.name, Server.is_deleted.is_(False)))
            .first()
        )
        if existing_name:
            raise ConflictException(f"Server with name '{request.name}' already exists")

    def validate_server_exists(self, server_id: int, db: Session) -> Server:
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, Server.is_deleted.is_(False)))
            .first()
        )
        if not server:
            raise ServerNotFoundException(str(server_id))
        return server

    def validate_server_directory(self, server_name: str) -> Path:
        try:
            self._validate_server_name_basic(server_name)
            server_dir = PathValidator.create_safe_server_directory(
                server_name, self.base_directory
            )
            if server_dir.exists():
                raise ConflictException(
                    f"Server directory for '{server_name}' already exists"
                )
            return server_dir
        except SecurityError as e:
            raise InvalidRequestException(f"Invalid server name: {e}")

    def _validate_server_name_basic(self, server_name: str) -> None:
        if not server_name or not isinstance(server_name, str):
            raise SecurityError("Server name must be a non-empty string")
        if len(server_name) > 255:
            raise SecurityError("Server name too long (max 255 characters)")
        if ".." in server_name:
            raise SecurityError("Server name cannot contain path traversal patterns (..)")
        if "\\" in server_name:
            raise SecurityError("Server name cannot contain backslashes")
        if server_name.startswith("/") or server_name.endswith("/"):
            raise SecurityError("Server name cannot start or end with slashes")
        if server_name.startswith(" ") or server_name.endswith(" "):
            raise SecurityError("Server name cannot start or end with spaces")


def list_servers_legacy_db(
    *,
    db: Session,
    owner_id: Optional[int] = None,
    status: Optional[ServerStatus] = None,
    server_type: Optional[ServerType] = None,
    page: int = 1,
    size: int = 50,
) -> Dict[str, Any]:
    """Direct-ORM fallback for `ServerService.list_servers` when no repo is wired."""
    from sqlalchemy.orm import joinedload

    try:
        query = (
            db.query(Server)
            .options(joinedload(Server.owner))
            .filter(Server.is_deleted.is_(False))
        )
        if owner_id is not None:
            query = query.filter(Server.owner_id == owner_id)
        if status:
            query = query.filter(Server.status == status)
        if server_type:
            query = query.filter(Server.server_type == server_type)
        query = query.order_by(Server.created_at.desc())

        total = query.count()
        servers = query.offset((page - 1) * size).limit(size).all()
        return {
            "servers": [ServerResponse.model_validate(s) for s in servers],
            "total": total,
            "page": page,
            "size": size,
        }
    except Exception as e:
        handle_database_error("list", "servers", e)


def list_servers_for_user_legacy(
    user: User, db: Session, page: int = 1, size: int = 50
) -> Dict[str, Any]:
    try:
        if db is None:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database session is required for security-critical operation",
            )
        offset = (page - 1) * size
        query = db.query(Server).filter(~Server.is_deleted)
        if user.role != Role.admin:
            query = query.filter(Server.owner_id == user.id)
        total = query.count()
        servers = query.offset(offset).limit(size).all()
        return {
            "servers": servers,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size if total > 0 else 0,
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Failed to list servers for user {user.id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list servers: {str(e)}",
        )


def validate_server_operation_legacy(server_id: int, operation: str, db: Session) -> bool:
    try:
        if db is None:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database session is required for security-critical operation",
            )
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Server not found",
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
            "backup": [ServerStatus.stopped, ServerStatus.running],
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


def get_server_with_access_check_legacy(
    server_id: int, user: User, db: Session
) -> Server:
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


def server_exists_legacy(server_id: int, db: Session) -> bool:
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


def get_server_statistics_legacy(user: User, db: Session) -> Dict[str, Any]:
    try:
        if db is None:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database session is required for security-critical operation",
            )
        query = db.query(Server).filter(~Server.is_deleted)
        if user.role != Role.admin:
            query = query.filter(Server.owner_id == user.id)
        total_servers = query.count()

        status_counts: Dict[str, int] = {}
        for status_value in ServerStatus:
            count = query.filter(Server.status == status_value).count()
            status_counts[status_value.value] = count

        type_counts: Dict[str, int] = {}
        for server_type_value in ServerType:
            count = query.filter(Server.server_type == server_type_value).count()
            type_counts[server_type_value.value] = count

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


def update_server_status_legacy(
    server_id: int, status: ServerStatus, db: Session
) -> bool:
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
