import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import aiofiles
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AccessDeniedException,
    FileOperationException,
    InvalidRequestException,
    ServerNotFoundException,
    handle_file_error,
)
from app.servers.models import Server
from app.services.encoding_handler import EncodingHandler
from app.services.file_history_service import file_history_service
from app.types import FileType
from app.users.models import Role, User

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

    def validate_server_exists(
        self,
        server_id: Annotated[int, "ID of the server to validate"],
        db: Annotated[Session, "Database session for queries"],
    ) -> Annotated[Server, "Validated server instance"]:
        """Validate that a server exists in the database.

        Args:
            server_id: The ID of the server to validate
            db: Database session for querying

        Returns:
            Server instance if validation passes

        Raises:
            ServerNotFoundException: If server doesn't exist
        """
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
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
            raise FileOperationException("access", str(target_path), "Path not found")

    def validate_file_readable(self, file_path: Path) -> None:
        """Validate file is readable"""
        if file_path.is_dir():
            raise FileOperationException(
                "read", str(file_path), "Path is a directory, not a file"
            )

        if not self._is_readable_file(file_path):
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


class FileInfoService:
    """Service for retrieving file information"""

    def __init__(self, validation_service: FileValidationService):
        self.validation_service = validation_service

    async def get_file_info(self, file_path: Path, server_path: Path) -> Dict[str, Any]:
        """Get comprehensive file information"""
        try:
            stats = file_path.stat()
            relative_path = file_path.relative_to(server_path)

            return {
                "name": file_path.name,
                "path": str(relative_path),
                "size": stats.st_size if file_path.is_file() else 0,
                "modified": datetime.fromtimestamp(stats.st_mtime).isoformat(),
                "is_directory": file_path.is_dir(),
                "is_file": file_path.is_file(),
                "extension": file_path.suffix,
                "type": self._determine_file_type(file_path),
                "readable": self._is_file_readable(file_path),
                "writable": self._is_file_writable(file_path),
                "permissions": {
                    "read": self._is_file_readable(file_path),
                    "write": self._is_file_writable(file_path),
                    "execute": file_path.is_file()
                    and file_path.suffix in [".sh", ".bat", ".exe"],
                },
            }
        except Exception as e:
            handle_file_error("get info", str(file_path), e)

    def _determine_file_type(self, file_path: Path) -> str:
        """Determine file type based on extension"""
        if file_path.is_dir():
            return "directory"

        suffix = file_path.suffix.lower()

        # Text files
        text_extensions = [
            ".txt",
            ".md",
            ".yml",
            ".yaml",
            ".json",
            ".properties",
            ".conf",
            ".log",
            ".sh",
            ".bat",
            ".xml",
            ".html",
            ".css",
            ".js",
            ".py",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".ini",
            ".cfg",
        ]

        # Binary files
        binary_extensions = [
            ".jar",
            ".zip",
            ".tar",
            ".gz",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".pdf",
            ".dat",
            ".mca",
            ".mcr",
            ".bin",
        ]

        if suffix in text_extensions:
            return "text"
        elif suffix in binary_extensions:
            return "binary"
        else:
            return "other"

    def _is_file_readable(self, file_path: Path) -> bool:
        """Check if file is readable"""
        if file_path.is_dir():
            return True

        suffix = file_path.suffix.lower()
        readable_extensions = [
            ".txt",
            ".md",
            ".yml",
            ".yaml",
            ".json",
            ".properties",
            ".conf",
            ".log",
            ".sh",
            ".bat",
            ".ini",
            ".cfg",
            ".xml",
        ]
        return suffix in readable_extensions

    def _is_file_writable(self, file_path: Path) -> bool:
        """Check if file is writable"""
        return self.validation_service._is_writable_file(
            file_path
        ) and not self.validation_service._is_restricted_file(file_path)


