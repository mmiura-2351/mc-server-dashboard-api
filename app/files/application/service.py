"""File edit history service (application layer).

Orchestrates file-version backups, retrieval, restoration, and cleanup
through the `FileHistoryRepository` and `FilesUnitOfWork` Ports plus
the cross-domain `ServerReadPort`. This module depends only on
`domain/` and `app.servers.domain.ports` — it must not import from
`adapters/`, `api/`, or any FastAPI / SQLAlchemy module.
"""

import hashlib
import logging
from datetime import timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import aiofiles

from app.core.datetime_utils import utcnow
from app.core.exceptions import (
    FileOperationException,
    InvalidRequestException,
    ServerNotFoundException,
)
from app.files.domain.entities import (
    CleanupResultEntity,
    CreateHistoryCommand,
    FileHistoryEntity,
    FileHistoryStatsEntity,
)
from app.files.domain.ports import FilesUnitOfWork
from app.servers.domain.ports import ServerReadPort

logger = logging.getLogger(__name__)


class FileHistoryService:
    """Use cases over the file-history catalogue.

    Receives a `FilesUnitOfWork` and a `ServerReadPort` via constructor
    injection. Each public method opens a fresh UoW (one transaction)
    per logical operation; the same `_uow` instance is re-entered
    cleanly because the SQLAlchemy adapter shares the underlying
    session across entries in `db=session` mode (see
    `SqlAlchemyFilesUnitOfWork` for the re-entry semantics).
    """

    def __init__(
        self,
        uow: FilesUnitOfWork,
        server_read: ServerReadPort,
        history_base_dir: Path = Path("./file_history"),
        max_versions_per_file: int = 50,
        auto_cleanup_days: int = 30,
    ):
        self._uow = uow
        self._server_read = server_read
        self.history_base_dir = history_base_dir
        self.max_versions_per_file = max_versions_per_file
        self.auto_cleanup_days = auto_cleanup_days

    # ===================
    # Public use cases
    # ===================

    async def create_version_backup(
        self,
        server_id: int,
        file_path: str,
        content: str,
        user_id: Optional[int] = None,
        description: Optional[str] = None,
    ) -> Optional[FileHistoryEntity]:
        """Create backup version of file before editing.

        Returns the persisted entity, or `None` if the content matches
        the latest version (no backup was created).
        """
        try:
            normalized_path = self._normalize_file_path(file_path)

            history_dir = self.history_base_dir / str(server_id) / normalized_path
            history_dir.mkdir(parents=True, exist_ok=True)

            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            async with self._uow as uow:
                latest = await uow.files_history.get_latest(server_id, normalized_path)
                if latest is not None and latest.content_hash == content_hash:
                    logger.info(f"Skipping backup for {file_path} - content unchanged")
                    return None

                max_version = await uow.files_history.get_max_version_number(
                    server_id, normalized_path
                )
                version_num = max_version + 1

            file_extension = Path(normalized_path).suffix
            timestamp = utcnow().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"v{version_num:03d}_{timestamp}{file_extension}"
            backup_file_path = history_dir / backup_filename

            async with aiofiles.open(backup_file_path, "w", encoding="utf-8") as f:
                await f.write(content)

            file_size = len(content.encode("utf-8"))
            command = CreateHistoryCommand(
                server_id=server_id,
                file_path=normalized_path,
                version_number=version_num,
                backup_file_path=str(backup_file_path),
                file_size=file_size,
                content_hash=content_hash,
                editor_user_id=user_id,
                description=description,
            )

            async with self._uow as uow:
                entity = await uow.files_history.add(command)
                await uow.commit()

            await self._cleanup_excess_versions(server_id, normalized_path)

            logger.info(f"Created backup version {version_num} for {file_path}")
            return entity

        except Exception as e:
            logger.error(f"Failed to create backup for {file_path}: {e}")
            raise FileOperationException("backup", file_path, str(e))

    async def get_file_history(
        self,
        server_id: int,
        file_path: str,
        limit: int = 20,
    ) -> List[FileHistoryEntity]:
        """Get edit history for a file."""
        normalized_path = self._normalize_file_path(file_path)
        async with self._uow as uow:
            return await uow.files_history.get_history_for_file(
                server_id, normalized_path, limit
            )

    async def get_version_content(
        self,
        server_id: int,
        file_path: str,
        version_number: int,
    ) -> Tuple[str, FileHistoryEntity]:
        """Get content of a specific version.

        Returns `(file_content, history_entity)`. Raises
        `InvalidRequestException` if the version is unknown,
        `FileOperationException` if the on-disk backup is missing or
        unreadable.
        """
        normalized_path = self._normalize_file_path(file_path)

        async with self._uow as uow:
            entity = await uow.files_history.get_version(
                server_id, normalized_path, version_number
            )

        if entity is None:
            raise InvalidRequestException(
                f"Version {version_number} not found for file {file_path}"
            )

        backup_file_path = Path(entity.backup_file_path)
        if not backup_file_path.exists():
            raise FileOperationException(
                "read", str(backup_file_path), "Backup file not found"
            )

        try:
            async with aiofiles.open(backup_file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            return content, entity
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
    ) -> Tuple[str, bool]:
        """Restore file from a specific version.

        Returns `(restored_content, backup_was_created)`. Raises
        `ServerNotFoundException` if the target server is unknown,
        `FileOperationException` if the restore write fails.
        """
        content, _ = await self.get_version_content(server_id, file_path, version_number)

        directory_path = await self._server_read.get_directory_path(server_id)
        if directory_path is None:
            raise ServerNotFoundException(f"Server {server_id} not found")

        actual_file_path = Path(directory_path) / file_path

        backup_created = False
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
                )
                backup_created = True
            except Exception as e:
                logger.warning(f"Failed to create backup before restore: {e}")

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
    ) -> bool:
        """Delete a specific version."""
        normalized_path = self._normalize_file_path(file_path)

        async with self._uow as uow:
            entity = await uow.files_history.get_version(
                server_id, normalized_path, version_number
            )
            if entity is None:
                raise InvalidRequestException(
                    f"Version {version_number} not found for file {file_path}"
                )

            backup_file_path = Path(entity.backup_file_path)
            if backup_file_path.exists():
                backup_file_path.unlink()

            assert entity.id is not None
            await uow.files_history.delete_by_id(entity.id)
            await uow.commit()

        logger.info(f"Deleted version {version_number} for {file_path}")
        return True

    async def get_server_statistics(self, server_id: int) -> FileHistoryStatsEntity:
        """Get file-history statistics for a server."""
        async with self._uow as uow:
            return await uow.files_history.get_server_statistics(server_id)

    async def cleanup_old_versions(
        self,
        days: Optional[int] = None,
        server_id: Optional[int] = None,
    ) -> CleanupResultEntity:
        """Remove versions older than `days` (defaulting to the
        configured auto-cleanup window).
        """
        if days is None:
            days = self.auto_cleanup_days

        # Use naive UTC to match the `FileEditHistory.created_at`
        # column (declared `DateTime`, not `DateTime(timezone=True)`).
        cutoff_date = utcnow() - timedelta(days=days)

        deleted_versions = 0
        freed_storage = 0

        async with self._uow as uow:
            old_records = await uow.files_history.get_versions_older_than(
                cutoff_date, server_id
            )

            for record in old_records:
                backup_path = Path(record.backup_file_path)
                if backup_path.exists():
                    freed_storage += backup_path.stat().st_size
                    backup_path.unlink()

                assert record.id is not None
                await uow.files_history.delete_by_id(record.id)
                deleted_versions += 1

            if deleted_versions > 0:
                await uow.commit()

        logger.info(
            f"Cleaned up {deleted_versions} old versions, freed {freed_storage} bytes"
        )

        return CleanupResultEntity(
            deleted_versions=deleted_versions,
            freed_storage=freed_storage,
            cleanup_type=f"older_than_{days}_days",
        )

    # ===================
    # Internal helpers
    # ===================

    def _normalize_file_path(self, file_path: str) -> str:
        """Normalize file path for consistent storage."""
        return str(Path(file_path.lstrip("/")))

    async def _cleanup_excess_versions(self, server_id: int, file_path: str) -> None:
        """Remove excess versions beyond the configured max limit."""
        async with self._uow as uow:
            excess = await uow.files_history.get_excess_versions(
                server_id, file_path, self.max_versions_per_file
            )

            for record in excess:
                backup_path = Path(record.backup_file_path)
                if backup_path.exists():
                    backup_path.unlink()

                assert record.id is not None
                await uow.files_history.delete_by_id(record.id)

            if excess:
                await uow.commit()
                logger.info(f"Cleaned up {len(excess)} excess versions for {file_path}")
