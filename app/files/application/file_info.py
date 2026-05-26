from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from app.core.exceptions import handle_file_error
from app.files.application.path_validation import FileValidationService


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
