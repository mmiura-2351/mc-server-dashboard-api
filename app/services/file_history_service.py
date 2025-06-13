"""
File edit history management service.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import aiofiles
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.exceptions import (
    FileOperationException,
    InvalidRequestException,
    ServerNotFoundException,
)
from app.files.models import FileEditHistory
from app.files.schemas import CleanupResult, FileHistoryRecord
from app.servers.models import Server

logger = logging.getLogger(__name__)


class FileHistoryService:
    """File edit history management service"""

    def __init__(self):
        self.history_base_dir = Path("./file_history")
        self.max_versions_per_file = 50  # Maximum versions per file
        self.auto_cleanup_days = 30  # Auto cleanup after days

    async def create_version_backup(
        self,
        server_id: int,
        file_path: str,
        content: str,
        user_id: Optional[int] = None,
        description: Optional[str] = None,
        db: Session = None,
    ) -> Optional[FileHistoryRecord]:
        """Create backup version of file before editing"""
        try:
            # Normalize file path
            normalized_path = self._normalize_file_path(file_path)

            # Create directory structure
            history_dir = self.history_base_dir / str(server_id) / normalized_path
            history_dir.mkdir(parents=True, exist_ok=True)

            # Calculate content hash for duplicate detection
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Check for duplicate content
            if await self._is_duplicate_content(
                server_id, normalized_path, content_hash, db
            ):
                logger.info(f"Skipping backup for {file_path} - content unchanged")
                return None

            # Get next version number
            version_num = await self._get_next_version_number(
                server_id, normalized_path, db
            )

            # Generate backup filename
            file_extension = Path(normalized_path).suffix
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"v{version_num:03d}_{timestamp}{file_extension}"
            backup_file_path = history_dir / backup_filename

            # Write backup file
            async with aiofiles.open(backup_file_path, "w", encoding="utf-8") as f:
                await f.write(content)

            # Create database record
            file_size = len(content.encode("utf-8"))
            history_record = FileEditHistory(
                server_id=server_id,
                file_path=normalized_path,
                version_number=version_num,
                backup_file_path=str(backup_file_path),
                file_size=file_size,
                content_hash=content_hash,
                editor_user_id=user_id,
                description=description,
            )

            db.add(history_record)
            db.commit()
            db.refresh(history_record)

            # Cleanup excess versions
            await self._cleanup_excess_versions(server_id, normalized_path, db)

            logger.info(f"Created backup version {version_num} for {file_path}")
            return self._to_record_schema(history_record, db)

        except Exception as e:
            logger.error(f"Failed to create backup for {file_path}: {e}")
            raise FileOperationException("backup", file_path, str(e))

    async def get_file_history(
        self,
        server_id: int,
        file_path: str,
        limit: int = 20,
        db: Session = None,
    ) -> List[FileHistoryRecord]:
        """Get edit history for a file"""
        normalized_path = self._normalize_file_path(file_path)

        history_records = (
            db.query(FileEditHistory)
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == normalized_path,
            )
            .order_by(desc(FileEditHistory.version_number))
            .limit(limit)
            .all()
        )

        return [self._to_record_schema(record, db) for record in history_records]

    async def get_version_content(
        self,
        server_id: int,
        file_path: str,
        version_number: int,
        db: Session = None,
    ) -> Tuple[str, FileEditHistory]:
        """Get content of specific version"""
        normalized_path = self._normalize_file_path(file_path)

        history_record = (
            db.query(FileEditHistory)
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == normalized_path,
                FileEditHistory.version_number == version_number,
            )
            .first()
        )

        if not history_record:
            raise InvalidRequestException(
                f"Version {version_number} not found for file {file_path}"
            )

        backup_file_path = Path(history_record.backup_file_path)
        if not backup_file_path.exists():
            raise FileOperationException(
                "read", str(backup_file_path), "Backup file not found"
            )

        try:
            async with aiofiles.open(backup_file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            return content, history_record
        except Exception as e:
            raise FileOperationException("read", str(backup_file_path), str(e))

    async def restore_from_history(
        self,
        server_id: int,
        file_path: str,
        version_number: int,
        user_id: int,
        create_backup_before_restore: bool = True,
        description: Optional[str] = None,
        db: Session = None,
    ) -> Tuple[str, bool]:
        """Restore file from specific version"""
        # Get version content
        content, history_record = await self.get_version_content(
            server_id, file_path, version_number, db
        )

        # Determine actual file path
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise ServerNotFoundException(f"Server {server_id} not found")

        actual_file_path = Path(server.directory_path) / file_path

        backup_created = False
        # Create backup of current content before restore
        if create_backup_before_restore and actual_file_path.exists():
            try:
                async with aiofiles.open(actual_file_path, "r", encoding="utf-8") as f:
                    current_content = await f.read()

                restore_description = f"Backup before restore to version {version_number}"
                if description:
                    restore_description += f": {description}"

                await self.create_version_backup(
                    server_id=server_id,
                    file_path=file_path,
                    content=current_content,
                    user_id=user_id,
                    description=restore_description,
                    db=db,
                )
                backup_created = True
            except Exception as e:
                logger.warning(f"Failed to create backup before restore: {e}")

        # Write restored content
        try:
            actual_file_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(actual_file_path, "w", encoding="utf-8") as f:
                await f.write(content)

            logger.info(f"Restored {file_path} to version {version_number}")
            return content, backup_created

        except Exception as e:
            raise FileOperationException("restore", str(actual_file_path), str(e))

    async def delete_version(
        self,
        server_id: int,
        file_path: str,
        version_number: int,
        db: Session = None,
    ) -> bool:
        """Delete specific version"""
        normalized_path = self._normalize_file_path(file_path)

        history_record = (
            db.query(FileEditHistory)
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == normalized_path,
                FileEditHistory.version_number == version_number,
            )
            .first()
        )

        if not history_record:
            raise InvalidRequestException(
                f"Version {version_number} not found for file {file_path}"
            )

        # Delete backup file
        backup_file_path = Path(history_record.backup_file_path)
        if backup_file_path.exists():
            backup_file_path.unlink()

        # Delete database record
        db.delete(history_record)
        db.commit()

        logger.info(f"Deleted version {version_number} for {file_path}")
        return True

    async def get_server_statistics(self, server_id: int, db: Session = None) -> dict:
        """Get file history statistics for server"""
        stats = (
            db.query(
                func.count(FileEditHistory.id).label("total_versions"),
                func.count(func.distinct(FileEditHistory.file_path)).label("total_files"),
                func.sum(FileEditHistory.file_size).label("total_storage"),
                func.min(FileEditHistory.created_at).label("oldest_version"),
                func.max(FileEditHistory.created_at).label("newest_version"),
            )
            .filter(FileEditHistory.server_id == server_id)
            .first()
        )

        # Most edited file
        most_edited = (
            db.query(
                FileEditHistory.file_path,
                func.count(FileEditHistory.id).label("version_count"),
            )
            .filter(FileEditHistory.server_id == server_id)
            .group_by(FileEditHistory.file_path)
            .order_by(desc("version_count"))
            .first()
        )

        return {
            "server_id": server_id,
            "total_files_with_history": stats.total_files or 0,
            "total_versions": stats.total_versions or 0,
            "total_storage_used": stats.total_storage or 0,
            "oldest_version_date": stats.oldest_version,
            "most_edited_file": most_edited.file_path if most_edited else None,
            "most_edited_file_versions": (
                most_edited.version_count if most_edited else None
            ),
        }

    async def cleanup_old_versions(
        self, days: int = None, server_id: int = None, db: Session = None
    ) -> CleanupResult:
        """Cleanup old versions"""
        if days is None:
            days = self.auto_cleanup_days

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        query = db.query(FileEditHistory).filter(FileEditHistory.created_at < cutoff_date)
        if server_id:
            query = query.filter(FileEditHistory.server_id == server_id)

        old_records = query.all()

        deleted_versions = 0
        freed_storage = 0

        for record in old_records:
            # Delete backup file
            backup_path = Path(record.backup_file_path)
            if backup_path.exists():
                freed_storage += backup_path.stat().st_size
                backup_path.unlink()

            # Delete database record
            db.delete(record)
            deleted_versions += 1

        db.commit()

        logger.info(
            f"Cleaned up {deleted_versions} old versions, freed {freed_storage} bytes"
        )

        return CleanupResult(
            deleted_versions=deleted_versions,
            freed_storage=freed_storage,
            cleanup_type=f"older_than_{days}_days",
        )

    def _normalize_file_path(self, file_path: str) -> str:
        """Normalize file path for consistent storage"""
        # Remove leading slashes and normalize
        return str(Path(file_path.lstrip("/")))

    async def _get_next_version_number(
        self, server_id: int, file_path: str, db: Session
    ) -> int:
        """Get next version number for file"""
        latest_version = (
            db.query(func.max(FileEditHistory.version_number))
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .scalar()
        )

        return (latest_version or 0) + 1

    async def _is_duplicate_content(
        self, server_id: int, file_path: str, content_hash: str, db: Session
    ) -> bool:
        """Check if content is duplicate of latest version"""
        latest_record = (
            db.query(FileEditHistory)
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .order_by(desc(FileEditHistory.version_number))
            .first()
        )

        return latest_record and latest_record.content_hash == content_hash

    async def _cleanup_excess_versions(
        self, server_id: int, file_path: str, db: Session
    ) -> None:
        """Remove excess versions beyond max limit"""
        excess_records = (
            db.query(FileEditHistory)
            .filter(
                FileEditHistory.server_id == server_id,
                FileEditHistory.file_path == file_path,
            )
            .order_by(desc(FileEditHistory.version_number))
            .offset(self.max_versions_per_file)
            .all()
        )

        for record in excess_records:
            # Delete backup file
            backup_path = Path(record.backup_file_path)
            if backup_path.exists():
                backup_path.unlink()

            # Delete database record
            db.delete(record)

        if excess_records:
            db.commit()
            logger.info(
                f"Cleaned up {len(excess_records)} excess versions for {file_path}"
            )

    def _to_record_schema(
        self, record: FileEditHistory, db: Session
    ) -> FileHistoryRecord:
        """Convert database record to schema"""
        editor_username = None
        if record.editor:
            editor_username = record.editor.username

        return FileHistoryRecord(
            id=record.id,
            server_id=record.server_id,
            file_path=record.file_path,
            version_number=record.version_number,
            file_size=record.file_size,
            content_hash=record.content_hash,
            editor_user_id=record.editor_user_id,
            editor_username=editor_username,
            created_at=record.created_at,
            description=record.description,
        )


# Global instance
file_history_service = FileHistoryService()