class FileBackupService:
    """Service for creating file backups"""

    async def create_file_backup(self, file_path: Path) -> str:
        """Create backup of existing file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{file_path.name}.backup_{timestamp}"
            backup_path = file_path.parent / backup_name

            shutil.copy2(file_path, backup_path)
            return str(backup_path)

        except Exception as e:
            handle_file_error("backup", str(file_path), e)


class FileOperationService:
    """Service for file system operations"""

    def __init__(self, backup_service: FileBackupService):
        self.backup_service = backup_service

    async def read_file_content(
        self, file_path: Path, encoding: str = None
    ) -> tuple[str, str]:
        """Read file content with automatic encoding detection

        Returns:
            Tuple of (content, detected_encoding)
        """
        try:
            if encoding:
                # If encoding is specified, use it directly
                async with aiofiles.open(file_path, mode="r", encoding=encoding) as f:
                    content = await f.read()
                    return content, encoding
            else:
                # Use encoding detection for better compatibility
                result = EncodingHandler.safe_read_text_file(str(file_path))
                if result["success"]:
                    logger.info(
                        f"File read successfully with encoding: {result['encoding']}"
                    )
                    return result["content"], result["encoding"]
                else:
                    raise InvalidRequestException(
                        f"Unable to decode file: {result['error']}"
                    )
        except UnicodeDecodeError:
            raise InvalidRequestException(
                f"Unable to decode file with {encoding} encoding"
            )
        except Exception as e:
            handle_file_error("read", str(file_path), e)

    async def read_image_as_base64(self, file_path: Path) -> str:
        """Read image file and return as base64 encoded string"""
        import base64

        try:
            async with aiofiles.open(file_path, mode="rb") as f:
                image_data = await f.read()
                return base64.b64encode(image_data).decode("utf-8")
        except Exception as e:
            handle_file_error("read image", str(file_path), e)

    async def write_file_content(
        self,
        file_path: Path,
        content: str,
        encoding: str = "utf-8",
        create_backup: bool = True,
        server_id: int = None,
        user_id: int = None,
        description: str = None,
        db: Session = None,
    ) -> Optional[str]:
        """Write content to file with specified encoding and create history backup"""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            backup_record = None
            if create_backup and file_path.exists() and server_id is not None:
                # Read current content for history backup
                try:
                    async with aiofiles.open(file_path, mode="r", encoding=encoding) as f:
                        current_content = await f.read()

                    # Extract relative file path from server directory
                    relative_path = self._extract_relative_path(file_path, server_id, db)

                    # Create history backup using new service
                    backup_record = await file_history_service.create_version_backup(
                        server_id=server_id,
                        file_path=relative_path,
                        content=current_content,
                        user_id=user_id,
                        description=description,
                        db=db,
                    )
                except Exception as e:
                    logger.warning(f"Failed to create history backup: {e}")

            # Write new content
            async with aiofiles.open(file_path, mode="w", encoding=encoding) as f:
                await f.write(content)

            return str(backup_record.backup_file_path) if backup_record else None

        except Exception as e:
            handle_file_error("write", str(file_path), e)

    def _extract_relative_path(self, file_path: Path, server_id: int, db: Session) -> str:
        """Extract relative path from server directory"""
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise ServerNotFoundException(f"Server {server_id} not found")

        server_path = Path(server.directory_path)
        try:
            relative_path = file_path.relative_to(server_path)
            return str(relative_path)
        except ValueError:
            # If file is not within server directory, use the filename
            return file_path.name

    async def upload_file(self, file: UploadFile, target_path: Path) -> int:
        """Upload file to target path and return file size"""
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)

            content = await file.read()

            async with aiofiles.open(target_path, mode="wb") as f:
                await f.write(content)

            return len(content)

        except Exception as e:
            handle_file_error("upload", str(target_path), e)

    def delete_file_or_directory(self, path: Path) -> str:
        """Delete file or directory and return operation type"""
        try:
            if path.is_file():
                path.unlink()
                return "file"
            elif path.is_dir():
                shutil.rmtree(path)
                return "directory"
        except Exception as e:
            handle_file_error("delete", str(path), e)

    def create_directory(self, path: Path) -> None:
        """Create directory"""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            handle_file_error("create directory", str(path), e)

    def move_file_or_directory(self, source: Path, destination: Path) -> None:
        """Move file or directory"""
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except Exception as e:
            handle_file_error("move", f"{source} to {destination}", e)

    def extract_archive(self, archive_path: Path, extract_to: Path) -> List[str]:
        """Extract archive and return list of extracted files"""
        try:
            extracted_files = []

            if archive_path.suffix.lower() == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(extract_to)
                    extracted_files = zip_ref.namelist()
            else:
                raise InvalidRequestException(
                    f"Unsupported archive format: {archive_path.suffix}"
                )

            return extracted_files

        except Exception as e:
            handle_file_error("extract", str(archive_path), e)


class FileSearchService:
    """Service for searching files"""

    def __init__(
        self, validation_service: FileValidationService, info_service: FileInfoService
    ):
        self.validation_service = validation_service
        self.info_service = info_service

    async def search_files(
        self,
        server_id: int,
        search_term: str,
        search_in_content: bool = False,
        file_type: Optional[str] = None,
        max_results: int = 100,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Search for files by name and optionally content"""
        # Validate server
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        self.validation_service.validate_server_directory(server_path)

        start_time = datetime.now()
        results = []

        # Search by filename
        filename_results = await self._search_by_filename(
            server_path, search_term, file_type, max_results
        )
        results.extend(filename_results)

        # Search in content if requested
        if search_in_content and len(results) < max_results:
            content_results = await self._search_file_content(
                server_path, search_term, file_type, max_results - len(results)
            )
            results.extend(content_results)

        search_time = (datetime.now() - start_time).total_seconds()

        return {
            "results": results[:max_results],
            "total_found": len(results),
            "search_time_seconds": round(search_time, 3),
            "search_term": search_term,
            "searched_content": search_in_content,
        }

    async def _search_by_filename(
        self,
        server_path: Path,
        search_term: str,
        file_type: Optional[str],
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Search files by filename"""
        results = []

        for file_path in server_path.rglob("*"):
            if len(results) >= max_results:
                break

            if search_term.lower() in file_path.name.lower():
                try:
                    file_info = await self.info_service.get_file_info(
                        file_path, server_path
                    )
                    if not file_type or file_info["type"] == file_type:
                        file_info["match_type"] = "filename"
                        results.append(file_info)
                except Exception:
                    continue

        return results

    async def _search_file_content(
        self,
        server_path: Path,
        search_term: str,
        file_type: Optional[str],
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Search in file content"""
        results = []

        for file_path in server_path.rglob("*"):
            if len(results) >= max_results:
                break

            if file_path.is_file() and self.validation_service._is_readable_file(
                file_path
            ):
                try:
                    file_info = await self.info_service.get_file_info(
                        file_path, server_path
                    )
                    if file_type and file_info["type"] != file_type:
                        continue

                    # Read file content and search
                    async with aiofiles.open(
                        file_path, mode="r", encoding="utf-8", errors="ignore"
                    ) as f:
                        content = await f.read()
                        if search_term.lower() in content.lower():
                            file_info["match_type"] = "content"
                            results.append(file_info)

                except Exception:
                    continue

        return results


class FileManagementService:
    """Main service for orchestrating file management operations"""

    def __init__(self):
        self.validation_service = FileValidationService()
        self.info_service = FileInfoService(self.validation_service)
        self.backup_service = FileBackupService()
        self.operation_service = FileOperationService(self.backup_service)
        self.search_service = FileSearchService(
            self.validation_service, self.info_service
        )

    async def get_server_files(
        self,
        server_id: int,
        path: str = "",
        file_type: Optional[FileType] = None,
        db: Session = None,
    ) -> List[Dict[str, Any]]:
        """Get files and directories in server path"""
        # Validate server and paths
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        self.validation_service.validate_server_directory(server_path)

        target_path = server_path / path
        self.validation_service.validate_path_safety(server_path, target_path)
        self.validation_service.validate_path_exists(target_path)

        # Get file information
        files = await self._collect_file_information(target_path, server_path, file_type)

        return sorted(files, key=lambda x: (not x["is_directory"], x["name"]))

    async def _collect_file_information(
        self, target_path: Path, server_path: Path, file_type: Optional[FileType]
    ) -> List[Dict[str, Any]]:
        """Collect file information for directory or single file"""
        files = []

        if target_path.is_dir():
            for item in target_path.iterdir():
                file_info = await self.info_service.get_file_info(item, server_path)
                if file_type is None or file_info["type"] == file_type:
                    files.append(file_info)
        else:
            file_info = await self.info_service.get_file_info(target_path, server_path)
            files.append(file_info)

        return files

    async def read_file(
        self,
        server_id: int,
        file_path: str,
        encoding: str = None,
        db: Session = None,
    ) -> tuple[str, str]:
        """Read file content with encoding detection

        Returns:
            Tuple of (content, detected_encoding)
        """
        # Validate server and file
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_file = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_file)
        self.validation_service.validate_path_exists(target_file)
        self.validation_service.validate_file_readable(target_file)

        # Read file content with encoding detection
        return await self.operation_service.read_file_content(target_file, encoding)

    async def read_image_as_base64(
        self,
        server_id: int,
        file_path: str,
        db: Session = None,
    ) -> str:
        """Read image file and return as base64 encoded string"""
        # Validate server and file
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_file = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_file)
        self.validation_service.validate_path_exists(target_file)

        # Check if file is actually an image
        if not self._is_image_file(target_file):
            raise InvalidRequestException(f"File {file_path} is not a valid image file")

        # Read image as base64
        return await self.operation_service.read_image_as_base64(target_file)

    def _is_image_file(self, file_path: Path) -> bool:
        """Check if file is a valid image file"""
        image_extensions = [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".webp",
            ".svg",
        ]
        return file_path.suffix.lower() in image_extensions

    async def write_file(
        self,
        server_id: int,
        file_path: str,
        content: str,
        encoding: str = "utf-8",
        create_backup: bool = True,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Write content to file"""
        # Validate server and file
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_file = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_file)
        self.validation_service.validate_file_writable(target_file, user)

        # Write file content with history backup
        backup_path = await self.operation_service.write_file_content(
            file_path=target_file,
            content=content,
            encoding=encoding,
            create_backup=create_backup,
            server_id=server_id,
            user_id=user.id if user else None,
            description=None,
            db=db,
        )

        # Get updated file info
        file_info = await self.info_service.get_file_info(target_file, server_path)

        return {
            "message": "File updated successfully",
            "file": file_info,
            "backup_created": backup_path is not None,
            "backup_path": backup_path,
        }

    async def delete_file(
        self,
        server_id: int,
        file_path: str,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, str]:
        """Delete file or directory"""
        # Validate server and file
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_path = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_path)
        self.validation_service.validate_path_exists(target_path)
        self.validation_service.validate_path_deletable(target_path, user)

        # Delete file or directory
        operation_type = self.operation_service.delete_file_or_directory(target_path)

        return {"message": f"{operation_type.title()} '{file_path}' deleted successfully"}

    async def upload_file(
        self,
        server_id: int,
        file: UploadFile,
        destination_path: str = "",
        extract_if_archive: bool = False,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Upload file to server directory"""
        # Validate server
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_dir = server_path / destination_path

        self.validation_service.validate_path_safety(server_path, target_dir)

        # Upload file
        target_file = target_dir / file.filename
        await self.operation_service.upload_file(file, target_file)

        # Get file info for response
        file_info = await self.info_service.get_file_info(target_file, server_path)

        result = {
            "message": f"File '{file.filename}' uploaded successfully",
            "file": file_info,
            "extracted_files": [],
        }

        # Extract if archive and requested
        if extract_if_archive and target_file.suffix.lower() in [".zip"]:
            extracted_files = self.operation_service.extract_archive(
                target_file, target_dir
            )
            result["extracted_files"] = extracted_files

            # Delete archive after extraction
            target_file.unlink()

            # Update message to reflect extraction
            result["message"] = (
                f"Archive '{file.filename}' uploaded and extracted successfully"
            )

        return result

    async def search_files(
        self,
        server_id: int,
        search_term: str,
        search_in_content: bool = False,
        file_type: Optional[str] = None,
        max_results: int = 100,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Search for files by name and optionally content"""
        return await self.search_service.search_files(
            server_id, search_term, search_in_content, file_type, max_results, db
        )

    async def create_directory(
        self,
        server_id: int,
        directory_path: str,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Create new directory"""
        # Validate server
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_dir = server_path / directory_path

        self.validation_service.validate_path_safety(server_path, target_dir)

        # Create directory
        self.operation_service.create_directory(target_dir)

        # Get directory info
        directory_info = await self.info_service.get_file_info(target_dir, server_path)

        return {
            "message": f"Directory '{directory_path}' created successfully",
            "directory": directory_info,
        }

    async def move_file(
        self,
        server_id: int,
        source_path: str,
        destination_path: str,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, str]:
        """Move file or directory"""
        # Validate server
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        source = server_path / source_path
        destination = server_path / destination_path

        self.validation_service.validate_path_safety(server_path, source)
        self.validation_service.validate_path_safety(server_path, destination)
        self.validation_service.validate_path_exists(source)
        self.validation_service.validate_path_deletable(source, user)

        # Move file or directory
        self.operation_service.move_file_or_directory(source, destination)

        return {"message": f"Moved '{source_path}' to '{destination_path}' successfully"}

    async def rename_file(
        self,
        server_id: int,
        file_path: str,
        new_name: str,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Rename file or directory"""
        # Validate server
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        source_path = server_path / file_path

        # Validate source path
        self.validation_service.validate_path_safety(server_path, source_path)
        self.validation_service.validate_path_exists(source_path)
        self.validation_service.validate_path_deletable(source_path, user)

        # Validate new name
        if not self._is_valid_filename(new_name):
            raise InvalidRequestException("Invalid filename: contains illegal characters")

        # Create destination path (same directory, new name)
        destination_path = source_path.parent / new_name

        # Check if destination already exists
        if destination_path.exists():
            raise FileOperationException(
                "rename",
                str(source_path),
                f"File or directory '{new_name}' already exists",
            )

        # Validate destination path safety
        self.validation_service.validate_path_safety(server_path, destination_path)

        # Perform rename operation
        self.operation_service.move_file_or_directory(source_path, destination_path)

        # Get updated file info
        file_info = await self.info_service.get_file_info(destination_path, server_path)

        return {
            "message": f"Successfully renamed '{source_path.name}' to '{new_name}'",
            "old_path": file_path,
            "new_path": str(destination_path.relative_to(server_path)),
            "file": file_info,
        }

    def _is_valid_filename(self, filename: str) -> bool:
        """Validate filename against illegal characters and patterns"""
        import re

        # Check for empty or whitespace-only names
        if not filename or not filename.strip():
            return False

        # Check for illegal characters (Windows + Unix)
        illegal_chars = r'[<>:"/\\|?*\x00-\x1f]'
        if re.search(illegal_chars, filename):
            return False

        # Check for reserved names (Windows)
        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        if filename.upper().split(".")[0] in reserved_names:
            return False

        # Check for names starting/ending with dots or spaces
        if filename.startswith(".") or filename.endswith(".") or filename.endswith(" "):
            return False

        # Check length (most filesystems have 255 character limit)
        if len(filename.encode("utf-8")) > 255:
            return False

        return True

    async def download_file(
        self,
        server_id: int,
        file_path: str,
        db: Session = None,
    ) -> tuple[str, str]:
        """Download file from server directory"""
        # Validate server and file
        server = self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_file = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_file)
        self.validation_service.validate_path_exists(target_file)
        self.validation_service.validate_file_readable(target_file)

        # Return file location and filename for FileResponse
        return str(target_file), target_file.name


# Global file management service instance
file_management_service = FileManagementService()
