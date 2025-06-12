import logging
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.servers.models import Server, ServerType, Template
from app.users.models import Role, User

logger = logging.getLogger(__name__)


class TemplateError(Exception):
    """Base exception for template operations"""

    pass


class TemplateNotFoundError(TemplateError):
    """Template not found error"""

    pass


class TemplateCreationError(TemplateError):
    """Error creating template"""

    pass


class TemplateAccessError(TemplateError):
    """Template access permission error"""

    pass


class TemplateService:
    """Service for managing server templates"""

    def __init__(self):
        self.templates_directory = Path("templates")
        self.templates_directory.mkdir(exist_ok=True)

    async def create_template_from_server(
        self,
        server_id: int,
        name: str,
        description: Optional[str] = None,
        is_public: bool = False,
        creator: User = None,
        db: Session = None,
    ) -> Template:
        """Create a template from an existing server"""
        try:
            # Get server from database
            server = (
                db.query(Server)
                .filter(and_(Server.id == server_id, Server.is_deleted.is_(False)))
                .first()
            )

            if not server:
                raise TemplateNotFoundError(f"Server {server_id} not found")

            # Check if server directory exists
            server_dir = Path(server.directory_path)
            if not server_dir.exists():
                raise TemplateCreationError(f"Server directory not found: {server_dir}")

            # Extract server configuration
            configuration = await self._extract_server_configuration(server, server_dir)

            # Create template record
            template = Template(
                name=name,
                description=description,
                minecraft_version=server.minecraft_version,
                server_type=server.server_type,
                configuration=configuration,
                created_by=creator.id,
                is_public=is_public,
            )

            db.add(template)
            db.flush()  # Get template ID

            # Create template files archive
            await self._create_template_files(template.id, server_dir)

            db.commit()
            db.refresh(template)

            logger.info(
                f"Successfully created template {template.id} from server {server_id}"
            )
            return template

        except Exception as e:
            if "template" in locals():
                db.rollback()

            logger.error(f"Failed to create template from server {server_id}: {e}")
            raise TemplateCreationError(f"Failed to create template: {str(e)}")

    async def create_custom_template(
        self,
        name: str,
        minecraft_version: str,
        server_type: ServerType,
        configuration: Dict[str, Any],
        description: Optional[str] = None,
        default_groups: Optional[Dict[str, List[int]]] = None,
        is_public: bool = False,
        creator: User = None,
        db: Session = None,
    ) -> Template:
        """Create a custom template with specified configuration"""
        try:
            template = Template(
                name=name,
                description=description,
                minecraft_version=minecraft_version,
                server_type=server_type,
                configuration=configuration,
                default_groups=default_groups
                or {"op_groups": [], "whitelist_groups": []},
                created_by=creator.id,
                is_public=is_public,
            )

            db.add(template)
            db.commit()
            db.refresh(template)

            logger.info(f"Successfully created custom template {template.id}")
            return template

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create custom template: {e}")
            raise TemplateCreationError(f"Failed to create template: {str(e)}")

    async def _extract_server_configuration(
        self, server: Server, server_dir: Path
    ) -> Dict[str, Any]:
        """Extract configuration from server directory"""
        try:
            configuration = {
                "server_properties": {},
                "files": [],
                "directories": [],
                "metadata": {
                    "original_server_id": server.id,
                    "original_server_name": server.name,
                    "port": server.port,
                    "max_memory": server.max_memory,
                    "max_players": server.max_players,
                },
            }

            # Extract server.properties
            properties_path = server_dir / "server.properties"
            if properties_path.exists():
                configuration["server_properties"] = await self._parse_server_properties(
                    properties_path
                )

            # List important files to include in template
            important_files = [
                "server.properties",
                "eula.txt",
                "ops.json",
                "whitelist.json",
                "banned-players.json",
                "banned-ips.json",
            ]

            for file_name in important_files:
                file_path = server_dir / file_name
                if file_path.exists():
                    configuration["files"].append(file_name)

            # List important directories
            important_dirs = ["plugins", "mods", "config", "datapacks"]
            for dir_name in important_dirs:
                dir_path = server_dir / dir_name
                if dir_path.exists() and dir_path.is_dir():
                    configuration["directories"].append(dir_name)

            return configuration

        except Exception as e:
            logger.error(f"Failed to extract server configuration: {e}")
            raise TemplateCreationError(f"Failed to extract configuration: {str(e)}")

    async def _parse_server_properties(self, properties_path: Path) -> Dict[str, str]:
        """Parse server.properties file"""
        try:
            properties = {}
            with open(properties_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        properties[key.strip()] = value.strip()
            return properties

        except Exception as e:
            logger.error(f"Failed to parse server.properties: {e}")
            return {}

    async def _create_template_files(self, template_id: int, server_dir: Path):
        """Create template files archive"""
        try:
            template_filename = f"template_{template_id}_files.tar.gz"
            template_path = self.templates_directory / template_filename

            with tarfile.open(template_path, "w:gz") as tar:
                # Add important configuration files
                important_files = [
                    "server.properties",
                    "eula.txt",
                    "ops.json",
                    "whitelist.json",
                    "banned-players.json",
                    "banned-ips.json",
                ]

                for file_name in important_files:
                    file_path = server_dir / file_name
                    if file_path.exists():
                        tar.add(file_path, arcname=file_name)

                # Add important directories
                important_dirs = ["plugins", "mods", "config", "datapacks"]
                for dir_name in important_dirs:
                    dir_path = server_dir / dir_name
                    if dir_path.exists() and dir_path.is_dir():
                        tar.add(dir_path, arcname=dir_name)

            logger.info(f"Created template files archive: {template_filename}")

        except Exception as e:
            logger.error(f"Failed to create template files: {e}")
            raise TemplateCreationError(f"Failed to create template files: {str(e)}")

    async def apply_template_to_server(
        self, template_id: int, server_dir: Path, db: Session
    ) -> bool:
        """Apply template files to a server directory"""
        try:
            template = db.query(Template).filter(Template.id == template_id).first()
            if not template:
                raise TemplateNotFoundError(f"Template {template_id} not found")

            # Check if template files exist
            template_filename = f"template_{template_id}_files.tar.gz"
            template_path = self.templates_directory / template_filename

            if template_path.exists():
                # Extract template files to server directory
                with tarfile.open(template_path, "r:gz") as tar:
                    tar.extractall(path=server_dir)

                logger.info(f"Applied template {template_id} files to {server_dir}")

            # Apply configuration from template
            configuration = template.get_configuration()
            if "server_properties" in configuration:
                await self._apply_server_properties(
                    server_dir, configuration["server_properties"]
                )

            return True

        except Exception as e:
            logger.error(f"Failed to apply template {template_id}: {e}")
            return False

    async def _apply_server_properties(
        self, server_dir: Path, properties: Dict[str, str]
    ):
        """Apply server.properties from template"""
        try:
            properties_path = server_dir / "server.properties"

            # Read existing properties if file exists
            existing_properties = {}
            if properties_path.exists():
                existing_properties = await self._parse_server_properties(properties_path)

            # Merge with template properties
            existing_properties.update(properties)

            # Write updated properties
            with open(properties_path, "w") as f:
                f.write("# Minecraft server properties\n")
                f.write("# Applied from template\n\n")
                for key, value in sorted(existing_properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(f"Applied server.properties from template to {properties_path}")

        except Exception as e:
            logger.error(f"Failed to apply server.properties: {e}")

    def get_template(
        self, template_id: int, user: User, db: Session
    ) -> Optional[Template]:
        """Get template by ID with access control"""
        try:
            template = db.query(Template).filter(Template.id == template_id).first()

            if not template:
                return None

            # Check access permissions
            if not self._can_access_template(template, user):
                raise TemplateAccessError("Access denied to template")

            return template

        except Exception as e:
            logger.error(f"Failed to get template {template_id}: {e}")
            raise TemplateError(f"Failed to get template: {str(e)}")

    def list_templates(
        self,
        user: User,
        minecraft_version: Optional[str] = None,
        server_type: Optional[ServerType] = None,
        is_public: Optional[bool] = None,
        page: int = 1,
        size: int = 50,
        db: Session = None,
    ) -> Dict[str, Any]:
        """List templates with filtering and pagination"""
        try:
            query = db.query(Template)

            # Apply access control
            if user.role != Role.admin:
                # Non-admins can only see public templates or their own
                query = query.filter(
                    (Template.is_public) | (Template.created_by == user.id)
                )

            # Apply filters
            if minecraft_version:
                query = query.filter(Template.minecraft_version == minecraft_version)

            if server_type:
                query = query.filter(Template.server_type == server_type)

            if is_public is not None:
                query = query.filter(Template.is_public == is_public)

            # Order by creation date (newest first)
            query = query.order_by(Template.created_at.desc())

            total = query.count()
            templates = query.offset((page - 1) * size).limit(size).all()

            return {
                "templates": templates,
                "total": total,
                "page": page,
                "size": size,
            }

        except Exception as e:
            logger.error(f"Failed to list templates: {e}")
            raise TemplateError(f"Failed to list templates: {str(e)}")

    def update_template(
        self,
        template_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        configuration: Optional[Dict[str, Any]] = None,
        default_groups: Optional[Dict[str, List[int]]] = None,
        is_public: Optional[bool] = None,
        user: User = None,
        db: Session = None,
    ) -> Optional[Template]:
        """Update template"""
        try:
            template = db.query(Template).filter(Template.id == template_id).first()

            if not template:
                return None

            # Check permissions
            if not self._can_modify_template(template, user):
                raise TemplateAccessError("Access denied to modify template")

            # Update fields
            if name is not None:
                template.name = name
            if description is not None:
                template.description = description
            if configuration is not None:
                template.set_configuration(configuration)
            if default_groups is not None:
                template.set_default_groups(default_groups)
            if is_public is not None:
                template.is_public = is_public

            db.commit()
            db.refresh(template)

            logger.info(f"Updated template {template_id}")
            return template

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update template {template_id}: {e}")
            raise TemplateError(f"Failed to update template: {str(e)}")

    def delete_template(self, template_id: int, user: User, db: Session) -> bool:
        """Delete template"""
        try:
            template = db.query(Template).filter(Template.id == template_id).first()

            if not template:
                return False

            # Check permissions
            if not self._can_modify_template(template, user):
                raise TemplateAccessError("Access denied to delete template")

            # Check if template is in use
            servers_using_template = (
                db.query(Server)
                .filter(Server.template_id == template_id, Server.is_deleted.is_(False))
                .count()
            )

            if servers_using_template > 0:
                raise TemplateError(
                    f"Cannot delete template: {servers_using_template} servers are using it"
                )

            # Delete template files if they exist
            template_filename = f"template_{template_id}_files.tar.gz"
            template_path = self.templates_directory / template_filename
            if template_path.exists():
                template_path.unlink()
                logger.info(f"Deleted template files: {template_filename}")

            # Delete database record
            db.delete(template)
            db.commit()

            logger.info(f"Successfully deleted template {template_id}")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete template {template_id}: {e}")
            raise TemplateError(f"Failed to delete template: {str(e)}")

    def _can_access_template(self, template: Template, user: User) -> bool:
        """Check if user can access template"""
        # Admins can access all templates
        if user.role == Role.admin:
            return True

        # Users can access public templates or their own
        return template.is_public or template.created_by == user.id

    def _can_modify_template(self, template: Template, user: User) -> bool:
        """Check if user can modify template"""
        # Admins can modify all templates
        if user.role == Role.admin:
            return True

        # Users can only modify their own templates
        return template.created_by == user.id

    async def clone_template(
        self,
        original_template_id: int,
        name: str,
        description: Optional[str] = None,
        is_public: bool = False,
        user: User = None,
        db: Session = None,
    ) -> Template:
        """Clone an existing template"""
        try:
            # Get the original template
            original_template = (
                db.query(Template).filter(Template.id == original_template_id).first()
            )

            if not original_template:
                raise TemplateNotFoundError(
                    f"Original template {original_template_id} not found"
                )

            # Check access permissions
            if not self._can_access_template(original_template, user):
                raise TemplateAccessError("Access denied to clone template")

            # Check if name already exists for this user
            existing_template = (
                db.query(Template)
                .filter(Template.created_by == user.id, Template.name == name)
                .first()
            )

            if existing_template:
                raise TemplateError("Template with this name already exists")

            # Create new template with copied data
            new_template = Template(
                name=name,
                description=description or f"Clone of {original_template.name}",
                minecraft_version=original_template.minecraft_version,
                server_type=original_template.server_type,
                configuration=original_template.configuration,
                default_groups=original_template.default_groups,
                is_public=is_public,
                created_by=user.id,
            )

            db.add(new_template)
            db.commit()
            db.refresh(new_template)

            # Copy template files if they exist
            original_filename = f"template_{original_template_id}_files.tar.gz"
            original_path = self.templates_directory / original_filename

            if original_path.exists():
                new_filename = f"template_{new_template.id}_files.tar.gz"
                new_path = self.templates_directory / new_filename

                # Copy the template files
                shutil.copy2(original_path, new_path)
                logger.info(
                    f"Copied template files from {original_filename} to {new_filename}"
                )

            logger.info(
                f"Successfully cloned template {original_template_id} as {new_template.id}"
            )
            return new_template

        except Exception as e:
            if "new_template" in locals():
                db.rollback()
            logger.error(f"Failed to clone template {original_template_id}: {e}")
            raise TemplateError(f"Failed to clone template: {str(e)}")

    def get_template_statistics(self, user: User, db: Session) -> Dict[str, Any]:
        """Get template usage statistics"""
        try:
            # Base query with access control
            query = db.query(Template)
            if user.role != Role.admin:
                query = query.filter(
                    (Template.is_public) | (Template.created_by == user.id)
                )

            total_templates = query.count()
            public_templates = query.filter(Template.is_public).count()
            user_templates = query.filter(Template.created_by == user.id).count()

            # Get templates by server type
            # Optimize: Use a single GROUP BY query instead of multiple individual counts
            from sqlalchemy import func

            # Apply the same access control filter for server type statistics
            stats_query = db.query(Template)
            if user.role != Role.admin:
                stats_query = stats_query.filter(
                    (Template.is_public) | (Template.created_by == user.id)
                )

            server_type_results = (
                stats_query.with_entities(Template.server_type, func.count(Template.id))
                .group_by(Template.server_type)
                .all()
            )

            # Initialize all server types with 0, then populate with actual counts
            server_type_stats = {server_type.value: 0 for server_type in ServerType}
            for server_type, count in server_type_results:
                server_type_stats[server_type.value] = count

            return {
                "total_templates": total_templates,
                "public_templates": public_templates,
                "user_templates": user_templates,
                "server_type_distribution": server_type_stats,
            }

        except Exception as e:
            logger.error(f"Failed to get template statistics: {e}")
            raise TemplateError(f"Failed to get template statistics: {str(e)}")


# Global template service instance
template_service = TemplateService()
