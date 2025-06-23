import asyncio
import fcntl
import logging
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    InvalidRequestException,
    ServerNotFoundException,
    handle_database_error,
    handle_file_error,
)
from app.core.security import PathValidator, SecurityError, TarExtractor
from app.servers.models import (
    Server,
    ServerStatus,
    ServerType,
    Template,
)
from app.servers.schemas import ServerCreateRequest, ServerResponse, ServerUpdateRequest
from app.services.group_service import GroupService
from app.services.jar_cache_manager import jar_cache_manager
from app.services.java_compatibility import java_compatibility_service
from app.services.minecraft_server import minecraft_server_manager
from app.services.server_properties_generator import server_properties_generator
from app.services.version_manager import minecraft_version_manager
from app.users.models import User
from app.versions.repository import VersionRepository

logger = logging.getLogger(__name__)


class ServerSecurityValidator:
    """Security validation for server configurations to prevent command injection"""

    @staticmethod
    def validate_memory_value(memory: int) -> bool:
        """Validate memory value is a positive integer within reasonable bounds"""
        if not isinstance(memory, int):
            raise InvalidRequestException("Memory value must be an integer")
        if memory <= 0:
            raise InvalidRequestException("Memory value must be positive")
        if memory > 32768:  # 32GB max reasonable limit
            raise InvalidRequestException(
                "Memory value exceeds maximum allowed (32768MB)"
            )
        return True

    @staticmethod
    def validate_jar_filename(jar_file: str) -> bool:
        """Validate jar filename to prevent path traversal and command injection"""
        if not jar_file:
            raise InvalidRequestException("JAR filename cannot be empty")

        # Only allow alphanumeric, dots, hyphens, underscores
        if not re.match(r"^[a-zA-Z0-9._-]+\.jar$", jar_file):
            raise InvalidRequestException("Invalid JAR filename format")

        # Prevent path traversal
        if ".." in jar_file or "/" in jar_file or "\\" in jar_file:
            raise InvalidRequestException("JAR filename cannot contain path separators")

        # Prevent excessively long filenames
        if len(jar_file) > 255:
            raise InvalidRequestException("JAR filename too long")

        return True

    @staticmethod
    def validate_server_name(name: str) -> bool:
        """Validate server name to prevent injection attacks"""
        if not name or not name.strip():
            raise InvalidRequestException("Server name cannot be empty")

        # Allow alphanumeric, spaces, dots, hyphens, underscores
        if not re.match(r"^[a-zA-Z0-9\s._-]+$", name):
            raise InvalidRequestException("Server name contains invalid characters")

        # Prevent excessively long names
        if len(name.strip()) > 100:
            raise InvalidRequestException("Server name too long")

        return True

    @staticmethod
    def validate_java_path(java_path: str) -> bool:
        """Validate Java executable path to prevent command injection"""
        if not java_path or not java_path.strip():
            raise InvalidRequestException("Java path cannot be empty")

        # Prevent path traversal and command injection
        if ".." in java_path or ";" in java_path or "|" in java_path or "&" in java_path:
            raise InvalidRequestException("Java path contains invalid characters")

        # Only allow reasonable path characters
        if not re.match(r"^[a-zA-Z0-9\s/._-]+$", java_path):
            raise InvalidRequestException("Java path contains invalid characters")

        # Prevent excessively long paths
        if len(java_path) > 500:
            raise InvalidRequestException("Java path too long")

        # Must be an absolute path for security
        if not java_path.startswith("/"):
            raise InvalidRequestException("Java path must be absolute")

        return True

    @staticmethod
    def sanitize_for_shell(value: str) -> str:
        """Sanitize string for safe shell usage"""
        # Use shlex.quote for proper shell escaping
        return shlex.quote(str(value))


