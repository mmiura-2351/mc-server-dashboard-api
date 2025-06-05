import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.servers.models import (
    Server,
    ServerConfiguration,
    ServerStatus,
    ServerType,
    Template,
)
from app.servers.schemas import ServerCreateRequest, ServerResponse, ServerUpdateRequest
from app.services.group_service import GroupService
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import User

logger = logging.getLogger(__name__)


class ServerCreationError(Exception):
    """Base exception for server creation errors"""

    pass


class ServerExistsError(ServerCreationError):
    """Server with same name or port already exists"""

    pass


class DownloadError(ServerCreationError):
    """Error downloading server JAR file"""

    pass


class ConfigurationError(ServerCreationError):
    """Error in server configuration"""

    pass


class ServerService:
    """Service for managing Minecraft servers with type-specific handling"""

    def __init__(self):
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)

        # Minecraft version and download URLs
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

    async def create_server(
        self, request: ServerCreateRequest, owner: User, db: Session
    ) -> ServerResponse:
        """Create a new Minecraft server with type-specific configuration"""
        try:
            # Validate server name and port uniqueness
            await self._validate_server_uniqueness(request, db)

            # Create server directory
            server_dir = await self._create_server_directory(request.name)

            # Download and setup server JAR
            jar_path = await self._download_server_jar(
                request.server_type, request.minecraft_version, server_dir
            )

            # Create database record
            server = await self._create_server_record(request, owner, str(server_dir), db)

            # Generate server configuration files
            await self._generate_server_files(server, request, server_dir)

            # Apply template if specified
            if request.template_id:
                await self._apply_template(server, request.template_id, db)

            # Attach groups if specified
            if request.attach_groups:
                await self._attach_groups(server, request.attach_groups, owner, db)

            # Commit all database changes
            db.commit()
            db.refresh(server)

            logger.info(f"Successfully created server {server.name} (ID: {server.id})")
            return ServerResponse.from_orm(server)

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create server {request.name}: {e}")

            # Cleanup on failure
            if "server_dir" in locals():
                await self._cleanup_server_directory(server_dir)

            raise ServerCreationError(f"Failed to create server: {str(e)}")

    async def _validate_server_uniqueness(
        self, request: ServerCreateRequest, db: Session
    ):
        """Validate that server name and port are unique"""
        # Check name uniqueness
        existing_name = (
            db.query(Server)
            .filter(and_(Server.name == request.name, not Server.is_deleted))
            .first()
        )

        if existing_name:
            raise ServerExistsError(f"Server with name '{request.name}' already exists")

        # Check port uniqueness
        existing_port = (
            db.query(Server)
            .filter(and_(Server.port == request.port, not Server.is_deleted))
            .first()
        )

        if existing_port:
            raise ServerExistsError(f"Server with port {request.port} already exists")

    async def _create_server_directory(self, server_name: str) -> Path:
        """Create server directory structure"""
        # Use sanitized server name for directory
        safe_name = "".join(
            c for c in server_name if c.isalnum() or c in (" ", "-", "_")
        ).rstrip()
        safe_name = safe_name.replace(" ", "_")

        server_dir = self.base_directory / safe_name
        counter = 1
        original_dir = server_dir

        # Handle directory name conflicts
        while server_dir.exists():
            server_dir = Path(f"{original_dir}_{counter}")
            counter += 1

        server_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created server directory: {server_dir}")

        return server_dir

    async def _download_server_jar(
        self, server_type: ServerType, version: str, server_dir: Path
    ) -> Path:
        """Download the appropriate server JAR file"""
        try:
            if server_type not in self.server_versions:
                raise DownloadError(f"Unsupported server type: {server_type.value}")

            if version not in self.server_versions[server_type]:
                raise DownloadError(
                    f"Unsupported version {version} for {server_type.value}"
                )

            download_url = self.server_versions[server_type][version]

            # Determine JAR filename based on server type
            if server_type == ServerType.forge:
                jar_filename = f"forge-{version}-installer.jar"
            else:
                jar_filename = f"server-{version}.jar"

            jar_path = server_dir / jar_filename

            logger.info(f"Downloading {server_type.value} {version} from {download_url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status != 200:
                        raise DownloadError(
                            f"Failed to download JAR: HTTP {response.status}"
                        )

                    with open(jar_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            # Special handling for Forge - run installer
            if server_type == ServerType.forge:
                await self._install_forge_server(jar_path, server_dir, version)

            logger.info(f"Successfully downloaded server JAR to {jar_path}")
            return jar_path

        except Exception as e:
            logger.error(f"Failed to download server JAR: {e}")
            raise DownloadError(f"Failed to download server JAR: {str(e)}")

    async def _install_forge_server(
        self, installer_path: Path, server_dir: Path, version: str
    ):
        """Install Forge server using the installer JAR"""
        try:
            # Run forge installer
            process = await asyncio.create_subprocess_exec(
                "java",
                "-jar",
                str(installer_path),
                "--installServer",
                cwd=str(server_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"Forge installer failed: {stderr.decode()}")
                raise DownloadError("Forge installation failed")

            # Find the actual forge server JAR
            forge_jar = None
            for file in server_dir.glob(f"forge-{version}-*.jar"):
                if "installer" not in file.name:
                    forge_jar = file
                    break

            if not forge_jar:
                raise DownloadError("Forge server JAR not found after installation")

            # Rename to standard name for consistency
            standard_jar = server_dir / f"server-{version}.jar"
            forge_jar.rename(standard_jar)

            # Clean up installer
            installer_path.unlink()

            logger.info(f"Successfully installed Forge server: {standard_jar}")

        except Exception as e:
            logger.error(f"Failed to install Forge server: {e}")
            raise DownloadError(f"Forge installation failed: {str(e)}")

    async def _create_server_record(
        self, request: ServerCreateRequest, owner: User, directory_path: str, db: Session
    ) -> Server:
        """Create server database record"""
        try:
            server = Server(
                name=request.name,
                description=request.description,
                minecraft_version=request.minecraft_version,
                server_type=request.server_type,
                directory_path=directory_path,
                port=request.port,
                max_memory=request.max_memory,
                max_players=request.max_players,
                owner_id=owner.id,
                template_id=request.template_id,
                status=ServerStatus.stopped,
            )

            db.add(server)
            db.flush()  # Get server ID without committing

            return server

        except IntegrityError as e:
            logger.error(f"Database integrity error creating server: {e}")
            raise ServerCreationError("Server creation failed due to data conflict")

    async def _generate_server_files(
        self, server: Server, request: ServerCreateRequest, server_dir: Path
    ):
        """Generate server configuration files"""
        # Create eula.txt
        await self._create_eula_file(server_dir)

        # Generate server.properties
        await self._generate_server_properties(server, request, server_dir)

        # Create additional directories based on server type
        await self._create_server_type_directories(server.server_type, server_dir)

    async def _create_eula_file(self, server_dir: Path):
        """Create eula.txt file with accepted EULA"""
        eula_content = """# Minecraft End User License Agreement
# https://account.mojang.com/documents/minecraft_eula
# Automatically accepted for server creation
eula=true
"""
        eula_path = server_dir / "eula.txt"
        with open(eula_path, "w") as f:
            f.write(eula_content)

        logger.info(f"Created eula.txt at {eula_path}")

    async def _generate_server_properties(
        self, server: Server, request: ServerCreateRequest, server_dir: Path
    ):
        """Generate server.properties file with type-specific settings"""
        # Base properties common to all server types
        properties = {
            "server-port": str(server.port),
            "max-players": str(server.max_players),
            "level-name": "world",
            "gamemode": "survival",
            "difficulty": "normal",
            "pvp": "true",
            "online-mode": "true",
            "white-list": "false",
            "enable-command-block": "false",
            "spawn-protection": "16",
            "op-permission-level": "4",
            "allow-flight": "false",
            "view-distance": "10",
            "simulation-distance": "10",
            "motd": f"A Minecraft Server - {server.name}",
        }

        # Server type specific properties
        if server.server_type == ServerType.paper:
            # Paper-specific optimizations
            properties.update(
                {
                    "use-native-transport": "true",
                    "enable-jmx-monitoring": "false",
                    "enable-status": "true",
                }
            )

        elif server.server_type == ServerType.forge:
            # Forge-specific properties
            properties.update(
                {
                    "allow-flight": "true",  # Often needed for modded servers
                    "max-tick-time": "60000",  # Prevent timeout with heavy mods
                }
            )

        # Apply custom properties from request
        if request.server_properties:
            for key, value in request.server_properties.items():
                # Convert underscores to hyphens for property names
                prop_key = key.replace("_", "-")
                properties[prop_key] = str(value)

        # Write properties file
        properties_path = server_dir / "server.properties"
        with open(properties_path, "w") as f:
            f.write("# Minecraft server properties\n")
            f.write(f"# Generated for {server.name}\n")
            f.write(f"# Server Type: {server.server_type.value}\n")
            f.write(f"# Version: {server.minecraft_version}\n\n")

            for key, value in sorted(properties.items()):
                f.write(f"{key}={value}\n")

        logger.info(f"Generated server.properties at {properties_path}")

    async def _create_server_type_directories(
        self, server_type: ServerType, server_dir: Path
    ):
        """Create directories specific to server type"""
        if server_type == ServerType.paper:
            # Paper plugin directory
            (server_dir / "plugins").mkdir(exist_ok=True)

        elif server_type == ServerType.forge:
            # Forge mod directory
            (server_dir / "mods").mkdir(exist_ok=True)

        # Common directories for all types
        (server_dir / "logs").mkdir(exist_ok=True)
        (server_dir / "world").mkdir(exist_ok=True)

    async def _apply_template(self, server: Server, template_id: int, db: Session):
        """Apply template configuration to server"""
        template = db.query(Template).filter(Template.id == template_id).first()

        if not template:
            logger.warning(f"Template {template_id} not found, skipping application")
            return

        # Apply template configuration
        template_config = template.get_configuration()

        if "server_properties" in template_config:
            for key, value in template_config["server_properties"].items():
                config = ServerConfiguration(
                    server_id=server.id,
                    configuration_key=key,
                    configuration_value=str(value),
                )
                db.add(config)

        logger.info(f"Applied template {template.name} to server {server.name}")

    async def _attach_groups(
        self,
        server: Server,
        attach_groups: Dict[str, List[int]],
        owner: User,
        db: Session,
    ):
        """Attach groups to the newly created server"""
        try:
            group_service = GroupService(db)
            for group_type, group_ids in attach_groups.items():
                for group_id in group_ids:
                    if group_type in ["op_groups", "whitelist_groups"]:
                        group_service.attach_group_to_server(owner, server.id, group_id)

            logger.info(f"Attached groups to server {server.name}: {attach_groups}")

        except Exception as e:
            logger.error(f"Failed to attach groups to server {server.name}: {e}")
            # Don't fail server creation if group attachment fails

    async def _cleanup_server_directory(self, server_dir: Path):
        """Clean up server directory on creation failure"""
        try:
            if server_dir.exists():
                import shutil

                shutil.rmtree(server_dir)
                logger.info(f"Cleaned up server directory: {server_dir}")
        except Exception as e:
            logger.error(f"Failed to cleanup server directory {server_dir}: {e}")

    async def get_server(self, server_id: int, db: Session) -> Optional[ServerResponse]:
        """Get server by ID with runtime information"""
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, not Server.is_deleted))
            .first()
        )

        if not server:
            return None

        # Get process information from MinecraftServerManager
        process_info = minecraft_server_manager.get_server_info(server_id)

        response = ServerResponse.from_orm(server)
        response.process_info = process_info

        return response

    async def list_servers(
        self,
        owner_id: Optional[int] = None,
        page: int = 1,
        size: int = 50,
        db: Session = None,
    ) -> Dict[str, Any]:
        """List servers with pagination"""
        query = db.query(Server).filter(not Server.is_deleted)

        if owner_id:
            query = query.filter(Server.owner_id == owner_id)

        total = query.count()
        servers = query.offset((page - 1) * size).limit(size).all()

        # Enrich with process information
        server_responses = []
        for server in servers:
            response = ServerResponse.from_orm(server)
            response.process_info = minecraft_server_manager.get_server_info(server.id)
            server_responses.append(response)

        return {"servers": server_responses, "total": total, "page": page, "size": size}

    async def update_server(
        self, server_id: int, request: ServerUpdateRequest, db: Session
    ) -> Optional[ServerResponse]:
        """Update server configuration"""
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, not Server.is_deleted))
            .first()
        )

        if not server:
            return None

        # Update fields
        if request.name is not None:
            server.name = request.name
        if request.description is not None:
            server.description = request.description
        if request.max_memory is not None:
            server.max_memory = request.max_memory
        if request.max_players is not None:
            server.max_players = request.max_players

        # Update server properties if provided
        if request.server_properties:
            for key, value in request.server_properties.items():
                config = (
                    db.query(ServerConfiguration)
                    .filter(
                        and_(
                            ServerConfiguration.server_id == server_id,
                            ServerConfiguration.configuration_key == key,
                        )
                    )
                    .first()
                )

                if config:
                    config.configuration_value = str(value)
                else:
                    new_config = ServerConfiguration(
                        server_id=server_id,
                        configuration_key=key,
                        configuration_value=str(value),
                    )
                    db.add(new_config)

        db.commit()
        db.refresh(server)

        logger.info(f"Updated server {server.name} (ID: {server_id})")
        return ServerResponse.from_orm(server)

    async def delete_server(self, server_id: int, db: Session) -> bool:
        """Soft delete server"""
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, not Server.is_deleted))
            .first()
        )

        if not server:
            return False

        # Stop server if running
        if minecraft_server_manager.get_server_status(server_id) != ServerStatus.stopped:
            await minecraft_server_manager.stop_server(server_id, force=True)

        # Soft delete
        server.is_deleted = True
        db.commit()

        logger.info(f"Deleted server {server.name} (ID: {server_id})")
        return True

    def get_supported_versions(self) -> Dict[str, Any]:
        """Get list of supported Minecraft versions by server type"""
        versions = []
        for server_type, type_versions in self.server_versions.items():
            for version in type_versions.keys():
                versions.append(
                    {
                        "version": version,
                        "server_type": server_type.value,
                        "download_url": type_versions[version],
                        "is_supported": True,
                    }
                )

        return {"versions": versions}


# Global service instance
server_service = ServerService()
