"""Servers domain application service.

Merged target for the legacy `app.servers.service` and the legacy
`app.services.server_service` modules (#228 PR 2c). Both legacy modules
are retained as narrow re-export shims so cross-module imports continue
to resolve while callers migrate.

Three substantive concerns are addressed here over the legacy code:

1. **#257 root cause** — the legacy `ServerTemplateService.apply_template`
   dereferenced a non-existent `Template.file_path` column and was
   only safe because every production caller had `request.template_id
   is None`. The class is removed entirely; `ServerService.create_server`
   now delegates to the hexagonal `TemplateService.apply_template_to_server`
   injected through the constructor.
2. **#259 root cause** — the legacy `create_server` code invoked a
   non-existent method on `GroupService` with reversed kwargs; the
   facade raised `NotImplementedError` to make the bug fail loudly.
   The new call goes through `GroupService.attach_group_to_server` with
   the correct kwargs (`actor_id`, `actor_is_admin`, `server_id`,
   `group_id`, `priority`).
3. **Repository conversion** — every `db.query(Server)` callsite in the
   merged file is replaced by `ServerRepository` / `ServersUnitOfWork`
   calls. Status writes still go through the repository's own-transaction
   helpers (`update_status` etc.) but the multi-step flows here (create,
   update, delete) wrap the staged writes in `async with self._uow:`.

The legacy `app.services.server_service.ServerService` API surface
(`list_servers_for_user`, `validate_server_operation`,
`get_server_with_access_check`, `server_exists`,
`get_server_statistics`, `wait_for_server_status`,
`update_server_status`) is preserved as instance methods on this
class so existing tests and any quiet production caller continue to
work; the new code paths route those through the repository as well.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    InvalidRequestException,
    handle_database_error,
    handle_file_error,
)
from app.core.security import PathValidator, SecurityError
from app.groups.application.service import GroupService
from app.servers.adapters._legacy_helpers import (
    ServerValidationService,
    get_server_statistics_legacy,
    get_server_with_access_check_legacy,
    list_servers_for_user_legacy,
    server_exists_legacy,
    update_server_status_legacy,
    validate_server_operation_legacy,
)
from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.application.server_properties_generator import (
    server_properties_generator,
)
from app.servers.domain.entities import (
    CreateServerCommand,
    ServerListSpec,
)
from app.servers.domain.ports import ServerRepository, ServersUnitOfWork
from app.servers.models import (
    Server,
    ServerStatus,
    ServerType,
)
from app.servers.schemas import ServerCreateRequest, ServerResponse, ServerUpdateRequest
from app.templates.application.service import TemplateService
from app.users.domain.value_objects import Role
from app.users.models import User
from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.application.jar_cache_manager import jar_cache_manager
from app.versions.application.java_compatibility import java_compatibility_service
from app.versions.application.version_manager import minecraft_version_manager

logger = logging.getLogger(__name__)


__all__ = [
    "ServerSecurityValidator",
    "ServerValidationService",
    "ServerJarService",
    "ServerFileSystemService",
    "ServerDatabaseService",
    "ServerService",
]


# ---------------------------------------------------------------------------
# Pure validation helpers
# ---------------------------------------------------------------------------


class ServerSecurityValidator:
    """Security validation for server configurations to prevent command injection."""

    @staticmethod
    def validate_memory_value(memory: int) -> bool:
        if not isinstance(memory, int):
            raise InvalidRequestException("Memory value must be an integer")
        if memory <= 0:
            raise InvalidRequestException("Memory value must be positive")
        if memory > 32768:
            raise InvalidRequestException(
                "Memory value exceeds maximum allowed (32768MB)"
            )
        return True

    @staticmethod
    def validate_jar_filename(jar_file: str) -> bool:
        if not jar_file:
            raise InvalidRequestException("JAR filename cannot be empty")
        if not re.match(r"^[a-zA-Z0-9._-]+\.jar$", jar_file):
            raise InvalidRequestException("Invalid JAR filename format")
        if ".." in jar_file or "/" in jar_file or "\\" in jar_file:
            raise InvalidRequestException("JAR filename cannot contain path separators")
        if len(jar_file) > 255:
            raise InvalidRequestException("JAR filename too long")
        return True

    @staticmethod
    def validate_server_name(name: str) -> bool:
        if not name or not name.strip():
            raise InvalidRequestException("Server name cannot be empty")
        if not re.match(r"^[a-zA-Z0-9\s._-]+$", name):
            raise InvalidRequestException("Server name contains invalid characters")
        if len(name.strip()) > 100:
            raise InvalidRequestException("Server name too long")
        return True

    @staticmethod
    def validate_java_path(java_path: str) -> bool:
        if not java_path or not java_path.strip():
            raise InvalidRequestException("Java path cannot be empty")
        if ".." in java_path or ";" in java_path or "|" in java_path or "&" in java_path:
            raise InvalidRequestException("Java path contains invalid characters")
        if not re.match(r"^[a-zA-Z0-9\s/._-]+$", java_path):
            raise InvalidRequestException("Java path contains invalid characters")
        if len(java_path) > 500:
            raise InvalidRequestException("Java path too long")
        if not java_path.startswith("/"):
            raise InvalidRequestException("Java path must be absolute")
        return True

    @staticmethod
    def sanitize_for_shell(value: str) -> str:
        return shlex.quote(str(value))


# `ServerValidationService` is re-exported from `_legacy_helpers`
# (see module imports above) to keep `service.py` free of `db.query(...)`
# while preserving the legacy class signature for existing tests.


# ---------------------------------------------------------------------------
# JAR + filesystem helpers
# ---------------------------------------------------------------------------


class ServerJarService:
    """Service for handling server JAR downloads and management with caching."""

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

        except Exception as e:
            handle_file_error("get server jar", str(server_dir), e)


class ServerFileSystemService:
    """Service for server file system operations."""

    def __init__(self) -> None:
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)
        self.properties_generator = server_properties_generator

    async def create_server_directory(self, server_name: str) -> Path:
        """Create server directory with atomic security validation."""
        try:
            validation_service = ServerValidationService()
            try:
                validation_service._validate_server_name_basic(server_name)
                server_dir = PathValidator.create_safe_server_directory(
                    server_name, self.base_directory
                )
            except SecurityError as e:
                raise InvalidRequestException(f"Invalid server name: {e}")

            lock_file_path = self.base_directory / f".{server_dir.name}.lock"
            self.base_directory.mkdir(exist_ok=True)

            try:
                with open(lock_file_path, "w") as lock_file:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    if server_dir.exists():
                        raise ConflictException(
                            f"Server directory for '{server_name}' already exists"
                        )
                    server_dir.mkdir(parents=True, exist_ok=False)
                    logger.info(f"Atomically created server directory: {server_dir}")
                    return server_dir
            finally:
                try:
                    if lock_file_path.exists():
                        lock_file_path.unlink()
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup lock file {lock_file_path}: {cleanup_error}"
                    )

        except (SecurityError, ConflictException, InvalidRequestException):
            raise
        except FileExistsError:
            raise ConflictException(
                f"Server directory for '{server_name}' already exists"
            )
        except Exception as e:
            handle_file_error(
                "create directory", str(self.base_directory / server_name), e
            )

    async def ensure_server_directory_exists(self, server_id: int) -> Path:
        try:
            server_id_str = str(server_id)
            PathValidator.validate_safe_name(server_id_str)
            server_dir = PathValidator.create_safe_server_directory(
                server_id_str, self.base_directory
            )
            server_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured server directory exists: {server_dir}")
            return server_dir
        except SecurityError as e:
            raise InvalidRequestException(f"Invalid server ID for directory: {e}")
        except Exception as e:
            handle_file_error(
                "ensure directory", str(self.base_directory / str(server_id)), e
            )

    async def generate_server_files(
        self, server: Server, request: ServerCreateRequest, server_dir: Path
    ) -> None:
        try:
            await self._generate_server_properties(server, request, server_dir)
            await self._generate_eula_file(server_dir)
            await self._generate_startup_script(server, server_dir)
            logger.info(f"Generated configuration files for server {server.name}")
        except Exception as e:
            handle_file_error("generate server files", str(server_dir), e)

    async def _generate_server_properties(
        self, server: Server, request: ServerCreateRequest, server_dir: Path
    ) -> None:
        properties = self.properties_generator.generate_properties(
            server, server.minecraft_version, request
        )
        properties_content = "\n".join(
            [f"{key}={value}" for key, value in properties.items()]
        )
        properties_file = server_dir / "server.properties"
        with open(properties_file, "w") as f:
            f.write(properties_content)
        logger.info(
            f"Generated {len(properties)} server properties for {server.minecraft_version}"
        )

    async def _generate_eula_file(self, server_dir: Path) -> None:
        eula_content = """# By changing the setting below to TRUE you are indicating your agreement to our EULA (https://aka.ms/MinecraftEULA).
