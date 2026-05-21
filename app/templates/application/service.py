"""Template service (application layer).

Orchestrates template creation from servers, custom templates, listing,
update, delete, clone, and statistics. Depends only on the templates
domain Ports and the minimal cross-domain `ServerReadPort`. Must not
import from `adapters/`, `api/`, FastAPI, or SQLAlchemy.

Permission helpers (`_can_access`, `_can_modify`) are pure functions
over `TemplateEntity` + viewer pair; they live alongside the use cases
intentionally — the Repository exposes facts, the application layer
applies the visibility rule.
"""

import logging
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.servers.domain.entities import ServerEntity
from app.servers.domain.ports import ServerReadPort
from app.servers.models import ServerType
from app.templates.domain.entities import (
    CreateTemplateCommand,
    TemplateEntity,
    TemplateListPage,
    TemplateListSpec,
    UpdateTemplateCommand,
)
from app.templates.domain.exceptions import (
    TemplateAccessError,
    TemplateCreationError,
    TemplateError,
    TemplateNotFoundError,
)
from app.templates.domain.ports import TemplatesUnitOfWork

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-function visibility helpers (kept module-level so tests can exercise
# them without instantiating the service).
# ---------------------------------------------------------------------------


def _can_access(template: TemplateEntity, viewer_id: int, viewer_is_admin: bool) -> bool:
    """Return True if `viewer` can read the template."""
    if viewer_is_admin:
        return True
    return template.is_public or template.created_by == viewer_id


def _can_modify(template: TemplateEntity, viewer_id: int, viewer_is_admin: bool) -> bool:
    """Return True if `viewer` can update or delete the template."""
    if viewer_is_admin:
        return True
    return template.created_by == viewer_id


class TemplateService:
    """Use cases over the template catalogue.

    Receives a `TemplatesUnitOfWork` and a `ServerReadPort` via
    constructor injection. Each public method opens a fresh UoW (one
    transaction) per logical operation; the same `_uow` instance is
    re-entered cleanly because the SQLAlchemy adapter shares the
    underlying session across entries in `db=session` mode (see
    `SqlAlchemyTemplatesUnitOfWork` for the re-entry semantics).
    """

    def __init__(
        self,
        uow: TemplatesUnitOfWork,
        server_read: ServerReadPort,
        templates_directory: Path = Path("templates"),
    ):
        self._uow = uow
        self._server_read = server_read
        self.templates_directory = Path(templates_directory)
        self.templates_directory.mkdir(exist_ok=True)

    # ===================
    # Public use cases
    # ===================

    async def create_template_from_server(
        self,
        server_id: int,
        name: str,
        creator_id: int,
        description: Optional[str] = None,
        is_public: bool = False,
    ) -> TemplateEntity:
        """Create a template by extracting configuration from an existing
        server.
        """
        try:
            server = await self._server_read.get(server_id)
            if server is None:
                raise TemplateNotFoundError(f"Server {server_id} not found")

            server_dir = Path(server.directory_path)
            if not server_dir.exists():
                raise TemplateCreationError(f"Server directory not found: {server_dir}")

            configuration = await self._extract_server_configuration(server, server_dir)

            command = CreateTemplateCommand(
                name=name,
                minecraft_version=server.minecraft_version,
                server_type=server.server_type,
                configuration=configuration,
                default_groups={"op_groups": [], "whitelist_groups": []},
                created_by=creator_id,
                is_public=is_public,
                description=description,
            )

            entity: Optional[TemplateEntity] = None
            try:
                async with self._uow as uow:
                    entity = await uow.templates.add(command)
                    assert entity.id is not None
                    await self._create_template_files(entity.id, server_dir)
                    await uow.commit()
            except Exception:
                # Known limitation (legacy behaviour, NOT introduced by
                # #225/#256): `_create_template_files` writes the
                # `template_{id}_files.tar.gz` archive to disk before
                # `await uow.commit()`. If the commit subsequently fails,
                # the DB row is rolled back but the on-disk archive is
                # left orphaned. Safe remediation needs atomic-rename
                # staging or a janitor sweep — tracked by #228
                # punch-list B (orphan-on-failure archive files).
                raise

            logger.info(
                f"Successfully created template {entity.id} from server {server_id}"
            )
            return entity

        except TemplateNotFoundError:
            raise
        except TemplateCreationError:
            raise
        except Exception as e:
            logger.error(f"Failed to create template from server {server_id}: {e}")
            raise TemplateCreationError(f"Failed to create template: {str(e)}")

    async def create_custom_template(
        self,
        name: str,
        minecraft_version: str,
        server_type: ServerType,
        configuration: Dict[str, Any],
        creator_id: int,
        description: Optional[str] = None,
        default_groups: Optional[Dict[str, List[int]]] = None,
        is_public: bool = False,
    ) -> TemplateEntity:
        """Create a custom template from explicit configuration."""
        command = CreateTemplateCommand(
            name=name,
            minecraft_version=minecraft_version,
            server_type=server_type,
            configuration=configuration,
            default_groups=default_groups or {"op_groups": [], "whitelist_groups": []},
            created_by=creator_id,
            is_public=is_public,
            description=description,
        )

        try:
            async with self._uow as uow:
                entity = await uow.templates.add(command)
                await uow.commit()
            logger.info(f"Successfully created custom template {entity.id}")
            return entity
        except Exception as e:
            logger.error(f"Failed to create custom template: {e}")
            raise TemplateCreationError(f"Failed to create template: {str(e)}")

    async def apply_template_to_server(self, template_id: int, server_dir: Path) -> bool:
        """Apply template files + properties to an existing server directory.

        Returns True on success, False if anything fails (matches the
        legacy contract; callers swallow exceptions silently).
        """
        try:
            async with self._uow as uow:
                template = await uow.templates.get(template_id)
            if template is None:
                raise TemplateNotFoundError(f"Template {template_id} not found")

            template_filename = f"template_{template_id}_files.tar.gz"
            template_path = self.templates_directory / template_filename

            if template_path.exists():
                with tarfile.open(template_path, "r:gz") as tar:
                    tar.extractall(path=server_dir, filter="data")
                logger.info(f"Applied template {template_id} files to {server_dir}")

            configuration = template.configuration
            if "server_properties" in configuration:
                await self._apply_server_properties(
                    server_dir, configuration["server_properties"]
                )

            return True

        except Exception as e:
            logger.error(f"Failed to apply template {template_id}: {e}")
            return False

    async def get_template(
        self, template_id: int, viewer_id: int, viewer_is_admin: bool
    ) -> Optional[TemplateEntity]:
        """Get template by id, enforcing visibility rules.

        Returns `None` if no row matches; raises `TemplateAccessError`
        if a row exists but the viewer cannot see it.
        """
        try:
            async with self._uow as uow:
                template = await uow.templates.get(template_id)

            if template is None:
                return None

            if not _can_access(template, viewer_id, viewer_is_admin):
                raise TemplateAccessError("Access denied to template")

            return template
        except TemplateAccessError:
            raise
        except Exception as e:
            logger.error(f"Failed to get template {template_id}: {e}")
            raise TemplateError(f"Failed to get template: {str(e)}")

    async def list_templates(
        self,
        viewer_id: int,
        viewer_is_admin: bool,
        minecraft_version: Optional[str] = None,
        server_type: Optional[ServerType] = None,
        is_public: Optional[bool] = None,
        page: int = 1,
        size: int = 50,
    ) -> TemplateListPage:
        """List templates visible to the viewer, with filters & pagination."""
        spec = TemplateListSpec(
            viewer_id=viewer_id,
            viewer_is_admin=viewer_is_admin,
            minecraft_version=minecraft_version,
            server_type=server_type,
            is_public=is_public,
            page=page,
            size=size,
        )
        try:
            async with self._uow as uow:
                return await uow.templates.list_paged(spec)
        except Exception as e:
            logger.error(f"Failed to list templates: {e}")
            raise TemplateError(f"Failed to list templates: {str(e)}")

    async def update_template(
        self,
        template_id: int,
        viewer_id: int,
        viewer_is_admin: bool,
        name: Optional[str] = None,
        description: Optional[str] = None,
        configuration: Optional[Dict[str, Any]] = None,
        default_groups: Optional[Dict[str, List[int]]] = None,
        is_public: Optional[bool] = None,
    ) -> Optional[TemplateEntity]:
        """Update a template, enforcing modify permissions."""
        try:
            async with self._uow as uow:
                existing = await uow.templates.get(template_id)
                if existing is None:
                    return None

                if not _can_modify(existing, viewer_id, viewer_is_admin):
                    raise TemplateAccessError("Access denied to modify template")

                command = UpdateTemplateCommand(
                    name=name,
                    description=description,
                    configuration=configuration,
                    default_groups=default_groups,
                    is_public=is_public,
                )
                updated = await uow.templates.update(template_id, command)
                await uow.commit()

            logger.info(f"Updated template {template_id}")
            return updated
        except TemplateAccessError:
            raise
        except Exception as e:
            logger.error(f"Failed to update template {template_id}: {e}")
            raise TemplateError(f"Failed to update template: {str(e)}")

    async def delete_template(
        self, template_id: int, viewer_id: int, viewer_is_admin: bool
    ) -> bool:
        """Delete a template if no servers depend on it.

        Returns `False` if the template does not exist. Raises
        `TemplateAccessError` if the viewer cannot modify it.
        Raises `TemplateError` if active dependent servers exist.
        """
        try:
            async with self._uow as uow:
                template = await uow.templates.get(template_id)
                if template is None:
                    return False

                if not _can_modify(template, viewer_id, viewer_is_admin):
                    raise TemplateAccessError("Access denied to delete template")

                dependents = await uow.templates.count_active_dependent_servers(
                    template_id
                )
                if dependents > 0:
                    raise TemplateError(
                        f"Cannot delete template: {dependents} servers are using it"
                    )

                # Delete on-disk archive (if any) before removing the row
                template_filename = f"template_{template_id}_files.tar.gz"
                template_path = self.templates_directory / template_filename
                if template_path.exists():
                    template_path.unlink()
                    logger.info(f"Deleted template files: {template_filename}")

                deleted = await uow.templates.delete(template_id)
                await uow.commit()

            logger.info(f"Successfully deleted template {template_id}")
            return deleted
        except TemplateAccessError:
            raise
        except TemplateError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete template {template_id}: {e}")
            raise TemplateError(f"Failed to delete template: {str(e)}")

    async def clone_template(
        self,
        original_template_id: int,
        name: str,
        viewer_id: int,
        viewer_is_admin: bool,
        description: Optional[str] = None,
        is_public: bool = False,
    ) -> TemplateEntity:
        """Clone an existing template by copying its config and archive.

        NOTE: the current router does not call this method (it composes
        `get_template` + `create_custom_template` instead). The method
        is preserved for backward compatibility with the legacy shim
        contract.
        """
        try:
            async with self._uow as uow:
                original = await uow.templates.get(original_template_id)
                if original is None:
                    raise TemplateNotFoundError(
                        f"Original template {original_template_id} not found"
                    )
                if not _can_access(original, viewer_id, viewer_is_admin):
                    raise TemplateAccessError("Access denied to clone template")

                duplicate = await uow.templates.find_by_creator_and_name(viewer_id, name)
                if duplicate is not None:
                    raise TemplateError("Template with this name already exists")

                command = CreateTemplateCommand(
                    name=name,
                    description=description or f"Clone of {original.name}",
                    minecraft_version=original.minecraft_version,
                    server_type=original.server_type,
                    configuration=original.configuration,
                    default_groups=original.default_groups,
                    created_by=viewer_id,
                    is_public=is_public,
                )
                new_template = await uow.templates.add(command)
                await uow.commit()

            # Copy on-disk archive if present (best-effort; failures are
            # logged but do not roll back the row)
            original_filename = f"template_{original_template_id}_files.tar.gz"
            original_path = self.templates_directory / original_filename
            if original_path.exists() and new_template.id is not None:
                new_filename = f"template_{new_template.id}_files.tar.gz"
                new_path = self.templates_directory / new_filename
                shutil.copy2(original_path, new_path)
                logger.info(
                    f"Copied template files from {original_filename} to {new_filename}"
                )

            logger.info(
                f"Successfully cloned template {original_template_id} as "
                f"{new_template.id}"
            )
            return new_template
        except TemplateNotFoundError:
            raise
        except TemplateAccessError:
            raise
        except TemplateError:
            raise
        except Exception as e:
            logger.error(f"Failed to clone template {original_template_id}: {e}")
            raise TemplateError(f"Failed to clone template: {str(e)}")

    async def get_template_statistics(
        self, viewer_id: int, viewer_is_admin: bool
    ) -> Dict[str, Any]:
        """Aggregate counts for the template catalogue.

        Returns the same dict shape as the legacy service so the
        router/schema layer is unchanged. `server_type_distribution`
        values are keyed by `ServerType.value` (string); the repository
        method returns `Dict[ServerType, int]` and this layer maps to
        the wire format.
        """
        try:
            async with self._uow as uow:
                total = await uow.templates.count_visible(viewer_id, viewer_is_admin)
                public = await uow.templates.count_visible_public(
                    viewer_id, viewer_is_admin
                )
                owned = await uow.templates.count_owned_by(viewer_id)
                by_type = await uow.templates.count_visible_by_server_type(
                    viewer_id, viewer_is_admin
                )

            distribution: Dict[str, int] = {st.value: 0 for st in ServerType}
            for server_type, count in by_type.items():
                distribution[server_type.value] = count

            return {
                "total_templates": total,
                "public_templates": public,
                "user_templates": owned,
                "server_type_distribution": distribution,
            }
        except Exception as e:
            logger.error(f"Failed to get template statistics: {e}")
            raise TemplateError(f"Failed to get template statistics: {str(e)}")

    # ===================
    # Internal helpers
    # ===================

    async def _extract_server_configuration(
        self, server: ServerEntity, server_dir: Path
    ) -> Dict[str, Any]:
        """Extract configuration metadata from a server directory."""
        try:
            configuration: Dict[str, Any] = {
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

            properties_path = server_dir / "server.properties"
            if properties_path.exists():
                configuration["server_properties"] = await self._parse_server_properties(
                    properties_path
                )

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
        """Parse a server.properties file into a plain dict."""
        try:
            properties: Dict[str, str] = {}
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

    async def _create_template_files(self, template_id: int, server_dir: Path) -> None:
        """Bundle server config files + dirs into the template archive."""
        try:
            template_filename = f"template_{template_id}_files.tar.gz"
            template_path = self.templates_directory / template_filename

            with tarfile.open(template_path, "w:gz") as tar:
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

                important_dirs = ["plugins", "mods", "config", "datapacks"]
                for dir_name in important_dirs:
                    dir_path = server_dir / dir_name
                    if dir_path.exists() and dir_path.is_dir():
                        tar.add(dir_path, arcname=dir_name)

            logger.info(f"Created template files archive: {template_filename}")
        except Exception as e:
            logger.error(f"Failed to create template files: {e}")
            raise TemplateCreationError(f"Failed to create template files: {str(e)}")

    async def _apply_server_properties(
        self, server_dir: Path, properties: Dict[str, str]
    ) -> None:
        """Merge template properties into the server.properties file."""
        try:
            properties_path = server_dir / "server.properties"

            existing_properties: Dict[str, str] = {}
            if properties_path.exists():
                existing_properties = await self._parse_server_properties(properties_path)

            existing_properties.update(properties)

            with open(properties_path, "w") as f:
                f.write("# Minecraft server properties\n")
                f.write("# Applied from template\n\n")
                for key, value in sorted(existing_properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(f"Applied server.properties from template to {properties_path}")
        except Exception as e:
            logger.error(f"Failed to apply server.properties: {e}")
