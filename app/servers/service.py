import asyncio
import logging
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
from app.servers.models import (
    Server,
    ServerStatus,
    ServerType,
    Template,
)
from app.servers.schemas import ServerCreateRequest, ServerResponse, ServerUpdateRequest
from app.services.group_service import GroupService
from app.services.jar_cache_manager import jar_cache_manager
from app.services.minecraft_server import minecraft_server_manager
from app.services.server_properties_generator import server_properties_generator
from app.services.version_manager import minecraft_version_manager
from app.users.models import User

logger = logging.getLogger(__name__)


class ServerValidationService:
    """Service for validating server operations"""

    def __init__(self):
        self.base_directory = Path("servers")

    async def validate_server_uniqueness(
        self, request: ServerCreateRequest, db: Session
    ) -> None:
        """Validate server name and port uniqueness"""
        # Check for existing server with same name
        existing_name = (
            db.query(Server)
            .filter(and_(Server.name == request.name, Server.is_deleted.is_(False)))
            .first()
        )
        if existing_name:
            raise ConflictException(f"Server with name '{request.name}' already exists")

        # Check for existing server with same port that is currently running
        existing_port = (
            db.query(Server)
            .filter(
                and_(
                    Server.port == request.port,
                    Server.is_deleted.is_(False),
                    Server.status.in_([ServerStatus.running, ServerStatus.starting]),
                )
            )
            .first()
        )
        if existing_port:
            raise ConflictException(f"Server with port {request.port} is already running")

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
        server_dir = self.base_directory / server_name
        if server_dir.exists():
            raise ConflictException(f"Server directory '{server_name}' already exists")
        return server_dir


class ServerJarService:
    """Service for handling server JAR downloads and management with caching"""

    def __init__(self):
        self.version_manager = minecraft_version_manager
        self.cache_manager = jar_cache_manager

    async def get_server_jar(
        self, server_type: ServerType, minecraft_version: str, server_dir: Path
    ) -> Path:
        """Get server JAR file (from cache or download)"""
        try:
            # Validate version support
            if not self.version_manager.is_version_supported(
                server_type, minecraft_version
            ):
                raise InvalidRequestException(
                    f"Version {minecraft_version} is not supported for {server_type.value} "
                    f"(minimum supported version: 1.8)"
                )

            # Get download URL
            download_url = await self.version_manager.get_download_url(
                server_type, minecraft_version
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
        """Create server directory"""
        try:
            server_dir = self.base_directory / server_name
            server_dir.mkdir(parents=True, exist_ok=False)

            logger.info(f"Created server directory: {server_dir}")
            return server_dir

        except FileExistsError:
            raise ConflictException(f"Server directory '{server_name}' already exists")
        except Exception as e:
            handle_file_error(
                "create directory", str(self.base_directory / server_name), e
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
        """Generate startup script"""
        script_content = f"""#!/bin/bash
cd "{server_dir}"
java -Xmx{server.max_memory}M -Xms{server.max_memory}M -jar server.jar nogui"""

        script_file = server_dir / "start.sh"
        with open(script_file, "w") as f:
            f.write(script_content)

        # Make script executable
        script_file.chmod(0o755)

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
        """Extract template files to server directory"""
        import tarfile

        with tarfile.open(template_path, "r:gz") as tar:
            tar.extractall(path=server_dir)


class ServerService:
    """Main service for orchestrating server operations"""

    def __init__(self):
        self.validation_service = ServerValidationService()
        self.jar_service = ServerJarService()
        self.filesystem_service = ServerFileSystemService()
        self.database_service = ServerDatabaseService()
        self.template_service = ServerTemplateService(self.filesystem_service)

    async def create_server(
        self, request: ServerCreateRequest, owner: User, db: Session
    ) -> ServerResponse:
        """Create a new Minecraft server with dynamic version and caching support"""
        # Validate server uniqueness
        await self.validation_service.validate_server_uniqueness(request, db)

        # Validate version support using dynamic version manager
        if not minecraft_version_manager.is_version_supported(
            request.server_type, request.minecraft_version
        ):
            raise InvalidRequestException(
                f"Version {request.minecraft_version} is not supported for {request.server_type.value}. "
                f"Minimum supported version: 1.8"
            )

        # Create server directory
        server_dir = await self.filesystem_service.create_server_directory(request.name)

        try:
            # Get server JAR (with caching)
            await self.jar_service.get_server_jar(
                request.server_type, request.minecraft_version, server_dir
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
        updated_server = self.database_service.update_server_record(server, request, db)
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
        await minecraft_server_manager.start_server(server)

        return {"message": f"Server '{server.name}' started successfully"}

    async def stop_server(self, server_id: int, db: Session) -> Dict[str, str]:
        """Stop server"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Stop the server using minecraft_server_manager
        await minecraft_server_manager.stop_server(server.id)

        return {"message": f"Server '{server.name}' stopped successfully"}

    async def restart_server(self, server_id: int, db: Session) -> Dict[str, str]:
        """Restart server"""
        server = self.validation_service.validate_server_exists(server_id, db)

        # Stop the server
        await minecraft_server_manager.stop_server(server.id)

        # Wait for server to stop
        await asyncio.sleep(5)

        # Start the server
        await minecraft_server_manager.start_server(server)

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
            query = db.query(Server).filter(Server.is_deleted.is_(False))

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


# Global server service instance
server_service = ServerService()
