"""Legacy ORM-direct helpers for ServerService, retained for migration parity.

These helpers contain direct `db.query(Server)` access — they live here in
adapters/ (per ARCHITECTURE Section 4.3, adapter layer may use SQLAlchemy) rather
than in application/ to preserve the layering invariant established in #225-#228.

The legacy entry points (`ServerValidationService`, `ServerDatabaseService`, etc.)
are exercised only by `tests/unit/services/test_server_service.py` and
`tests/unit/servers/test_service.py` legacy test fixtures. Production routers
use the canonical `ServerService` in `app/servers/application/service.py`,
which goes through `ServerRepository` exclusively.

TODO(#149): once those legacy tests are rewritten to repository-fake fixtures,
this entire module can be deleted.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    InvalidRequestException,
    ServerNotFoundException,
    handle_database_error,
    handle_file_error,
)
from app.core.security import PathValidator, SecurityError
from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.domain.exceptions import UnsupportedMinecraftVersionError
from app.servers.models import Server, ServerStatus, ServerType
from app.servers.schemas import (
    ServerCreateRequest,
    ServerResponse,
    ServerUpdateRequest,
)
from app.users.domain.value_objects import Role
from app.users.models import User
from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.application.jar_cache_manager import jar_cache_manager
from app.versions.application.version_manager import minecraft_version_manager

logger = logging.getLogger(__name__)


__all__ = [
    "ServerDatabaseService",
    "ServerJarService",
    "ServerValidationService",
    "is_version_supported_db_legacy",
    "list_servers_legacy_db",
    "list_servers_for_user_legacy",
    "validate_server_operation_legacy",
    "get_server_with_access_check_legacy",
    "server_exists_legacy",
    "get_server_statistics_legacy",
    "update_server_status_legacy",
]


async def is_version_supported_db_legacy(
    db: Session, server_type: ServerType, version: str
) -> bool:
    """Legacy version-support lookup that talks to SQLAlchemy directly.

    Moved here from ``app.servers.application.service`` in #285 so the
    application layer no longer constructs ``SqlAlchemyVersionRepository``
    by hand (ARCHITECTURE Section 4.2). Behaviour matches the original
    ``ServerService._is_version_supported_db``: DB-first lookup, fall
    back to the external version-manager API on miss / DB failure.
    """
    try:
        repo = SqlAlchemyVersionRepository(db)
        db_version = await repo.get_version_by_type_and_version(server_type, version)
        if db_version is not None and db_version.is_active:
            return True
        try:
            return minecraft_version_manager.is_version_supported(server_type, version)
        except Exception as api_error:
            logger.error(
                f"External API validation failed for {server_type.value} "
                f"{version}: {api_error}"
            )
            raise InvalidRequestException(
                f"Unable to validate version {version} for {server_type.value}. "
                "Version not found in database and external API is unavailable."
            )
    except InvalidRequestException:
        raise
    except Exception as db_error:
        logger.error(
            f"Database validation failed for {server_type.value} {version}: {db_error}"
        )
        try:
            return minecraft_version_manager.is_version_supported(server_type, version)
        except Exception as api_error:
            logger.error(f"Both database and API validation failed: {api_error}")
            raise InvalidRequestException(
                f"Unable to validate version {version} for {server_type.value}. "
                "Both database and external API are unavailable."
            )


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

        status_counts: Dict[str, int] = {s.value: 0 for s in ServerStatus}
        status_query = query.with_entities(
            Server.status, func.count(Server.id).label("count")
        ).group_by(Server.status)
        for status_value, count in status_query:
            status_counts[status_value.value] = count

        type_counts: Dict[str, int] = {t.value: 0 for t in ServerType}
        type_query = query.with_entities(
            Server.server_type, func.count(Server.id).label("count")
        ).group_by(Server.server_type)
        for type_value, count in type_query:
            type_counts[type_value.value] = count

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


# ---------------------------------------------------------------------------
# Session-direct helpers (moved from app.servers.application.service in #285).
#
# These classes call SQLAlchemy methods on a ``Session`` at runtime
# (``db.add``, ``db.query``, ``db.commit``...), so they belong in
# adapters/ per ARCHITECTURE Section 4.2/Section 4.3. The application service module
# re-exports them for backward compatibility with the legacy tests that
# import them via ``app.servers.application.service``.
# ---------------------------------------------------------------------------


class ServerJarService:
    """Service for handling server JAR downloads and management with caching.

    Pre-existing legacy class that consumes a ``Session`` at runtime to
    look up versions through the version repository. Kept here in
    adapters/ rather than application/ to preserve the Section 4.2 invariant.
    """

    def __init__(self) -> None:
        self.version_manager = minecraft_version_manager
        self.cache_manager = jar_cache_manager

    async def _is_version_supported_db(
        self, db: Session, server_type: ServerType, version: str
    ) -> bool:
        try:
            repo = SqlAlchemyVersionRepository(db)
            db_version = await repo.get_version_by_type_and_version(server_type, version)
            if db_version is not None and db_version.is_active:
                return True
            return False
        except Exception:
            return False

    async def _get_download_url_db(
        self, db: Session, server_type: ServerType, version: str
    ) -> Optional[str]:
        try:
            repo = SqlAlchemyVersionRepository(db)
            db_version = await repo.get_version_by_type_and_version(server_type, version)
            if db_version and db_version.is_active and db_version.download_url:
                return db_version.download_url
            return None
        except Exception:
            return None

    async def get_server_jar(
        self,
        server_type: ServerType,
        minecraft_version: str,
        server_dir: Path,
        db: Session,
    ) -> Path:
        try:
            if not await self._is_version_supported_db(
                db, server_type, minecraft_version
            ):
                raise InvalidRequestException(
                    f"Version {minecraft_version} is not supported for {server_type.value} "
                    f"(minimum supported version: 1.8)"
                )

            download_url = await self._get_download_url_db(
                db, server_type, minecraft_version
            )

            if not download_url:
                raise UnsupportedMinecraftVersionError(
                    version=minecraft_version,
                    server_type=server_type.value,
                )

            cached_jar_path = await self.cache_manager.get_or_download_jar(
                server_type, minecraft_version, download_url
            )

            server_jar_path = await self.cache_manager.copy_jar_to_server(
                cached_jar_path, server_dir
            )

            logger.info(
                f"Prepared {server_type.value} {minecraft_version} JAR for server "
                f"at {server_jar_path}"
            )
            return server_jar_path

        except UnsupportedMinecraftVersionError:
            raise
        except Exception as e:
            handle_file_error("get server jar", str(server_dir), e)


class ServerDatabaseService:
    """Legacy DB-direct CRUD helper.

    Preserved for backward compatibility with the existing unit tests
    that inject a ``Mock(db)`` and exercise the SQLAlchemy path. The
    canonical ``ServerService.create_server`` path uses the
    ``ServerRepository`` Port instead.
    """

    def create_server_record(
        self,
        request: ServerCreateRequest,
        owner: User,
        directory_path: str,
        db: Session,
    ) -> Server:
        try:
            server = Server(
                name=request.name,
                description=request.description,
                server_type=request.server_type,
                minecraft_version=request.minecraft_version,
                port=request.port,
                max_memory=request.max_memory,
                max_players=request.max_players,
                directory_path=directory_path,
                owner_id=owner.id,
                status=ServerStatus.stopped,
            )
            db.add(server)
            db.commit()
            db.refresh(server)
            logger.info(f"Created server record: {server.name} (ID: {server.id})")
            return server
        except IntegrityError as e:
            db.rollback()
            handle_database_error("create", "server", e)
        except Exception as e:
            db.rollback()
            handle_database_error("create", "server", e)

    def update_server_record(
        self, server: Server, request: ServerUpdateRequest, db: Session
    ) -> Server:
        try:
            for field_name, value in request.model_dump(exclude_unset=True).items():
                setattr(server, field_name, value)
            db.commit()
            db.refresh(server)
            logger.info(f"Updated server record: {server.name} (ID: {server.id})")
            return server
        except Exception as e:
            db.rollback()
            handle_database_error("update", "server", e)

    def soft_delete_server(self, server: Server, db: Session) -> None:
        try:
            server.is_deleted = True
            server.status = ServerStatus.stopped
            db.commit()
            logger.info(f"Soft deleted server: {server.name} (ID: {server.id})")
        except Exception as e:
            db.rollback()
            handle_database_error("delete", "server", e)
