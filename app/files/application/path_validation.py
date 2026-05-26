import logging
from pathlib import Path
from typing import Annotated, Any

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AccessDeniedException,
    FileMissingError,
    FileOperationException,
    InvalidFileTypeError,
    ServerNotFoundException,
)
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.users.domain.value_objects import Role
from app.users.models import User

logger = logging.getLogger(__name__)


class FileValidationService:
    """Service for validating file operations and access.

    This service handles all validation logic for file operations including
    server existence, path safety, file permissions, and access control.
    """

    def __init__(self) -> None:
        self.allowed_extensions = {
            "config": [".properties", ".yml", ".yaml", ".json", ".txt", ".conf"],
            "world": [".dat", ".dat_old", ".mca", ".mcr"],
            "plugin": [".jar"],
            "mod": [".jar"],
            "log": [".log", ".gz"],
        }
        self.restricted_files = [
            # Core server files
            "server.jar",
            "eula.txt",
            # Permission and access control files
            "ops.json",
            "whitelist.json",
            "banned-players.json",
            "banned-ips.json",
            # Server configuration files (Bukkit/Spigot/Paper)
            "bukkit.yml",
            "spigot.yml",
            "paper.yml",
            "paper-global.yml",
            "paper-world-defaults.yml",
            # Plugin and command configuration
            "plugins.yml",
            "commands.yml",
            "permissions.yml",
            "help.yml",
            # World data files (critical for world integrity)
            "level.dat",
            "level.dat_old",
            "session.lock",
            # User cache and security files
            "usercache.json",
            "usernamecache.json",
            # Additional server implementation JARs
            "minecraft_server.jar",
            "forge.jar",
            "fabric-server-launch.jar",
            # Plugin management files
            "plugin.yml",
            "mod.toml",
            # Proxy server configurations (for multi-server setups)
            "config.yml",
            "velocity.toml",
            "waterfall.yml",
        ]

    async def validate_server_exists(
        self,
        server_id: Annotated[int, "ID of the server to validate"],
        db: Annotated[Session, "Database session for queries"],
    ) -> Annotated[Any, "Validated server view with `directory_path`"]:
        """Validate that a server exists in the database.

        Returns a view exposing `directory_path` so callers that need only
        the on-disk path continue to work unchanged. Resolution goes
        through `SqlAlchemyServerReadPort.get`, which returns a
        domain-pure `ServerEntity` (soft-deleted rows are excluded).

        Raises:
            ServerNotFoundException: If server doesn't exist.
        """
        server = await SqlAlchemyServerReadPort(db).get(server_id)
        if server is None:
            raise ServerNotFoundException(str(server_id))
        return server

    def validate_server_directory(self, server_path: Path) -> None:
        """Validate server directory exists, create if it doesn't"""
        if not server_path.exists():
            # Create the server directory if it doesn't exist
            try:
                server_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created server directory: {server_path}")
            except Exception as e:
                raise FileOperationException(
                    "access", str(server_path), f"Failed to create server directory: {e}"
                )

    def validate_path_safety(self, server_path: Path, target_path: Path) -> None:
        """Validate path is safe and within server directory"""
        if not self._is_safe_path(server_path, target_path):
            raise AccessDeniedException("file", "access")

    def validate_path_exists(self, target_path: Path) -> None:
        """Validate target path exists"""
        if not target_path.exists():
            raise FileMissingError("access", str(target_path))

    def validate_file_readable(self, file_path: Path) -> None:
        """Validate file is readable"""
        if file_path.is_dir():
            raise InvalidFileTypeError(
                "read",
                str(file_path),
                "Path is a directory, not a file",
                detected_type="directory",
            )

        if not self._is_readable_file(file_path):
            # ``AccessDeniedException`` (403) preserved for backwards
            # compatibility with existing tests; the policy denial is
            # distinct from OS-level permission errors, which are mapped
            # to :class:`FileAccessDeniedError` by ``handle_file_error``.
            raise AccessDeniedException("file", "read")

    def validate_file_writable(self, file_path: Path, user: User) -> None:
        """Validate file can be written"""
        if self._is_restricted_file(file_path) and user.role != Role.admin:
            raise AccessDeniedException("file", "write")

        if not self._is_writable_file(file_path):
            raise AccessDeniedException("file", "edit")

    def validate_path_deletable(self, path: Path, user: User = None) -> None:
        """Validate path (file or directory) can be deleted"""
        # Only validate that the path exists - no file type restrictions
        # The actual existence check is done by validate_path_exists
        # This method is kept for API consistency but doesn't add restrictions
        pass

    def _is_safe_path(self, server_path: Path, target_path: Path) -> bool:
        """Check if target path is within server directory"""
        try:
            target_path.resolve().relative_to(server_path.resolve())
            return True
        except ValueError:
            return False

    def _is_readable_file(self, file_path: Path) -> bool:
        """Check if file type is readable"""
        suffix = file_path.suffix.lower()
        for _, extensions in self.allowed_extensions.items():
            if suffix in extensions:
                return True
        return suffix in [
            ".txt",
            ".md",
            ".yml",
            ".yaml",
            ".json",
            ".properties",
            ".sh",
            ".bat",
            ".ini",
            ".cfg",
            ".xml",
        ]

    def _is_writable_file(self, file_path: Path) -> bool:
        """Check if file type is writable"""
        if file_path.is_dir():
            return False

        suffix = file_path.suffix.lower()
        writable_extensions = [".properties", ".yml", ".yaml", ".json", ".txt", ".conf"]
        return suffix in writable_extensions

    def _is_restricted_file(self, file_path: Path) -> bool:
        """Check if file is restricted from modification"""
        return file_path.name in self.restricted_files
