import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    FileAlreadyExistsError,
    InvalidRequestException,
)
from app.files.application.encoding_handler import EncodingHandler
from app.files.application.file_info import FileInfoService
from app.files.application.file_io import FileBackupService, FileOperationService
from app.files.application.file_search import FileSearchService
from app.files.application.path_validation import FileValidationService
from app.types import FileType
from app.users.models import User

logger = logging.getLogger(__name__)


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
        db: Session,
        path: str = "",
        file_type: Optional[FileType] = None,
    ) -> List[Dict[str, Any]]:
        """Get files and directories in server path

        Args:
            server_id: ID of the server to list files for
            path: Relative path within the server directory
            file_type: Optional file type filter
            db: Database session (required for security validation)

        Returns:
            List of file and directory information dictionaries
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file listing operations"
            )

        # Validate server and paths
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        db: Session,
        encoding: str = None,
    ) -> tuple[str, str]:
        """Read file content with encoding detection

        Args:
            server_id: ID of the server containing the file
            file_path: Relative path to the file within the server directory
            encoding: Optional encoding to use for reading
            db: Database session (required for security validation)

        Returns:
            Tuple of (content, detected_encoding)
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file read operations"
            )

        # Validate server and file
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        db: Session,
    ) -> str:
        """Read image file and return as base64 encoded string

        Args:
            server_id: ID of the server containing the image
            file_path: Relative path to the image file within the server directory
            db: Database session (required for security validation)

        Returns:
            Base64 encoded string of the image content
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for image read operations"
            )

        # Validate server and file
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        db: Session,
        encoding: str = "utf-8",
        create_backup: bool = True,
        user: User = None,
    ) -> Dict[str, Any]:
        """Write content to file

        Args:
            server_id: ID of the server containing the file
            file_path: Relative path to the file within the server directory
            content: Content to write to the file
            encoding: File encoding (default: utf-8)
            create_backup: Whether to create a backup before writing
            user: User performing the operation
            db: Database session (required for security validation)

        Returns:
            Dictionary containing operation results and file information
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file write operations"
            )

        # Validate server and file
        server = await self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_file = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_file)
        self.validation_service.validate_file_writable(target_file, user)

        # Write file content with history backup
        backup_path = await self.operation_service.write_file_content(
            file_path=target_file,
            content=content,
            db=db,
            encoding=encoding,
            create_backup=create_backup,
            server_id=server_id,
            user_id=user.id if user else None,
            description=None,
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
        db: Session,
        user: User = None,
    ) -> Dict[str, str]:
        """Delete file or directory

        Args:
            server_id: ID of the server containing the file
            file_path: Relative path to the file/directory within the server directory
            user: User performing the operation
            db: Database session (required for security validation)

        Returns:
            Dictionary containing deletion confirmation message
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file delete operations"
            )

        # Validate server and file
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        db: Session,
        destination_path: str = "",
        extract_if_archive: bool = False,
        user: User = None,
    ) -> Dict[str, Any]:
        """Upload file to server directory

        Args:
            server_id: ID of the server to upload to
            file: Uploaded file object
            destination_path: Relative path within server directory for upload
            extract_if_archive: Whether to extract archive files after upload
            user: User performing the operation
            db: Database session (required for security validation)

        Returns:
            Dictionary containing upload results and file information
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file upload operations"
            )

        # Validate server
        server = await self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_dir = server_path / destination_path

        self.validation_service.validate_path_safety(server_path, target_dir)

        # ``UploadFile.filename`` is ``Optional[str]``; reject missing/empty
        # names explicitly so ``Path(None)`` doesn't surface as a TypeError.
        # ``Path(".").name`` resolves to ``""``; ``Path("..").name`` resolves
        # to ``".."`` which is caught by the downstream ``validate_path_safety``.
        if not file.filename:
            raise InvalidRequestException("Filename is required for file upload")

        # Strip any directory components from the attacker-controlled
        # ``Content-Disposition`` filename, then re-validate the resolved
        # path so traversal sequences (e.g. ``../../other-server/ops.json``)
        # cannot escape ``server_path``.
        safe_name = Path(file.filename).name
        if not safe_name:
            raise InvalidRequestException("Invalid filename for file upload")
        target_file = target_dir / safe_name
        self.validation_service.validate_path_safety(server_path, target_file)

        await self.operation_service.upload_file(file, target_file)

        # Get file info for response
        file_info = await self.info_service.get_file_info(target_file, server_path)

        result = {
            "message": f"File '{safe_name}' uploaded successfully",
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
                f"Archive '{safe_name}' uploaded and extracted successfully"
            )

        return result

    async def search_files(
        self,
        server_id: int,
        search_term: str,
        db: Session,
        search_in_content: bool = False,
        file_type: Optional[str] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Search for files by name and optionally content

        Args:
            server_id: ID of the server to search in
            search_term: Term to search for in filenames and/or content
            db: Database session (required for security validation)
            search_in_content: Whether to search inside file contents
            file_type: Optional file type filter
            max_results: Maximum number of results to return

        Returns:
            Dictionary containing search results and metadata
        """
        return await self.search_service.search_files(
            server_id, search_term, db, search_in_content, file_type, max_results
        )

    async def create_directory(
        self,
        server_id: int,
        directory_path: str,
        db: Session,
    ) -> Dict[str, Any]:
        """Create new directory

        Args:
            server_id: ID of the server to create directory in
            directory_path: Relative path for the new directory within server directory
            db: Database session (required for security validation)

        Returns:
            Dictionary containing creation results and directory information
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for directory creation operations"
            )

        # Validate server
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        db: Session,
        user: User = None,
    ) -> Dict[str, str]:
        """Move file or directory

        Args:
            server_id: ID of the server containing the file
            source_path: Current relative path of the file/directory
            destination_path: Target relative path for the file/directory
            user: User performing the operation
            db: Database session (required for security validation)

        Returns:
            Dictionary containing move confirmation message
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file move operations"
            )

        # Validate server
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        db: Session,
        user: User = None,
    ) -> Dict[str, Any]:
        """Rename file or directory

        Args:
            server_id: ID of the server containing the file
            file_path: Current relative path of the file/directory
            new_name: New name for the file/directory
            user: User performing the operation
            db: Database session (required for security validation)

        Returns:
            Dictionary containing rename results and updated file information
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file rename operations"
            )

        # Validate server
        server = await self.validation_service.validate_server_exists(server_id, db)
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

        # Check if destination already exists. Routed through the
        # dedicated :class:`FileAlreadyExistsError` (HTTP 409, #341)
        # so the client gets a structured envelope with the existing
        # path and actionable suggestions.
        if destination_path.exists():
            raise FileAlreadyExistsError(
                "rename",
                str(source_path),
                f"File or directory '{new_name}' already exists",
                existing_path=str(destination_path.relative_to(server_path)),
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
        db: Session,
    ) -> tuple[str, str]:
        """Download file from server directory

        Args:
            server_id: ID of the server containing the file
            file_path: Relative path to the file within the server directory
            db: Database session (required for security validation)

        Returns:
            Tuple of (file_path, filename) for FileResponse
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file download operations"
            )

        # Validate server and file
        server = await self.validation_service.validate_server_exists(server_id, db)
        server_path = Path(server.directory_path)
        target_file = server_path / file_path

        self.validation_service.validate_path_safety(server_path, target_file)
        self.validation_service.validate_path_exists(target_file)
        self.validation_service.validate_file_readable(target_file)

        # Return file location and filename for FileResponse
        return str(target_file), target_file.name


# Global file management service instance
file_management_service = FileManagementService()


# Backwards-compatibility re-exports.
#
# These symbols used to live in this module and are still imported and
# patched (``@patch("app.files.application.management.<symbol>")``) by
# existing tests and downstream callers. Keep them exposed so the split
# is purely structural.
__all__ = [
    "EncodingHandler",
    "FileBackupService",
    "FileInfoService",
    "FileManagementService",
    "FileOperationService",
    "FileSearchService",
    "FileValidationService",
    "file_management_service",
    "settings",
]
