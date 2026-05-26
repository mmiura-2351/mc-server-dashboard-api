import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import ClassVar, List, Optional

import aiofiles
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    FileTooLargeError,
    InvalidRequestException,
    ServerNotFoundException,
    handle_file_error,
)
from app.files.adapters.legacy import file_history_service
from app.files.application.encoding_handler import EncodingHandler
from app.servers.adapters.read_port import SqlAlchemyServerReadPort

logger = logging.getLogger(__name__)


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
        db: Session,
        encoding: str = "utf-8",
        create_backup: bool = True,
        server_id: int = None,
        user_id: int = None,
        description: str = None,
    ) -> Optional[str]:
        """Write content to file with specified encoding and create history backup

        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            encoding: File encoding (default: utf-8)
            create_backup: Whether to create a backup before writing
            server_id: Server ID for backup tracking
            user_id: User ID for backup tracking
            description: Description for the backup
            db: Database session (required for security-critical operations)

        Returns:
            Path to backup file if created, None otherwise
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file write operations"
            )

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            backup_record = None
            if create_backup and file_path.exists() and server_id is not None:
                # Read current content for history backup
                try:
                    async with aiofiles.open(file_path, mode="r", encoding=encoding) as f:
                        current_content = await f.read()

                    # Extract relative file path from server directory
                    relative_path = await self._extract_relative_path(
                        file_path, server_id, db
                    )

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

    async def _extract_relative_path(
        self, file_path: Path, server_id: int, db: Session
    ) -> str:
        """Extract relative path from server directory"""
        directory_path = await SqlAlchemyServerReadPort(db).get_directory_path(server_id)
        if directory_path is None:
            raise ServerNotFoundException(f"Server {server_id} not found")

        server_path = Path(directory_path)
        try:
            relative_path = file_path.relative_to(server_path)
            return str(relative_path)
        except ValueError:
            # If file is not within server directory, use the filename
            return file_path.name

    # 64 KiB chunk size matches the default disk page size for most
    # filesystems and keeps peak per-request memory bounded while
    # streaming the upload to disk.
    _UPLOAD_CHUNK_BYTES: ClassVar[int] = 64 * 1024

    async def upload_file(self, file: UploadFile, target_path: Path) -> int:
        """Upload file to target path and return file size.

        Reads the upload in fixed-size chunks (#341) so the full payload
        never materialises in memory. The running total is checked
        against ``settings.FILE_MAX_UPLOAD_BYTES`` after every chunk and
        a :class:`FileTooLargeError` is raised the moment the limit is
        exceeded — any partial output is removed before the exception
        propagates. ``FILE_MAX_UPLOAD_BYTES = 0`` disables enforcement.
        """
        from app.core.concurrency import get_semaphores

        async with get_semaphores().file_io:
            return await self._upload_file_inner(file, target_path)

    async def _upload_file_inner(self, file: UploadFile, target_path: Path) -> int:
        max_bytes = settings.FILE_MAX_UPLOAD_BYTES
        enforce_limit = max_bytes > 0
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)

            total = 0
            try:
                async with aiofiles.open(target_path, mode="wb") as f:
                    while True:
                        chunk = await file.read(self._UPLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if enforce_limit and total > max_bytes:
                            raise FileTooLargeError(
                                "upload",
                                str(target_path),
                                size_bytes=total,
                                max_bytes=max_bytes,
                            )
                        await f.write(chunk)
            except FileTooLargeError:
                try:
                    if target_path.exists():
                        target_path.unlink()
                except OSError:
                    logger.debug(
                        "Failed to cleanup partial upload at %s",
                        target_path,
                        exc_info=True,
                    )
                raise

            return total

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
            else:
                # Builtin ``FileNotFoundError`` is intercepted by
                # ``handle_file_error`` and re-raised as the structured
                # :class:`FileMissingError` (404).
                raise FileNotFoundError(f"Path does not exist: {path}")
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
