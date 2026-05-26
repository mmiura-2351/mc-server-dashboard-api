from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidRequestException
from app.files.application.file_info import FileInfoService
from app.files.application.path_validation import FileValidationService


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
        db: Session,
        search_in_content: bool = False,
        file_type: Optional[str] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Search for files by name and optionally content

        Args:
            server_id: ID of the server to search in
            search_term: Term to search for in filenames and/or content
            search_in_content: Whether to search inside file contents
            file_type: Optional file type filter
            max_results: Maximum number of results to return
            db: Database session (required for security validation)

        Returns:
            Dictionary containing search results and metadata
        """
        # Validate database session for security-critical operations
        if db is None:
            raise InvalidRequestException(
                "Database session is required for file search operations"
            )

        # Validate server
        server = await self.validation_service.validate_server_exists(server_id, db)
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
        results: list[dict[str, Any]] = []

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
        results: list[dict[str, Any]] = []

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