class ServerValidationService:
    """Service for validating server operations"""

    def __init__(self):
        self.base_directory = Path("servers")

    async def validate_server_uniqueness(
        self, request: ServerCreateRequest, db: Session
    ) -> None:
        """Validate server name uniqueness

        Note: Port conflict validation is performed at server startup time,
        not during server creation. This allows users to create servers
        with duplicate ports and handle conflicts when starting servers.
        """
        # Check for existing server with same name
        existing_name = (
            db.query(Server)
            .filter(and_(Server.name == request.name, Server.is_deleted.is_(False)))
            .first()
        )
        if existing_name:
            raise ConflictException(f"Server with name '{request.name}' already exists")

    def validate_server_exists(self, server_id: int, db: Session) -> Server:
        """Validate server exists and return it"""
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, Server.is_deleted.is_(False)))
            .first()
        )
        if not server:
            raise ServerNotFoundException(str(server_id))
        return server

    def validate_server_directory(self, server_name: str) -> Path:
        """Validate and return server directory path"""
        try:
            # Validate server name has basic safety (allow spaces for display)
            self._validate_server_name_basic(server_name)

            # Create safe server directory path (converts spaces to underscores)
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
        """Basic validation for server names (allows spaces)"""
        if not server_name or not isinstance(server_name, str):
            raise SecurityError("Server name must be a non-empty string")

        if len(server_name) > 255:
            raise SecurityError("Server name too long (max 255 characters)")

        # Check for path traversal patterns
        if ".." in server_name:
            raise SecurityError("Server name cannot contain path traversal patterns (..)")

        if "\\" in server_name:
            raise SecurityError("Server name cannot contain backslashes")

        if server_name.startswith("/") or server_name.endswith("/"):
            raise SecurityError("Server name cannot start or end with slashes")

        # Check for starting/ending with spaces
        if server_name.startswith(" ") or server_name.endswith(" "):
            raise SecurityError("Server name cannot start or end with spaces")


class ServerJarService:
    """Service for handling server JAR downloads and management with caching"""

    def __init__(self):
        self.version_manager = minecraft_version_manager
        self.cache_manager = jar_cache_manager

    async def _is_version_supported_db(
        self, db: Session, server_type: ServerType, version: str
    ) -> bool:
        """Check if version is supported using database (FAST - ~10ms vs ~1000ms)"""
        try:
            repo = VersionRepository(db)
            db_version = await repo.get_version_by_type_and_version(server_type, version)
            if db_version is not None and db_version.is_active:
                return True
            # Fallback to external API if not found in database
            return self.version_manager.is_version_supported(server_type, version)
        except Exception:
            # Fallback to external API if database fails
            return self.version_manager.is_version_supported(server_type, version)

    async def _get_download_url_db(
        self, db: Session, server_type: ServerType, version: str
    ) -> Optional[str]:
        """Get download URL from database (FAST - ~10ms vs ~1000ms)"""
        try:
            repo = VersionRepository(db)
            db_version = await repo.get_version_by_type_and_version(server_type, version)
            if db_version and db_version.is_active and db_version.download_url:
                return db_version.download_url
            # Fallback to external API if not found in database
            return await self.version_manager.get_download_url(server_type, version)
        except Exception:
            # Fallback to external API if database fails
            return await self.version_manager.get_download_url(server_type, version)

    async def get_server_jar(
        self,
        server_type: ServerType,
        minecraft_version: str,
        server_dir: Path,
        db: Session,
    ) -> Path:
        """Get server JAR file (from cache or download) - FAST DATABASE VERSION"""
        try:
            # Validate version support using database (FAST - ~10ms vs ~1000ms)
            if not await self._is_version_supported_db(
                db, server_type, minecraft_version
            ):
                raise InvalidRequestException(
                    f"Version {minecraft_version} is not supported for {server_type.value} "
                    f"(minimum supported version: 1.8)"
                )

            # Get download URL from database (FAST - ~10ms vs ~1000ms)
            download_url = await self._get_download_url_db(
                db, server_type, minecraft_version
            )

            # Get JAR from cache or download
            cached_jar_path = await self.cache_manager.get_or_download_jar(
                server_type, minecraft_version, download_url
            )

            # Copy to server directory
            server_jar_path = await self.cache_manager.copy_jar_to_server(
                cached_jar_path, server_dir
            )

            logger.info(
                f"Prepared {server_type.value} {minecraft_version} JAR for server at {server_jar_path}"
            )
            return server_jar_path

        except Exception as e:
            handle_file_error("get server jar", str(server_dir), e)