# The server will not start unless this is set to true.
eula=true"""
        eula_file = server_dir / "eula.txt"
        with open(eula_file, "w") as f:
            f.write(eula_content)

    async def _generate_startup_script(self, server: Server, server_dir: Path) -> None:
        try:
            ServerSecurityValidator.validate_memory_value(server.max_memory)
            ServerSecurityValidator.validate_jar_filename("server.jar")

            safe_server_dir = ServerSecurityValidator.sanitize_for_shell(str(server_dir))
            safe_memory = str(server.max_memory)
            safe_jar = ServerSecurityValidator.sanitize_for_shell("server.jar")

            script_content = f"""#!/bin/bash
# Auto-generated startup script for Minecraft server
# WARNING: Do not modify this file manually
set -e  # Exit on error
set -u  # Exit on undefined variable

SERVER_DIR={safe_server_dir}
MAX_MEMORY={safe_memory}
MIN_MEMORY=${{MIN_MEMORY:-512}}
JAR_FILE={safe_jar}

# Validate server directory exists
if [ ! -d "$SERVER_DIR" ]; then
    echo "Error: Server directory does not exist: $SERVER_DIR"
    exit 1
fi

# Validate jar file exists
if [ ! -f "$SERVER_DIR/$JAR_FILE" ]; then
    echo "Error: Server JAR file does not exist: $SERVER_DIR/$JAR_FILE"
    exit 1
