import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp
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
from app.services.minecraft_server import minecraft_server_manager
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
            .filter(and_(Server.name == request.name, not Server.is_deleted))
            .first()
        )
        if existing_name:
            raise ConflictException(f"Server with name '{request.name}' already exists")

        # Check for existing server with same port
        existing_port = (
            db.query(Server)
            .filter(and_(Server.port == request.port, not Server.is_deleted))
            .first()
        )
        if existing_port:
            raise ConflictException(f"Server with port {request.port} already exists")

    def validate_server_exists(self, server_id: int, db: Session) -> Server:
        """Validate server exists and return it"""
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, not Server.is_deleted))
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
    """Service for handling server JAR downloads and management"""

    def __init__(self):
        self.server_versions = {
            ServerType.vanilla: {
                "1.20.1": "https://piston-data.mojang.com/v1/objects/84194a2f286ef7c14ed7ce0090dba59902951553/server.jar",
                "1.19.4": "https://piston-data.mojang.com/v1/objects/8f3112a1049751cc472ec13e397eade5336ca7ae/server.jar",
                "1.18.2": "https://piston-data.mojang.com/v1/objects/c8f83c5655308435b3dcf03c06d9fe8740a77469/server.jar",
                "1.17.1": "https://piston-data.mojang.com/v1/objects/a16d67e5807f57fc4e550299cf20226194497dc2/server.jar",
            },
            ServerType.paper: {
                "1.20.1": "https://api.papermc.io/v2/projects/paper/versions/1.20.1/builds/196/downloads/paper-1.20.1-196.jar",
                "1.19.4": "https://api.papermc.io/v2/projects/paper/versions/1.19.4/builds/550/downloads/paper-1.19.4-550.jar",
                "1.18.2": "https://api.papermc.io/v2/projects/paper/versions/1.18.2/builds/388/downloads/paper-1.18.2-388.jar",
                "1.17.1": "https://api.papermc.io/v2/projects/paper/versions/1.17.1/builds/411/downloads/paper-1.17.1-411.jar",
            },
            ServerType.forge: {
                "1.20.1": "https://maven.minecraftforge.net/net/minecraftforge/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0-installer.jar",
                "1.19.4": "https://maven.minecraftforge.net/net/minecraftforge/forge/1.19.4-45.2.0/forge-1.19.4-45.2.0-installer.jar",
                "1.18.2": "https://maven.minecraftforge.net/net/minecraftforge/forge/1.18.2-40.2.0/forge-1.18.2-40.2.0-installer.jar",
                "1.17.1": "https://maven.minecraftforge.net/net/minecraftforge/forge/1.17.1-37.1.1/forge-1.17.1-37.1.1-installer.jar",
            },
        }

    async def download_server_jar(
        self, server_type: ServerType, minecraft_version: str, server_dir: Path
    ) -> Path:
        """Download server JAR file"""
        try:
            download_url = self._get_download_url(server_type, minecraft_version)
            jar_path = server_dir / "server.jar"

            await self._download_file(download_url, jar_path)

            logger.info(
                f"Downloaded {server_type.value} {minecraft_version} to {jar_path}"
            )
            return jar_path

        except Exception as e:
            handle_file_error("download server jar", str(server_dir), e)

    def _get_download_url(self, server_type: ServerType, minecraft_version: str) -> str:
        """Get download URL for server type and version"""
        if server_type not in self.server_versions:
            raise InvalidRequestException(f"Unsupported server type: {server_type.value}")

        version_urls = self.server_versions[server_type]
        if minecraft_version not in version_urls:
            raise InvalidRequestException(
                f"Unsupported version {minecraft_version} for {server_type.value}"
            )

        return version_urls[minecraft_version]

    async def _download_file(self, url: str, file_path: Path) -> None:
        """Download file from URL to local path"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()

                with open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)


class ServerFileSystemService:
    """Service for server file system operations"""

    def __init__(self):
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)

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
            # Generate server.properties
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
        """Generate server.properties file"""
        properties = {
            "server-port": str(server.port),
            "server-name": server.name,
            "motd": request.description or f"A Minecraft Server - {server.name}",
            "max-players": str(request.max_players or 20),
            "difficulty": request.difficulty or "normal",
            "gamemode": request.gamemode or "survival",
            "level-name": "world",
            "spawn-protection": "16",
            "view-distance": "10",
            "online-mode": "true",
            "enable-command-block": "false",
            "allow-nether": "true",
            "allow-flight": "false",
            "resource-pack": "",
            "pvp": "true",
            "hardcore": "false",
            "white-list": "false",
            "enforce-whitelist": "false",
        }

        # Add type-specific properties
        if server.server_type == ServerType.paper:
            properties.update(
                {
                    "paper-settings.async-chunks": "true",
                    "paper-settings.optimize-explosions": "true",
                }
            )

        properties_content = "\n".join(
            [f"{key}={value}" for key, value in properties.items()]
        )

        properties_file = server_dir / "server.properties"
        with open(properties_file, "w") as f:
            f.write(properties_content)

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
java -Xmx{server.ram_mb}M -Xms{server.ram_mb}M -jar server.jar nogui"""

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
                ram_mb=request.ram_mb,
                max_players=request.max_players,
                difficulty=request.difficulty,
                gamemode=request.gamemode,
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
            for field, value in request.dict(exclude_unset=True).items():
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
            server.status = ServerStatus.deleted

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
        """Create a new Minecraft server with type-specific configuration"""
        # Validate server uniqueness
        await self.validation_service.validate_server_uniqueness(request, db)

        # Create server directory
        server_dir = await self.filesystem_service.create_server_directory(request.name)

        try:
            # Download server JAR
            await self.jar_service.download_server_jar(
                request.server_type, request.minecraft_version, server_dir
            )

            # Create database record
            server = self.database_service.create_server_record(
                request, owner, str(server_dir), db
            )

            # Generate server configuration files
            await self.filesystem_service.generate_server_files(
                server, request, server_dir
            )

            # Apply template if provided
            if request.template_id:
                await self.template_service.apply_template(
                    server, request.template_id, db
                )

            # Attach groups if provided
            if hasattr(request, "group_ids") and request.group_ids:
                group_service = GroupService(db)
                for group_id in request.group_ids:
                    await group_service.attach_server_to_group(
                        group_id=group_id, server_id=server.id, db=db
                    )

            logger.info(
                f"Successfully created {request.server_type.value} server '{request.name}' "
                f"(ID: {server.id}) for user {owner.username}"
            )
            return ServerResponse.from_orm(server)

        except Exception as e:
            # Cleanup on failure
            await self.filesystem_service.cleanup_server_directory(server_dir)
            logger.error(f"Failed to create server {request.name}: {e}")
            raise

    async def get_server(self, server_id: int, db: Session) -> ServerResponse:
        """Get server by ID"""
        server = self.validation_service.validate_server_exists(server_id, db)
        return ServerResponse.from_orm(server)

    async def update_server(
        self, server_id: int, request: ServerUpdateRequest, db: Session
    ) -> ServerResponse:
        """Update server configuration"""
        server = self.validation_service.validate_server_exists(server_id, db)
        updated_server = self.database_service.update_server_record(server, request, db)
        return ServerResponse.from_orm(updated_server)

    async def delete_server(self, server_id: int, db: Session) -> Dict[str, str]:
        """Soft delete server"""
        server = self.validation_service.validate_server_exists(server_id, db)
        self.database_service.soft_delete_server(server, db)

        return {"message": f"Server '{server.name}' deleted successfully"}

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
            query = db.query(Server).filter(not Server.is_deleted)

            if owner_id:
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
                "servers": [ServerResponse.from_orm(server) for server in servers],
                "total": total,
                "page": page,
                "size": size,
            }

        except Exception as e:
            handle_database_error("list", "servers", e)


# Global server service instance
server_service = ServerService()