class ServerFileSystemService:
    """Service for server file system operations"""

    def __init__(self):
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)
        self.properties_generator = server_properties_generator

    async def create_server_directory(self, server_name: str) -> Path:
        """Create server directory with atomic security validation to prevent race conditions"""
        try:
            # Use the validation service method that allows spaces
            validation_service = ServerValidationService()

            # Create safe server directory path (this validates but doesn't check existence)
            try:
                validation_service._validate_server_name_basic(server_name)
                server_dir = PathValidator.create_safe_server_directory(
                    server_name, self.base_directory
                )
            except SecurityError as e:
                raise InvalidRequestException(f"Invalid server name: {e}")

            # Use file locking for atomic directory creation
            lock_file_path = self.base_directory / f".{server_dir.name}.lock"

            # Ensure base directory exists
            self.base_directory.mkdir(exist_ok=True)

            try:
                # Use file lock for atomic operation
                with open(lock_file_path, "w") as lock_file:
                    # Acquire exclusive lock (blocks until available)
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

                    # Now atomically check and create directory
                    if server_dir.exists():
                        raise ConflictException(
                            f"Server directory for '{server_name}' already exists"
                        )

                    # Create the directory - use exist_ok=False to ensure atomicity
                    server_dir.mkdir(parents=True, exist_ok=False)

                    logger.info(f"Atomically created server directory: {server_dir}")
                    return server_dir

            finally:
                # Clean up lock file
                try:
                    if lock_file_path.exists():
                        lock_file_path.unlink()
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup lock file {lock_file_path}: {cleanup_error}"
                    )

        except (SecurityError, ConflictException, InvalidRequestException):
            # Re-raise these as they are already properly formatted
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
        """Ensure server directory exists, create if it doesn't"""
        try:
            # Validate server ID as string for directory name
            server_id_str = str(server_id)
            PathValidator.validate_safe_name(server_id_str)

            # Create safe server directory path
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
        """Generate all server configuration files"""
        try:
            # Generate server.properties using dynamic generator
            await self._generate_server_properties(server, request, server_dir)

            # Generate eula.txt
            await self._generate_eula_file(server_dir)

            # Generate startup script
            await self._generate_startup_script(server, server_dir)

            logger.info(f"Generated configuration files for server {server.name}")

        except Exception as e:
            handle_file_error("generate server files", str(server_dir), e)

    async def _generate_server_properties(
        self, server: Server, request: ServerCreateRequest, server_dir: Path
    ) -> None:
        """Generate server.properties file using dynamic generator"""
        # Use the new dynamic properties generator
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
        """Generate eula.txt file"""
        eula_content = """# By changing the setting below to TRUE you are indicating your agreement to our EULA (https://aka.ms/MinecraftEULA).
# The server will not start unless this is set to true.
eula=true"""

        eula_file = server_dir / "eula.txt"
        with open(eula_file, "w") as f:
            f.write(eula_content)

    async def _generate_startup_script(self, server: Server, server_dir: Path) -> None:
        """Generate secure startup script with proper input validation and escaping"""
        try:
            # Validate inputs to prevent command injection
            ServerSecurityValidator.validate_memory_value(server.max_memory)
            ServerSecurityValidator.validate_jar_filename("server.jar")  # Fixed jar name

            # Sanitize all values for shell usage
            safe_server_dir = ServerSecurityValidator.sanitize_for_shell(str(server_dir))
            safe_memory = str(server.max_memory)  # Already validated as int
            safe_jar = ServerSecurityValidator.sanitize_for_shell("server.jar")

            # Generate secure script with proper escaping
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

            # Make script executable
            script_file.chmod(0o755)

            logger.info(f"Generated secure startup script for server {server.id}")

        except Exception as e:
            logger.error(f"Failed to generate startup script for server {server.id}: {e}")
            raise InvalidRequestException(
                f"Failed to generate secure startup script: {e}"
            )

    async def cleanup_server_directory(self, server_dir: Path) -> None:
        """Cleanup server directory on failure"""
        try:
            if server_dir.exists():
                import shutil

                shutil.rmtree(server_dir)
                logger.info(f"Cleaned up server directory: {server_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup server directory {server_dir}: {e}")