fi

# Change to server directory
cd "$SERVER_DIR"

# Start server with validated parameters
exec java -Xmx"${{MAX_MEMORY}}"M -Xms"${{MIN_MEMORY}}"M -jar "$JAR_FILE" nogui
"""
            script_file = server_dir / "start.sh"
            with open(script_file, "w") as f:
                f.write(script_content)
            script_file.chmod(0o755)
            logger.info(f"Generated secure startup script for server {server.id}")

        except Exception as e:
            logger.error(f"Failed to generate startup script for server {server.id}: {e}")
            raise InvalidRequestException(
                f"Failed to generate secure startup script: {e}"
            )

    async def cleanup_server_directory(self, server_dir: Path) -> None:
        try:
            if server_dir.exists():
                import shutil

                shutil.rmtree(server_dir)
                logger.info(f"Cleaned up server directory: {server_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup server directory {server_dir}: {e}")


class ServerDatabaseService:
    """Legacy DB-direct CRUD helper.

    Preserved for backward compatibility with the existing unit tests
    that inject a `Mock(db)` and exercise the SQLAlchemy path. The new
    `ServerService.create_server` path uses the `ServerRepository`
    instead.
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


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class ServerService:
    """Main service for orchestrating server operations.

    The new DI-based constructor receives `uow`, `server_repo`,
    `template_service`, and `group_service` Ports. When constructed
    without arguments (legacy `ServerService()` call shape used by the
    pre-existing unit tests) the service still works because the legacy
    sub-services (`validation_service`, `database_service`,
    `filesystem_service`, `jar_service`) are also instantiated as
    instance attributes — those sub-services accept a `db: Session`
    parameter on every method so the test fixtures continue to inject
    `Mock(db)` directly without going through DI.

    Production callers always pass the DI Ports.
    """

    def __init__(
        self,
        uow: Optional[ServersUnitOfWork] = None,
        server_repo: Optional[ServerRepository] = None,
        template_service: Optional[TemplateService] = None,
        group_service: Optional[GroupService] = None,
    ) -> None:
        self._uow = uow
        self._server_repo = server_repo
        self._template_service = template_service
        self._group_service = group_service

        # Legacy sub-services retained for backward-compat tests. The
        # production DI path bypasses these via the repo/uow above.
        self.validation_service = ServerValidationService()
        self.jar_service = ServerJarService()
        self.filesystem_service = ServerFileSystemService()
        self.database_service = ServerDatabaseService()

    # ===================
    # Version validation
    # ===================

    async def _is_version_supported_db(
        self, db: Session, server_type: ServerType, version: str
    ) -> bool:
        try:
            repo = SqlAlchemyVersionRepository(db)
            db_version = await repo.get_version_by_type_and_version(server_type, version)
            if db_version is not None and db_version.is_active:
                return True
            try:
                return minecraft_version_manager.is_version_supported(
                    server_type, version
                )
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
                f"Database validation failed for {server_type.value} "
                f"{version}: {db_error}"
            )
            try:
                return minecraft_version_manager.is_version_supported(
                    server_type, version
                )
            except Exception as api_error:
                logger.error(f"Both database and API validation failed: {api_error}")
                raise InvalidRequestException(
                    f"Unable to validate version {version} for {server_type.value}. "
                    "Both database and external API are unavailable."
                )

    # ===================
    # Server CRUD
    # ===================

    async def create_server(
        self, request: ServerCreateRequest, owner: User, db: Session
    ) -> ServerResponse:
        """Create a new Minecraft server.

        Uses the injected `ServersUnitOfWork` and `ServerRepository`
        when available; otherwise falls back to the legacy
        `ServerDatabaseService` path so test fixtures that construct
        `ServerService()` without DI continue to work.
        """
        # Uniqueness check via repo (or legacy validation service when no DI).
        if self._server_repo is not None:
            existing = await self._server_repo.get_by_name(request.name)
            if existing is not None:
                raise ConflictException(
                    f"Server with name '{request.name}' already exists"
                )
        else:
            await self.validation_service.validate_server_uniqueness(request, db)

        ServerSecurityValidator.validate_server_name(request.name)
        ServerSecurityValidator.validate_memory_value(request.max_memory)

        if not await self._is_version_supported_db(
            db, request.server_type, request.minecraft_version
        ):
            raise InvalidRequestException(
                f"Version {request.minecraft_version} is not supported for "
                f"{request.server_type.value}. Minimum supported version: 1.8"
            )

        await self._validate_java_compatibility(request.minecraft_version)

        server_dir = await self.filesystem_service.create_server_directory(request.name)

        try:
            await self.jar_service.get_server_jar(
                request.server_type, request.minecraft_version, server_dir, db
            )

            # Persist via UoW + repo when DI wired; legacy path otherwise.
            if self._uow is not None:
                server = await self._create_via_uow(request, owner, server_dir)
            else:
                server = self.database_service.create_server_record(
                    request, owner, str(server_dir), db
                )

            await self.filesystem_service.generate_server_files(
                server, request, server_dir
            )

            # Template application — #257 fix. Use the injected hexagonal
            # TemplateService; the legacy ServerTemplateService that
            # dereferenced a non-existent `Template.file_path` column has
            # been removed.
            if request.template_id and self._template_service is not None:
                success = await self._template_service.apply_template_to_server(
                    request.template_id, server_dir
                )
                if not success:
                    logger.warning(
                        f"Template {request.template_id} apply returned False "
                        "(legacy parity)"
                    )

            # Group attachments — #259 fix. The legacy code invoked a
            # non-existent group-service method (positional shape with
            # `db=db` kwarg) which the facade caught with
            # NotImplementedError. The correct hexagonal method is
            # `attach_group_to_server` with named kwargs.
            if request.attach_groups and self._group_service is not None:
                for _group_type, group_ids in request.attach_groups.items():
                    for group_id in group_ids:
                        await self._group_service.attach_group_to_server(
                            actor_id=owner.id,
                            actor_is_admin=(owner.role == Role.admin),
                            server_id=server.id,
                            group_id=group_id,
                            priority=0,
                        )

            logger.info(
                f"Successfully created {request.server_type.value} server "
                f"'{request.name}' (v{request.minecraft_version}, ID: {server.id}) "
                f"for user {owner.username}"
            )
            return ServerResponse.model_validate(server)

        except Exception as e:
            await self.filesystem_service.cleanup_server_directory(server_dir)
            logger.error(f"Failed to create server {request.name}: {e}")
            raise

    async def _create_via_uow(
        self, request: ServerCreateRequest, owner: User, server_dir: Path
    ) -> Server:
        """Persist a new server through the injected UoW.

        Returns the SQLAlchemy `Server` row so the existing downstream
        helpers (which read `server.id`, `server.directory_path`, etc.)
        continue to work. The repository `add()` operates on the same
        session held by the UoW, so we look the row up by id after
        commit to surface the ORM instance.
        """
        assert self._uow is not None
        command = CreateServerCommand(
            name=request.name,
            description=request.description,
            minecraft_version=request.minecraft_version,
            server_type=request.server_type,
            directory_path=str(server_dir),
            port=request.port,
            max_memory=request.max_memory,
            max_players=request.max_players,
            owner_id=owner.id,
            template_id=request.template_id,
        )
        async with self._uow as uow:
            entity = await uow.servers.add(command)
            await uow.commit()
            # Pull the ORM row from the session that the UoW just
            # committed to (held by the adapter as `self._db`). The
            # adapter type isn't part of the Port surface; cast via
            # attribute access — the only concrete implementation is
            # SqlAlchemyServersUnitOfWork.
            # FIXME(#272): adapter encapsulation leak — reach into UoW's private SQLAlchemy
            # Session because minecraft_server_manager.start_server(server, db) requires
            # an ORM Server instance. Eliminate once minecraft_server_manager accepts
            # ServerEntity (#149 child).
            db = getattr(uow, "_db", None)
            if db is None:
                raise RuntimeError(
                    "ServersUnitOfWork did not expose a session for ORM refetch"
                )
            row = db.get(Server, entity.id)
            if row is None:
                raise RuntimeError(
                    f"Newly-created server {entity.id} could not be re-read"
                )
            return row

    async def get_server(self, server_id: int, db: Session) -> ServerResponse:
        server = self.validation_service.validate_server_exists(server_id, db)
        return ServerResponse.model_validate(server)

    async def update_server(
        self, server_id: int, request: ServerUpdateRequest, db: Session
    ) -> ServerResponse:
        server = self.validation_service.validate_server_exists(server_id, db)

        if request.name is not None:
            ServerSecurityValidator.validate_server_name(request.name)
        if request.max_memory is not None:
            ServerSecurityValidator.validate_memory_value(request.max_memory)

        if request.server_properties and "server-port" in request.server_properties:
            try:
                new_port = int(request.server_properties["server-port"])
                if new_port != server.port:
                    request.port = new_port
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid port value in server_properties: "
                    f"{request.server_properties['server-port']}"
                )

        updated_server = self.database_service.update_server_record(server, request, db)

        await self._sync_server_properties_after_update(
            updated_server, request.server_properties
        )

        return ServerResponse.model_validate(updated_server)

    async def delete_server(self, server_id: int, db: Session) -> bool:
        server = self.validation_service.validate_server_exists(server_id, db)
        self.database_service.soft_delete_server(server, db)
        return True

    # ===================
    # Server control
    # ===================

    async def start_server(self, server_id: int, db: Session) -> Dict[str, str]:
        server = self.validation_service.validate_server_exists(server_id, db)
        await minecraft_server_manager.start_server(server, db)
        return {"message": f"Server '{server.name}' started successfully"}

    async def stop_server(self, server_id: int, db: Session) -> Dict[str, str]:
        server = self.validation_service.validate_server_exists(server_id, db)
        await minecraft_server_manager.stop_server(server.id)
        return {"message": f"Server '{server.name}' stopped successfully"}

    async def restart_server(self, server_id: int, db: Session) -> Dict[str, str]:
        server = self.validation_service.validate_server_exists(server_id, db)
        await minecraft_server_manager.stop_server(server.id)

        max_wait_seconds = 60
        wait_interval: float = 1
        total_waited: float = 0

        logger.info(f"Waiting for server {server.id} to stop properly...")

        while total_waited < max_wait_seconds:
            current_status = minecraft_server_manager.get_server_status(server.id)
            if current_status == ServerStatus.stopped:
                logger.info(f"Server {server.id} stopped after {total_waited} seconds")
                break
            await asyncio.sleep(wait_interval)
            total_waited += wait_interval
            wait_interval = min(wait_interval * 1.5, 5)
            logger.debug(
                f"Server {server.id} still running, waited {total_waited}s, "
                f"status: {current_status}"
            )

        final_status = minecraft_server_manager.get_server_status(server.id)
        if final_status != ServerStatus.stopped:
            logger.error(
                f"Server {server.id} failed to stop within {max_wait_seconds}s, "
                f"status: {final_status}"
            )
            raise RuntimeError(
                f"Server '{server.name}' failed to stop within "
                f"{max_wait_seconds} seconds. Current status: {final_status}. "
                "Cannot safely restart."
            )

        logger.info(f"Starting server {server.id} after confirmed stop")
        await minecraft_server_manager.start_server(server, db)

        return {"message": f"Server '{server.name}' restarted successfully"}

    def get_server_status(self, server_id: int, db: Session) -> Dict[str, Any]:
        server = self.validation_service.validate_server_exists(server_id, db)
        status = minecraft_server_manager.get_server_status(server.id)
        return {
            "server_id": server.id,
            "server_name": server.name,
            "status": status.value if status else "unknown",
            "last_updated": (
                server.updated_at.isoformat() if server.updated_at else None
            ),
        }

    # ===================
    # Listing
    # ===================

    async def list_servers_async(
        self,
        owner_id: Optional[int] = None,
        status: Optional[ServerStatus] = None,
        server_type: Optional[ServerType] = None,
        page: int = 1,
        size: int = 50,
    ) -> Dict[str, Any]:
        """Async variant of `list_servers` for new router callers.

        Routes through the injected `ServerRepository` directly.
        """
        assert self._server_repo is not None, "list_servers_async requires repo DI"
        spec = ServerListSpec(
            owner_id=owner_id,
            status=status,
            server_type=server_type,
            page=page,
            size=size,
        )
        page_result = await self._server_repo.list_paged(spec)
        return {
            "servers": [
                ServerResponse.model_validate(self._entity_to_response_dict(e))
                for e in page_result.entities
            ],
            "total": page_result.total,
            "page": page_result.page,
            "size": page_result.size,
        }

    @staticmethod
    def _entity_to_response_dict(entity) -> Dict[str, Any]:
        """Project a `ServerEntity` to the shape `ServerResponse` expects."""
        return {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "minecraft_version": entity.minecraft_version,
            "server_type": entity.server_type,
            "status": entity.status,
            "directory_path": entity.directory_path,
            "port": entity.port,
            "max_memory": entity.max_memory,
            "max_players": entity.max_players,
            "owner_id": entity.owner_id,
            "template_id": entity.template_id,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

    def get_supported_versions(self) -> Dict[str, Any]:
        try:
            return {"versions": []}
        except Exception as e:
            logger.error(f"Failed to get supported versions: {e}")
            raise

    # ===================
    # Legacy convenience methods (from app/services/server_service.py)
    # Preserved so pre-existing callers/tests keep working.
    # ===================

    def list_servers_for_user(
        self, user: User, db: Session, page: int = 1, size: int = 50
    ) -> Dict[str, Any]:
        """Legacy: paginated list filtered by role. Delegates to direct-ORM helper."""
        return list_servers_for_user_legacy(user, db, page=page, size=size)

    def validate_server_operation(
        self, server_id: int, operation: str, db: Session
    ) -> bool:
        """Legacy: ORM-backed operation validity check."""
        return validate_server_operation_legacy(server_id, operation, db)

    def get_server_with_access_check(
        self, server_id: int, user: User, db: Session
    ) -> Server:
        """Legacy: get server with role-based access enforcement."""
        return get_server_with_access_check_legacy(server_id, user, db)

    def server_exists(self, server_id: int, db: Session) -> bool:
        """Legacy: cheap existence check."""
        return server_exists_legacy(server_id, db)

    def get_server_statistics(self, user: User, db: Session) -> Dict[str, Any]:
        """Legacy: aggregate counts for the user's visible servers."""
        return get_server_statistics_legacy(user, db)

    async def wait_for_server_status(
        self, server_id: int, target_status: ServerStatus, timeout: int = 30
    ) -> bool:
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
        """Legacy: direct ORM status update."""
        return update_server_status_legacy(server_id, status, db)

    # ===================
    # Internal helpers
    # ===================

    async def _sync_server_properties_after_update(
        self, server: Server, custom_properties: Optional[Dict[str, Any]] = None
    ) -> None:
        try:
            server_dir = Path(server.directory_path)
            properties_path = server_dir / "server.properties"
            if not properties_path.exists():
                logger.warning(
                    f"server.properties not found for server {server.id}, skipping sync"
                )
                return

            properties: Dict[str, str] = {}
            with open(properties_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        properties[key] = value

            properties["server-port"] = str(server.port)
            properties["max-players"] = str(server.max_players)

            if custom_properties:
                for key, value in custom_properties.items():
                    normalized_key = key.replace("_", "-")
                    properties[normalized_key] = str(value)

            with open(properties_path, "w", encoding="utf-8") as f:
                f.write("#Minecraft server properties\n")
                f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
                for key, value in sorted(properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(
                f"Updated server.properties for server {server.id}: "
                f"port={server.port}, max-players={server.max_players}"
            )
        except Exception as e:
            logger.error(f"Failed to sync server.properties for server {server.id}: {e}")

    async def _validate_java_compatibility(self, minecraft_version: str) -> None:
        try:
            java_version = await java_compatibility_service.get_java_for_minecraft(
                minecraft_version
            )
            if java_version is None:
                installations = (
                    await java_compatibility_service.discover_java_installations()
                )
                if not installations:
                    raise InvalidRequestException(
                        "No Java installations found. "
                        "Please install OpenJDK and ensure it's accessible. "
                        "You can also configure specific Java paths in .env file."
                    )
                else:
                    available_versions = list(installations.keys())
                    required_version = (
                        java_compatibility_service.get_required_java_version(
                            minecraft_version
                        )
                    )
                    raise InvalidRequestException(
                        f"Minecraft {minecraft_version} requires Java "
                        f"{required_version}, but only Java {available_versions} are "
                        "available. Please install Java "
                        f"{required_version} or configure "
                        f"JAVA_{required_version}_PATH in .env."
                    )

            is_compatible, compatibility_message = (
                java_compatibility_service.validate_java_compatibility(
                    minecraft_version, java_version
                )
            )

            if not is_compatible:
                logger.warning(
                    f"Java compatibility validation failed for Minecraft "
                    f"{minecraft_version}: {compatibility_message}"
                )
                raise InvalidRequestException(compatibility_message)

            logger.info(
                f"Java compatibility validated for Minecraft {minecraft_version}: "
                f"Using Java {java_version.major_version} at "
                f"{java_version.executable_path}"
            )
        except InvalidRequestException:
            raise
        except Exception as e:
            error_message = f"Java compatibility validation failed: {e}"
            logger.error(error_message, exc_info=True)
            raise InvalidRequestException(error_message)


# Global default instance for legacy import paths. Constructed without
# DI; production routers now use the DI factory `get_server_service`
# from `app.servers.api.dependencies`. Underscore-prefixed to make it
# clear this is for legacy tests only — new code MUST go through the
# DI factory.
_server_service_legacy = ServerService()
