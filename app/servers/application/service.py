"""Servers domain application service.

Merged target for the legacy `app.servers.service` and the legacy
`app.services.server_service` modules (#228 PR 2c). Both legacy shims
have been removed (#276 / #290) — all callers import from this module
directly.

Three substantive concerns are addressed here over the legacy code:

1. **#259 root cause** — the legacy `create_server` code invoked a
   non-existent method on `GroupService` with reversed kwargs; the
   facade raised `NotImplementedError` to make the bug fail loudly.
   The new call goes through `GroupService.attach_group_to_server` with
   the correct kwargs (`actor_id`, `actor_is_admin`, `server_id`,
   `group_id`, `priority`).
2. **Repository conversion** — every `db.query(Server)` callsite in the
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
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.core.error_schemas import ErrorDetail
from app.core.exceptions import (
    ConflictException,
    FileOperationException,
    InvalidRequestException,
    handle_file_error,
)
from app.core.security import PathValidator, SecurityError
from app.groups.application.service import GroupService

# `ServerJarService` / `ServerDatabaseService` originally lived in this
# module but consume a `Session` at runtime, so they were moved to the
# adapter layer in #285 (ARCHITECTURE Section 4.2 — application/ must not
# depend on a framework). They are re-imported here purely so the
# pre-existing public API
# (`from app.servers.application.service import ServerJarService`)
# keeps resolving for legacy callers and unit tests.
from app.servers.adapters._legacy_helpers import (
    ServerDatabaseService,
    ServerJarService,
    ServerValidationService,
    get_server_statistics_legacy,
    get_server_with_access_check_legacy,
    is_version_supported_db_legacy,
    list_servers_for_user_legacy,
    server_exists_legacy,
    update_server_status_legacy,
    validate_server_operation_legacy,
)
from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.application.port_allocator import (
    find_available_ports,
    port_holder,
)
from app.servers.application.server_properties_generator import (
    server_properties_generator,
)
from app.servers.domain.entities import (
    CreateServerCommand,
    ServerListSpec,
    UpdateServerCommand,
)
from app.servers.domain.exceptions import (
    JavaCompatibilityError,
    NoAvailablePortError,
    ServerCreationRollbackError,
    ServerJarDownloadError,
    ServerNameConflictError,
    ServerPortConflictError,
    UnsupportedMinecraftVersionError,
)
from app.servers.domain.ports import ServerRepository, ServersUnitOfWork
from app.servers.models import (
    Server,
    ServerStatus,
    ServerType,
)
from app.servers.schemas import ServerCreateRequest, ServerResponse, ServerUpdateRequest
from app.users.domain.value_objects import Role
from app.users.models import User
from app.versions.application.java_compatibility import java_compatibility_service

# `Session` is used only as a type annotation on legacy passthrough
# methods that forward the value to ``_legacy_helpers`` (which lives in
# adapters/). With ``from __future__ import annotations`` enabled the
# names are strings at runtime, so we keep the import under
# ``TYPE_CHECKING`` to keep the application module framework-free at
# runtime (ARCHITECTURE Section 4.2, #285).
if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.servers.schemas import ValidateServerCreationResponse

logger = logging.getLogger(__name__)


__all__ = [
    "ServerSecurityValidator",
    "ServerValidationService",
    "ServerJarService",
    "ServerFileSystemService",
    "ServerDatabaseService",
    "ServerService",
]

# Default starting port for the auto-assign path (Issue #32). The
# Minecraft community convention is 25565; we walk upward from there
# when ``ServerCreateRequest.port`` is omitted. Hardcoded — see the
# delivery plan: making this configurable adds knobs without a known
# caller and complicates the discovery endpoint contract.
DEFAULT_PORT_START = 25565


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


# `ServerJarService` and `ServerDatabaseService` (the SQLAlchemy-direct
# legacy CRUD helpers) live in ``app.servers.adapters._legacy_helpers``
# after #285. They are re-imported at the top of this module for
# back-compat so legacy imports / unit tests continue to work.


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class ServerService:
    """Main service for orchestrating server operations.

    The new DI-based constructor receives `uow`, `server_repo`,
    and `group_service` Ports. When constructed
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
        group_service: Optional[GroupService] = None,
    ) -> None:
        self._uow = uow
        self._server_repo = server_repo
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
        """Thin passthrough to the SQLAlchemy-direct legacy helper.

        The implementation was moved to
        ``app.servers.adapters._legacy_helpers.is_version_supported_db_legacy``
        in #285 so this module no longer constructs adapter classes
        directly (ARCHITECTURE Section 4.2).
        """
        return await is_version_supported_db_legacy(db, server_type, version)

    # ===================
    # Server CRUD
    # ===================

    async def create_server(
        self, request: ServerCreateRequest, owner: User, db: Session
    ) -> ServerResponse:
        """Create a new Minecraft server.

        Performs pre-flight validation (name uniqueness, port
        availability among active servers, version support, Java
        compatibility) **before** mutating the filesystem so failure
        modes surface as actionable structured errors rather than
        partially-created server directories (Issue #33).

        Uses the injected `ServersUnitOfWork` and `ServerRepository`
        when available; otherwise falls back to the legacy
        `ServerDatabaseService` path so test fixtures that construct
        `ServerService()` without DI continue to work.
        """
        # ---- Pre-flight validation (Issue #33) -----------------------
        # All checks below MUST raise domain exceptions with a stable
        # ``error_code``; the global handler maps them to actionable
        # HTTP responses.
        await self._validate_creation_preconditions(request, db)

        # ---- Filesystem + persistence stage --------------------------
        logger.info(
            "server_create_step",
            extra={
                "stage": "directory_create",
                "server_name": request.name,
                "owner_id": owner.id,
            },
        )
        server_dir = await self.filesystem_service.create_server_directory(request.name)

        try:
            logger.info(
                "server_create_step",
                extra={
                    "stage": "jar_download",
                    "server_name": request.name,
                    "server_type": request.server_type.value,
                    "minecraft_version": request.minecraft_version,
                },
            )
            try:
                await self.jar_service.get_server_jar(
                    request.server_type, request.minecraft_version, server_dir, db
                )
            except (
                ServerJarDownloadError,
                UnsupportedMinecraftVersionError,
            ):
                # Already an actionable domain exception — propagate.
                raise
            except FileOperationException as e:
                # `_legacy_helpers.ServerJarService.get_server_jar`
                # currently funnels every JAR failure through
                # ``handle_file_error`` which re-raises as
                # FileOperationException. Re-classify as a structured
                # ``ServerJarDownloadError`` so the frontend gets a 502
                # with a retry hint instead of a generic 500.
                raise ServerJarDownloadError(
                    server_type=request.server_type.value,
                    version=request.minecraft_version,
                    reason=str(e.detail) if e.detail else "unknown",
                    retry_hint=(
                        "Check upstream availability and retry. Clearing "
                        "the JAR cache may help if a partial download "
                        "is suspected."
                    ),
                ) from e

            # Persist via UoW + repo when DI wired; legacy path otherwise.
            logger.info(
                "server_create_step",
                extra={"stage": "persist", "server_name": request.name},
            )
            if self._uow is not None:
                server = await self._create_via_uow(request, owner, server_dir)
            else:
                server = self.database_service.create_server_record(
                    request, owner, str(server_dir), db
                )

            logger.info(
                "server_create_step",
                extra={
                    "stage": "generate_files",
                    "server_name": request.name,
                    "server_id": server.id,
                },
            )
            await self.filesystem_service.generate_server_files(
                server, request, server_dir
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
            stage = "post_directory"
            error_code = getattr(e, "error_code", e.__class__.__name__)
            logger.exception(
                "server_create_failed",
                extra={
                    "stage": stage,
                    "error_code": error_code,
                    "server_name": request.name,
                },
            )
            try:
                await self.filesystem_service.cleanup_server_directory(server_dir)
            except Exception as cleanup_error:  # pragma: no cover - defensive
                logger.error(
                    "server_create_rollback_failed",
                    extra={
                        "stage": stage,
                        "error_code": error_code,
                        "server_name": request.name,
                        "rollback_error": str(cleanup_error),
                    },
                )
                # Surface the rollback failure to the caller so an
                # operator can intervene (a stranded directory remains
                # on disk). Chain the original error for traceability.
                raise ServerCreationRollbackError(
                    stage=stage,
                    original_error=str(e),
                ) from cleanup_error
            raise

    async def _validate_creation_preconditions(
        self, request: ServerCreateRequest, db: Session
    ) -> None:
        """Run all pre-flight checks for ``create_server`` (Issue #33).

        Order is deliberate: cheap in-memory and DB-only checks first
        (name, port), then the version lookup, then the Java probe
        which may need to walk the filesystem. Each failure raises a
        dedicated domain exception with an ``error_code`` and (where
        relevant) structured ``extra_details``.
        """
        # ---- Name uniqueness ----
        logger.info(
            "server_create_step",
            extra={"stage": "name_check", "server_name": request.name},
        )
        if self._server_repo is not None:
            existing = await self._server_repo.get_by_name(request.name)
            if existing is not None:
                raise ServerNameConflictError(request.name)
        else:
            # Legacy fallback used by unit tests that construct
            # ``ServerService()`` without DI. Translate the legacy
            # ``ConflictException`` into the structured error so the
            # router contract stays uniform.
            try:
                await self.validation_service.validate_server_uniqueness(request, db)
            except ConflictException as e:
                raise ServerNameConflictError(request.name) from e

        # ---- Static safety checks ----
        ServerSecurityValidator.validate_server_name(request.name)
        ServerSecurityValidator.validate_memory_value(request.max_memory)

        # ---- Auto-assign port (Issue #32) ----
        # When ``port`` is omitted, walk from ``DEFAULT_PORT_START`` to
        # find the first free port. Done **before** the conflict check
        # below so the conflict path always sees a concrete integer.
        # The discovery only consults the database (active-status
        # servers) — see ``port_allocator.find_available_ports``.
        if request.port is None:
            if self._server_repo is None:
                # Legacy fallback (no DI). Best-effort: default to the
                # historical 25565 and let downstream logic surface a
                # conflict if needed. The repo-less path is exercised
                # only by unit tests that mock ``database_service``.
                request.port = DEFAULT_PORT_START
            else:
                picks = await find_available_ports(
                    self._server_repo, DEFAULT_PORT_START, count=1
                )
                if not picks:
                    raise NoAvailablePortError(start_port=DEFAULT_PORT_START)
                request.port = picks[0]
                logger.info(
                    "server_create_port_auto_assigned",
                    extra={
                        "server_name": request.name,
                        "assigned_port": request.port,
                    },
                )

        # ---- Port pre-flight ----
        logger.info(
            "server_create_step",
            extra={
                "stage": "port_check",
                "server_name": request.name,
                "port": request.port,
            },
        )
        if self._server_repo is not None:
            holder_name = await port_holder(self._server_repo, request.port)
            if holder_name is not None:
                suggestions = await find_available_ports(
                    self._server_repo, start_port=request.port + 1, count=3
                )
                raise ServerPortConflictError(
                    port=request.port,
                    conflicting_server=holder_name,
                    suggested_ports=suggestions,
                )

        # ---- Version support ----
        logger.info(
            "server_create_step",
            extra={
                "stage": "version_check",
                "server_name": request.name,
                "server_type": request.server_type.value,
                "minecraft_version": request.minecraft_version,
            },
        )
        try:
            supported = await self._is_version_supported_db(
                db, request.server_type, request.minecraft_version
            )
        except InvalidRequestException as e:
            # Both DB and upstream lookups failed — surface as the
            # version-unsupported domain code so the frontend can
            # offer a retry instead of rendering a 500.
            raise UnsupportedMinecraftVersionError(
                version=request.minecraft_version,
                server_type=request.server_type.value,
            ) from e
        if not supported:
            raise UnsupportedMinecraftVersionError(
                version=request.minecraft_version,
                server_type=request.server_type.value,
            )

        # ---- Java compatibility ----
        logger.info(
            "server_create_step",
            extra={
                "stage": "java_check",
                "server_name": request.name,
                "minecraft_version": request.minecraft_version,
            },
        )
        await self._validate_java_compatibility(request.minecraft_version)

    async def validate_creation_request(
        self, request: ServerCreateRequest, db: Session
    ) -> "ValidateServerCreationResponse":
        """Pre-validate a create-server request without mutating state.

        Powers the ``POST /api/v1/servers/validate`` endpoint added under
        Issue #33 so frontends can render inline validation feedback
        before committing the user to the create button. Returns a
        :class:`ValidateServerCreationResponse` with ``valid=False`` and
        a populated ``warnings`` list on failure (rather than raising)
        so the caller can render multiple issues at once.
        """
        from app.servers.schemas import ValidateServerCreationResponse

        warnings: List[ErrorDetail] = []
        try:
            await self._validate_creation_preconditions(request, db)
            valid = True
        except (
            ServerNameConflictError,
            ServerPortConflictError,
            UnsupportedMinecraftVersionError,
            JavaCompatibilityError,
        ) as exc:
            valid = False
            warnings.append(
                ErrorDetail(
                    field=None,
                    message=str(exc),
                    code=exc.error_code,
                )
            )
            extra_fn = getattr(exc, "extra_details", None)
            if callable(extra_fn):
                try:
                    warnings.extend(list(extra_fn()))
                except Exception:  # pragma: no cover - defensive
                    pass
        except InvalidRequestException as exc:
            valid = False
            warnings.append(
                ErrorDetail(
                    field=None,
                    message=str(exc.detail) if exc.detail else "invalid request",
                    code=getattr(exc, "error_code", "INVALID_REQUEST"),
                )
            )

        # Always provide at least one alternative port suggestion when
        # the repo is wired — useful both for the conflict path and for
        # frontends that want to show "free ports near your choice"
        # affordances independent of any failure. When the request omits
        # ``port`` entirely (Issue #32 auto-assign), the
        # ``_validate_creation_preconditions`` call above has already
        # populated ``request.port`` with the auto-assigned value; fall
        # back to the default start port if validation aborted before
        # that step ran.
        suggested_ports: List[int] = []
        if self._server_repo is not None:
            start = request.port if request.port is not None else DEFAULT_PORT_START
            suggested_ports = await find_available_ports(
                self._server_repo, start_port=start, count=3
            )

        return ValidateServerCreationResponse(
            valid=valid,
            warnings=warnings,
            suggested_ports=suggested_ports,
        )

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
        )
        async with self._uow as uow:
            entity = await uow.servers.add(command)
            await uow.commit()
            # Pull the ORM row from the session that the UoW just
            # committed to (held by the adapter as `self._db`). The
            # adapter type isn't part of the Port surface; cast via
            # attribute access — the only concrete implementation is
            # SqlAlchemyServersUnitOfWork.
            # NB(#272): the legacy reason for reaching into the UoW's
            # private session (``minecraft_server_manager.start_server``
            # used to require an ORM ``Server``) no longer applies — the
            # manager accepts ``ServerEntity`` now. The downstream
            # ``filesystem_service.generate_server_files`` / template
            # / group helpers below still want an ORM row to read
            # ``server.id`` / ``server.directory_path`` from, so the
            # refetch stays until those helpers are migrated separately
            # (#149).
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

        # Persist via UoW + repo when DI wired; legacy path otherwise
        # (parity with `create_server`). The legacy fallback preserves
        # the existing unit-test contract that constructs `ServerService()`
        # without DI and mocks `database_service.update_server_record`.
        if self._uow is not None:
            updated_server = await self._update_via_uow(server_id, request)
        else:
            updated_server = self.database_service.update_server_record(
                server, request, db
            )

        await self._sync_server_properties_after_update(
            updated_server, request.server_properties
        )

        return ServerResponse.model_validate(updated_server)

    async def _update_via_uow(
        self, server_id: int, request: ServerUpdateRequest
    ) -> Server:
        """Persist a server update through the injected UoW.

        Mirrors `_create_via_uow`: stages the write through the
        repository, commits, and then refetches the ORM row from the
        UoW's session so the downstream
        `_sync_server_properties_after_update` helper (which reads
        `server.directory_path`, `server.id`, `server.port`,
        `server.max_players` from an ORM row) continues to work without
        change.
        """
        assert self._uow is not None
        command = UpdateServerCommand(
            name=request.name,
            description=request.description,
            port=request.port,
            max_memory=request.max_memory,
            max_players=request.max_players,
        )
        async with self._uow as uow:
            entity = await uow.servers.update(server_id, command)
            if entity is None:
                # validate_server_exists() already guarded above; if the
                # row vanished between validation and update, surface a
                # clear error rather than letting None propagate.
                raise RuntimeError(
                    f"Server {server_id} vanished between validation and update"
                )
            await uow.commit()
            # See `_create_via_uow` for the rationale on refetching the
            # ORM row from the UoW's session — the downstream
            # `_sync_server_properties_after_update` helper still wants
            # an ORM-row shaped object and will be migrated separately
            # under #149.
            db = getattr(uow, "_db", None)
            if db is None:
                raise RuntimeError(
                    "ServersUnitOfWork did not expose a session for ORM refetch"
                )
            row = db.get(Server, server_id)
            if row is None:
                raise RuntimeError(f"Updated server {server_id} could not be re-read")
            return row

    async def delete_server(self, server_id: int, db: Session) -> bool:
        server = self.validation_service.validate_server_exists(server_id, db)
        # Persist via UoW + repo when DI wired; legacy path otherwise
        # (parity with `create_server` / `update_server`).
        if self._uow is not None:
            async with self._uow as uow:
                deleted = await uow.servers.soft_delete(server_id)
                if not deleted:
                    raise RuntimeError(
                        f"Server {server_id} vanished between validation and delete"
                    )
                await uow.commit()
        else:
            self.database_service.soft_delete_server(server, db)
        return True

    # ===================
    # Server control
    # ===================

    def _require_server_repo(self, db: Session) -> ServerRepository:
        """Return the injected ``ServerRepository`` for control flows.

        The canonical production path constructs ``ServerService``
        through ``get_server_service`` (which wires
        ``self._server_repo``). The legacy ``ServerService()`` shape
        (no DI) does not exercise ``start_server`` / ``stop_server`` /
        ``restart_server`` so we raise when the Port is not wired
        rather than reach into ``adapters/`` from the application
        layer (ARCHITECTURE Section 4.2). The ``db`` argument is accepted
        purely so the calling methods can still expose a
        ``db: Session`` annotation under TYPE_CHECKING for legacy
        signature parity.
        """
        if self._server_repo is None:
            raise RuntimeError(
                "ServerService.start_server / restart_server require a "
                "ServerRepository Port; construct the service via the "
                "DI factory `get_server_service` instead of bare "
                "`ServerService()`."
            )
        return self._server_repo

    async def start_server(self, server_id: int, db: Session) -> Dict[str, str]:
        # Existence check (kept on the legacy validator for the
        # not-found semantics it raises). The manager now accepts a
        # frozen ``ServerEntity`` and a ``ServerRepository`` (#272) so
        # we hand it the entity loaded through the Port instead of the
        # ORM row.
        server = self.validation_service.validate_server_exists(server_id, db)
        server_repository = self._require_server_repo(db)
        entity = await server_repository.get(server_id, include_deleted=False)
        if entity is None:
            raise RuntimeError(
                f"Server {server_id} vanished between validation and start"
            )
        await minecraft_server_manager.start_server(entity, server_repository)
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
        server_repository = self._require_server_repo(db)
        entity = await server_repository.get(server.id, include_deleted=False)
        if entity is None:
            raise RuntimeError(f"Server {server.id} vanished between stop and restart")
        await minecraft_server_manager.start_server(entity, server_repository)

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
                    if isinstance(value, bool):
                        properties[normalized_key] = str(value).lower()
                    else:
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
        """Verify a compatible Java runtime is installed for ``minecraft_version``.

        Raises :class:`JavaCompatibilityError` with structured context
        (required version, available versions) so the frontend can
        render an actionable install hint (Issue #33).
        """
        try:
            required_version: Optional[int] = None
            try:
                required_version = java_compatibility_service.get_required_java_version(
                    minecraft_version
                )
            except Exception:  # pragma: no cover - best-effort metadata
                required_version = None

            java_version = await java_compatibility_service.get_java_for_minecraft(
                minecraft_version
            )
            if java_version is None:
                installations = (
                    await java_compatibility_service.discover_java_installations()
                )
                available_versions: List[int] = (
                    list(installations.keys()) if installations else []
                )
                raise JavaCompatibilityError(
                    minecraft_version=minecraft_version,
                    required_java=required_version,
                    available_java=available_versions,
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
                raise JavaCompatibilityError(
                    minecraft_version=minecraft_version,
                    required_java=required_version,
                    available_java=[java_version.major_version],
                    message=compatibility_message,
                )

            logger.info(
                f"Java compatibility validated for Minecraft {minecraft_version}: "
                f"Using Java {java_version.major_version} at "
                f"{java_version.executable_path}"
            )
        except JavaCompatibilityError:
            raise
        except InvalidRequestException as e:
            # Translate the legacy code-path (still raised by older
            # ``java_compatibility_service`` failure modes) into the
            # structured Issue #33 exception.
            raise JavaCompatibilityError(
                minecraft_version=minecraft_version,
                required_java=None,
                message=str(e.detail) if e.detail else str(e),
            ) from e
        except Exception as e:
            error_message = f"Java compatibility validation failed: {e}"
            logger.error(error_message, exc_info=True)
            raise JavaCompatibilityError(
                minecraft_version=minecraft_version,
                required_java=None,
                message=error_message,
            ) from e


# Global default instance for legacy import paths. Constructed without
# DI; production routers now use the DI factory `get_server_service`
# from `app.servers.api.dependencies`. Underscore-prefixed to make it
# clear this is for legacy tests only — new code MUST go through the
# DI factory.
_server_service_legacy = ServerService()