class ServerDatabaseService:
    """Service for server database operations"""

    def create_server_record(
        self, request: ServerCreateRequest, owner: User, directory_path: str, db: Session
    ) -> Server:
        """Create server database record"""
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
        """Update server database record"""
        try:
            for field, value in request.model_dump(exclude_unset=True).items():
                setattr(server, field, value)

            db.commit()
            db.refresh(server)

            logger.info(f"Updated server record: {server.name} (ID: {server.id})")
            return server

        except Exception as e:
            db.rollback()
            handle_database_error("update", "server", e)

    def soft_delete_server(self, server: Server, db: Session) -> None:
        """Soft delete server record"""
        try:
            server.is_deleted = True
            server.status = ServerStatus.stopped  # Don't use 'deleted' status

            db.commit()

            logger.info(f"Soft deleted server: {server.name} (ID: {server.id})")

        except Exception as e:
            db.rollback()
            handle_database_error("delete", "server", e)


class ServerTemplateService:
    """Service for applying templates to servers"""

    def __init__(self, filesystem_service: ServerFileSystemService):
        self.filesystem_service = filesystem_service

    async def apply_template(self, server: Server, template_id: int, db: Session) -> None:
        """Apply template to server"""
        try:
            template = db.query(Template).filter(Template.id == template_id).first()
            if not template:
                raise InvalidRequestException(f"Template {template_id} not found")

            # Apply template files to server directory
            server_dir = Path(server.directory_path)
            template_path = Path(template.file_path)

            if template_path.exists():
                await self._extract_template_files(template_path, server_dir)
                logger.info(f"Applied template {template.name} to server {server.name}")

        except Exception as e:
            handle_file_error("apply template", str(template_path), e)

    async def _extract_template_files(
        self, template_path: Path, server_dir: Path
    ) -> None:
        """Extract template files to server directory with security validation"""
        try:
            # Use secure tar extraction
            TarExtractor.safe_extract_tar(template_path, server_dir)
        except SecurityError as e:
            raise InvalidRequestException(f"Template extraction failed: {e}")
        except Exception as e:
            raise InvalidRequestException(f"Failed to extract template: {e}")


class ServerService:
    """Main service for orchestrating server operations"""

    def __init__(self):
        self.validation_service = ServerValidationService()
        self.jar_service = ServerJarService()
        self.filesystem_service = ServerFileSystemService()
        self.database_service = ServerDatabaseService()
        self.template_service = ServerTemplateService(self.filesystem_service)

    async def _is_version_supported_db(
        self, db: Session, server_type: ServerType, version: str
    ) -> bool:
        """Check if version is supported using database (FAST - ~10ms vs ~1000ms)"""
        try:
            repo = VersionRepository(db)
            db_version = await repo.get_version_by_type_and_version(server_type, version)
            if db_version is not None and db_version.is_active:
                return True
            # Fallback to external API if not found in database
            return minecraft_version_manager.is_version_supported(server_type, version)
        except Exception:
            # Fallback to external API if database fails
            return minecraft_version_manager.is_version_supported(server_type, version)

    async def create_server(
        self, request: ServerCreateRequest, owner: User, db: Session
    ) -> ServerResponse:
        """Create a new Minecraft server with dynamic version and caching support"""
        # Validate server uniqueness
        await self.validation_service.validate_server_uniqueness(request, db)

        # Security validation to prevent command injection
        ServerSecurityValidator.validate_server_name(request.name)
        ServerSecurityValidator.validate_memory_value(request.max_memory)

        # Validate version support using database (FAST - ~10ms vs ~1000ms)
        if not await self._is_version_supported_db(
            db, request.server_type, request.minecraft_version
        ):
            raise InvalidRequestException(
                f"Version {request.minecraft_version} is not supported for {request.server_type.value}. "
                f"Minimum supported version: 1.8"
            )

        # Validate Java compatibility before creating server resources
        await self._validate_java_compatibility(request.minecraft_version)

        # Create server directory
        server_dir = await self.filesystem_service.create_server_directory(request.name)

        try:
            # Get server JAR (with caching) - FAST DATABASE VERSION
            await self.jar_service.get_server_jar(
                request.server_type, request.minecraft_version, server_dir, db
            )

            # Create database record
            server = self.database_service.create_server_record(
                request, owner, str(server_dir), db
            )

            # Generate server configuration files (with dynamic properties)
            await self.filesystem_service.generate_server_files(
                server, request, server_dir
            )

            # Apply template if provided
            if request.template_id:
                await self.template_service.apply_template(
                    server, request.template_id, db
                )

            # Attach groups if provided
            if request.attach_groups:
                group_service = GroupService()
                for group_type, group_ids in request.attach_groups.items():
                    for group_id in group_ids:
                        await group_service.attach_server_to_group(
                            group_id=group_id, server_id=server.id, db=db
                        )

            logger.info(
                f"Successfully created {request.server_type.value} server '{request.name}' "
                f"(v{request.minecraft_version}, ID: {server.id}) for user {owner.username}"
            )
            return ServerResponse.model_validate(server)

        except Exception as e:
            # Cleanup on failure
            await self.filesystem_service.cleanup_server_directory(server_dir)
            logger.error(f"Failed to create server {request.name}: {e}")
            raise

    async def get_server(self, server_id: int, db: Session) -> ServerResponse:
        """Get server by ID"""
        server = self.validation_service.validate_server_exists(server_id, db)
        return ServerResponse.model_validate(server)

    async def update_server(
        self, server_id: int, request: ServerUpdateRequest, db: Session
    ) -> ServerResponse:
        """Update server configuration"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Security validation to prevent command injection
        if request.name is not None:
            ServerSecurityValidator.validate_server_name(request.name)
        if request.max_memory is not None:
            ServerSecurityValidator.validate_memory_value(request.max_memory)

        # Check if port is being updated via server_properties
        if request.server_properties and "server-port" in request.server_properties:
            try:
                new_port = int(request.server_properties["server-port"])
                if new_port != server.port:
                    # Update the port field in the request for consistency
                    request.port = new_port
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid port value in server_properties: {request.server_properties['server-port']}"
                )

        updated_server = self.database_service.update_server_record(server, request, db)

        # Always sync server.properties after API updates to maintain consistency
        # This ensures database changes are reflected in the file
        await self._sync_server_properties_after_update(
            updated_server, request.server_properties
        )

        return ServerResponse.model_validate(updated_server)

    async def delete_server(self, server_id: int, db: Session) -> bool:
        """Soft delete server"""
        server = self.validation_service.validate_server_exists(server_id, db)
        self.database_service.soft_delete_server(server, db)
        return True

    async def start_server(self, server_id: int, db: Session) -> Dict[str, str]:
        """Start server"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Start the server using minecraft_server_manager
        await minecraft_server_manager.start_server(server, db)

        return {"message": f"Server '{server.name}' started successfully"}

    async def stop_server(self, server_id: int, db: Session) -> Dict[str, str]:
        """Stop server"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Stop the server using minecraft_server_manager
        await minecraft_server_manager.stop_server(server.id)

        return {"message": f"Server '{server.name}' stopped successfully"}

    async def restart_server(self, server_id: int, db: Session) -> Dict[str, str]:
        """Restart server with proper status verification to prevent race conditions"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Stop the server
        await minecraft_server_manager.stop_server(server.id)

        # Wait for proper shutdown with exponential backoff and timeout
        max_wait_seconds = 60  # Maximum wait time
        wait_interval = 1  # Start with 1 second
        total_waited = 0

        logger.info(f"Waiting for server {server.id} to stop properly...")

        while total_waited < max_wait_seconds:
            # Check server status
            current_status = minecraft_server_manager.get_server_status(server.id)

            if current_status == ServerStatus.stopped:
                logger.info(f"Server {server.id} stopped after {total_waited} seconds")
                break

            # Wait with exponential backoff (capped at 5 seconds)
            await asyncio.sleep(wait_interval)
            total_waited += wait_interval
            wait_interval = min(wait_interval * 1.5, 5)  # Cap at 5 seconds

            logger.debug(
                f"Server {server.id} still running, waited {total_waited}s, status: {current_status}"
            )

        # Verify server has stopped
        final_status = minecraft_server_manager.get_server_status(server.id)
        if final_status != ServerStatus.stopped:
            logger.error(
                f"Server {server.id} failed to stop within {max_wait_seconds}s, status: {final_status}"
            )
            raise RuntimeError(
                f"Server '{server.name}' failed to stop within {max_wait_seconds} seconds. "
                f"Current status: {final_status}. Cannot safely restart."
            )

        # Now safely start the server
        logger.info(f"Starting server {server.id} after confirmed stop")
        await minecraft_server_manager.start_server(server, db)

        return {"message": f"Server '{server.name}' restarted successfully"}

    def get_server_status(self, server_id: int, db: Session) -> Dict[str, Any]:
        """Get server status"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Get status from minecraft_server_manager
        status = minecraft_server_manager.get_server_status(server.id)

        return {
            "server_id": server.id,
            "server_name": server.name,
            "status": status.value if status else "unknown",
            "last_updated": server.updated_at.isoformat() if server.updated_at else None,
        }

    def list_servers(
        self,
        owner_id: Optional[int] = None,
        status: Optional[ServerStatus] = None,
        server_type: Optional[ServerType] = None,
        page: int = 1,
        size: int = 50,
        db: Session = None,
    ) -> Dict[str, Any]:
        """List servers with filtering and pagination"""
        try:
            # Use eager loading for owner relationship to avoid N+1 queries
            from sqlalchemy.orm import joinedload

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

            # Order by creation date (newest first)
            query = query.order_by(Server.created_at.desc())

            total = query.count()
            servers = query.offset((page - 1) * size).limit(size).all()

            return {
                "servers": [ServerResponse.model_validate(server) for server in servers],
                "total": total,
                "page": page,
                "size": size,
            }

        except Exception as e:
            handle_database_error("list", "servers", e)

    def get_supported_versions(self) -> Dict[str, Any]:
        """Get supported versions for all server types"""
        try:
            # This will be called from router and converted to async
            # For now, return a basic structure that can be populated by the router
            return {
                "versions": []  # Will be populated by router using async version manager
            }
        except Exception as e:
            logger.error(f"Failed to get supported versions: {e}")
            raise

    async def _sync_server_properties_after_update(
        self, server: Server, custom_properties: Optional[Dict[str, Any]] = None
    ) -> None:
        """Sync server.properties file after database update"""
        try:
            server_dir = Path(server.directory_path)
            properties_path = server_dir / "server.properties"

            if not properties_path.exists():
                logger.warning(
                    f"server.properties not found for server {server.id}, skipping sync"
                )
                return

            # Read existing properties
            properties = {}
            with open(properties_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        properties[key] = value

            # Update properties that might have changed
            properties["server-port"] = str(server.port)
            properties["max-players"] = str(server.max_players)

            # Apply custom properties if provided (from server_properties field)
            if custom_properties:
                for key, value in custom_properties.items():
                    # Convert key format (server-port vs server_port)
                    normalized_key = key.replace("_", "-")
                    properties[normalized_key] = str(value)

            # Write updated properties back
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
            # Don't fail the update if properties sync fails

    async def _validate_java_compatibility(self, minecraft_version: str) -> None:
        """Validate Java compatibility for Minecraft version"""
        try:
            # Get appropriate Java installation for Minecraft version
            java_version = await java_compatibility_service.get_java_for_minecraft(
                minecraft_version
            )

            if java_version is None:
                # Provide helpful error message with available Java installations
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
                        f"Minecraft {minecraft_version} requires Java {required_version}, "
                        f"but only Java {available_versions} are available. "
                        f"Please install Java {required_version} or configure JAVA_{required_version}_PATH in .env."
                    )

            # Validate compatibility with Minecraft version
            is_compatible, compatibility_message = (
                java_compatibility_service.validate_java_compatibility(
                    minecraft_version, java_version
                )
            )

            if not is_compatible:
                logger.warning(
                    f"Java compatibility validation failed for Minecraft {minecraft_version}: {compatibility_message}"
                )
                raise InvalidRequestException(compatibility_message)

            logger.info(
                f"Java compatibility validated for Minecraft {minecraft_version}: "
                f"Using Java {java_version.major_version} at {java_version.executable_path}"
            )

        except InvalidRequestException:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            error_message = f"Java compatibility validation failed: {e}"
            logger.error(error_message, exc_info=True)
            raise InvalidRequestException(error_message)


# Global server service instance
server_service = ServerService()
