"""Backup service (application layer).

Orchestrates backup CRUD, restoration, scheduled-backup creation, and
upload through the `BackupsUnitOfWork`. Depends only on the backups
domain Ports and the minimal cross-domain `ServerReadPort`. Must not
import from `adapters/`, `api/`, FastAPI, or SQLAlchemy.
"""

import logging
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

from app.backups.application.file_service import BackupFileService
from app.backups.application.resource_monitor import ResourceMonitor
from app.backups.domain.entities import (
    BackupEntity,
    BackupListPage,
    BackupListSpec,
    BackupStatistics,
    CreateBackupCommand,
    UpdateBackupFileCommand,
)
from app.backups.domain.ports import BackupsUnitOfWork
from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
    ServerStateException,
)
from app.core.security import SecurityError, TarExtractor
from app.servers.domain.ports import ServerReadPort

# `BackupStatus` / `BackupType` are runtime-required (used as values, not
# just type annotations) — we accept the cross-domain enum import as a
# documented deviation (see `docs/ARCHITECTURE.md` adoption notes). The
# `Server` ORM class is only referenced from type annotations, so it
# stays under TYPE_CHECKING to keep the application layer free of ORM
# imports at runtime.
from app.servers.models import BackupStatus, BackupType

# `minecraft_server_manager` is the legacy module-level singleton; it is
# *called* at runtime (`get_server_status`) so it cannot move under
# TYPE_CHECKING. Cross-domain process-state lookup will move behind a
# Port in a follow-up (#154-9).
from app.services.minecraft_server import minecraft_server_manager

if TYPE_CHECKING:
    from fastapi import UploadFile

    from app.servers.models import Server

logger = logging.getLogger(__name__)


class BackupService:
    """Use cases over the backup catalogue and archive store.

    Receives a `BackupsUnitOfWork`, a `ServerReadPort`, and a
    `backups_directory` via constructor injection. Each public method
    opens a fresh UoW (one transaction) per logical operation; the
    SQLAlchemy adapter shares the underlying session across entries in
    `db=session` mode.

    Authorization / API-only validation (e.g. file_size 500MB ceiling)
    is handled by the router; this service handles persistence-side
    invariants only.
    """

    def __init__(
        self,
        uow: BackupsUnitOfWork,
        server_read: ServerReadPort,
        backups_directory: Path = Path("backups"),
    ):
        self._uow = uow
        self._server_read = server_read
        self.backups_directory = Path(backups_directory)
        self.backups_directory.mkdir(exist_ok=True)
        self._file_service = BackupFileService(self.backups_directory)

    # ===================
    # Helpers
    # ===================

    async def _get_server_or_raise(self, server_id: int) -> "Server":
        """Resolve a server via `ServerReadPort`, raising the legacy
        `ServerNotFoundException` on miss.

        Returns the raw ORM `Server` (built from the entity fields)
        because `BackupFileService` consumes ORM-shaped objects. We use
        a duck-typed shim (`_ServerView`) below to keep us from
        materialising a real ORM row outside the adapter.
        """
        entity = await self._server_read.get(server_id)
        if entity is None:
            raise ServerNotFoundException(str(server_id))
        return _ServerView(
            id=entity.id,
            name=entity.name,
            directory_path=entity.directory_path,
            minecraft_version=entity.minecraft_version,
        )

    def _log_running_server_warning(self, server_id: int) -> None:
        is_running = minecraft_server_manager.get_server_status(server_id)
        if is_running and is_running.value != "stopped":
            logger.warning(f"Creating backup of running server {server_id}")

    # ===================
    # Public use cases
    # ===================

    async def create_backup(
        self,
        server_id: int,
        name: str,
        description: Optional[str] = None,
        backup_type: BackupType = BackupType.manual,
    ) -> BackupEntity:
        """Create a backup row, write the tar.gz, finalise the row.

        Legacy contract preserved: if `uow.commit()` fails after the
        tar.gz has been written, the file is cleaned up but the
        commit-failure window may still leave an orphan archive on
        disk if the unlink itself fails. Tracked by #228 punch-list B
        (orphan-file remediation).
        """
        server = await self._get_server_or_raise(server_id)
        self._log_running_server_warning(server_id)

        backup_entity: Optional[BackupEntity] = None
        backup_path: Optional[Path] = None
        try:
            async with self._uow as uow:
                backup_entity = await uow.backups.add(
                    CreateBackupCommand(
                        server_id=server_id,
                        name=name,
                        description=description,
                        backup_type=backup_type,
                    )
                )

                # File write happens between flush and commit; if the
                # process dies here the row is rolled back when the
                # UoW exits without commit().
                backup_filename = await self._file_service.create_backup_file(
                    server, backup_entity.id, backup_type
                )
                backup_path = self.backups_directory / backup_filename

                final = await uow.backups.update_file_info(
                    backup_entity.id,
                    UpdateBackupFileCommand(
                        file_path=str(backup_path),
                        file_size=backup_path.stat().st_size,
                        status=BackupStatus.completed,
                    ),
                )
                assert final is not None
                await uow.commit()
                backup_entity = final

            logger.info(
                f"Successfully created backup {backup_entity.id} for server {server_id}"
            )
            return backup_entity

        except Exception as e:
            # Best-effort cleanup of orphan archive (legacy parity).
            if backup_path is not None and backup_path.exists():
                try:
                    backup_path.unlink()
                    logger.info(f"Cleaned up orphaned backup file: {backup_path}")
                except Exception as cleanup_error:
                    logger.error(
                        f"Failed to cleanup backup file {backup_path}: {cleanup_error}"
                    )
            logger.error(f"Failed to create backup for server {server_id}: {e}")
            raise

    async def restore_backup(
        self,
        backup_id: int,
        server_id: Optional[int] = None,
    ) -> bool:
        """Restore a backup to its original server (or `server_id`)."""
        async with self._uow as uow:
            backup = await uow.backups.get(backup_id)

        if backup is None:
            raise BackupNotFoundException(str(backup_id))

        if backup.status != BackupStatus.completed:
            raise ServerStateException(
                str(backup.id), backup.status.value, BackupStatus.completed.value
            )

        target_server_id = server_id or backup.server_id
        target_server = await self._get_server_or_raise(target_server_id)

        # Ensure target server is stopped before restoring
        server_status = minecraft_server_manager.get_server_status(target_server_id)
        if server_status and server_status.value != "stopped":
            raise ServerStateException(
                str(target_server_id), server_status.value, "stopped"
            )

        # Synthesise an ORM-shaped Backup for BackupFileService
        backup_orm = _BackupView(
            id=backup.id,
            file_path=backup.file_path,
        )
        await self._file_service.restore_backup_file(backup_orm, target_server)

        logger.info(
            f"Successfully restored backup {backup_id} to server {target_server_id}"
        )
        return True

    async def delete_backup(self, backup_id: int) -> bool:
        """Delete a backup row and its file."""
        async with self._uow as uow:
            backup = await uow.backups.get(backup_id)
        if backup is None:
            raise BackupNotFoundException(str(backup_id))

        # File-first delete: legacy parity (line 859-863).
        self._file_service.delete_backup_file(backup.file_path)

        async with self._uow as uow:
            await uow.backups.delete(backup_id)
            await uow.commit()

        logger.info(f"Successfully deleted backup {backup_id}")
        return True

    async def list_backups(
        self,
        server_id: Optional[int] = None,
        backup_type: Optional[BackupType] = None,
        page: int = 1,
        size: int = 50,
    ) -> BackupListPage:
        spec = BackupListSpec(
            server_id=server_id,
            backup_type=backup_type,
            page=page,
            size=size,
        )
        async with self._uow as uow:
            return await uow.backups.list_paged(spec)

    async def get_backup(self, backup_id: int) -> Optional[BackupEntity]:
        async with self._uow as uow:
            return await uow.backups.get(backup_id)

    async def get_backup_statistics(
        self, server_id: Optional[int] = None
    ) -> BackupStatistics:
        async with self._uow as uow:
            return await uow.backups.get_statistics(server_id=server_id)

    async def create_scheduled_backup(self, server_id: int) -> Optional[BackupEntity]:
        """Create a scheduled backup for a server.

        Returns `None` if the server does not exist (legacy contract:
        scheduler swallows missing-server errors silently).
        """
        try:
            server = await self._server_read.get(server_id)
            if server is None:
                return None
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            backup_name = f"Scheduled backup - {timestamp}"
            return await self.create_backup(
                server_id=server_id,
                name=backup_name,
                description="Automatically created scheduled backup",
                backup_type=BackupType.scheduled,
            )
        except Exception as e:
            logger.error(f"Failed to create scheduled backup for server {server_id}: {e}")
            return None

    async def upload_backup(
        self,
        server_id: int,
        file: "UploadFile",
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> BackupEntity:
        """Persist an uploaded tar.gz as a completed backup.

        Implements the streaming pattern from the legacy code: writes
        to a temp file with chunk-by-chunk size + memory monitoring,
        validates safety, moves into place, then inserts the
        completed-status row in a single UoW commit.
        """
        await self._get_server_or_raise(server_id)

        temp_path: Optional[Path] = None
        backup_path: Optional[Path] = None

        async with ResourceMonitor(max_memory_mb=256) as monitor:
            try:
                if not file.filename.endswith((".tar.gz", ".tgz")):
                    raise FileOperationException(
                        "upload",
                        file.filename,
                        "Only .tar.gz and .tgz files are supported",
                    )

                content_length = file.headers.get("content-length")
                max_size = 500 * 1024 * 1024
                if content_length and int(content_length) > max_size:
                    raise FileOperationException(
                        "upload",
                        file.filename,
                        f"File size ({int(content_length) / (1024 * 1024):.1f}MB) "
                        f"exceeds maximum allowed size (500MB)",
                    )

                if not name:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    name = f"Uploaded backup - {timestamp}"

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"server_{server_id}_{timestamp}.tar.gz"
                backup_path = self.backups_directory / backup_filename

                with tempfile.NamedTemporaryFile(
                    suffix=".tar.gz", delete=False
                ) as temp_file:
                    temp_path = Path(temp_file.name)
                    total_size = 0
                    chunk_count = 0
                    async for chunk in self._read_file_chunks(file):
                        total_size += len(chunk)
                        chunk_count += 1
                        if total_size > max_size:
                            raise FileOperationException(
                                "upload",
                                file.filename,
                                f"File size ({total_size / (1024 * 1024):.1f}MB) "
                                f"exceeds maximum allowed size (500MB)",
                            )
                        temp_file.write(chunk)
                        if chunk_count % 100 == 0:
                            await monitor.check_memory_usage()
                    temp_file.flush()
                    file_size = total_size

                try:
                    with tarfile.open(temp_path, mode="r:gz") as tar:
                        tar.getnames()
                    await monitor.check_memory_usage()
                    TarExtractor.validate_archive_safety(temp_path)
                    logger.info(f"Upload validation passed for {file.filename}")
                except SecurityError as e:
                    raise FileOperationException(
                        "upload",
                        file.filename,
                        f"Security validation failed: {str(e)}",
                    )
                except MemoryError as e:
                    raise FileOperationException(
                        "upload",
                        file.filename,
                        f"Memory limit exceeded during validation: {str(e)}",
                    )
                except Exception as e:
                    raise FileOperationException(
                        "upload",
                        file.filename,
                        f"Invalid tar.gz file: {str(e)}",
                    )

                self.backups_directory.mkdir(exist_ok=True)
                shutil.move(str(temp_path), str(backup_path))
                temp_path = None

                logger.info(f"Uploaded backup file: {backup_path} ({file_size} bytes)")

                async with self._uow as uow:
                    entity = await uow.backups.add(
                        CreateBackupCommand(
                            server_id=server_id,
                            name=name,
                            description=description,
                            backup_type=BackupType.manual,
                            status=BackupStatus.completed,
                            file_path=str(backup_path),
                            file_size=file_size,
                        )
                    )
                    await uow.commit()

                logger.info(f"Created backup record: ID {entity.id}")
                return entity

            except Exception as e:
                logger.error(f"Failed to upload backup for server {server_id}: {e}")
                if temp_path and temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                if backup_path and backup_path.exists():
                    backup_path.unlink(missing_ok=True)
                if isinstance(
                    e,
                    (FileOperationException, DatabaseOperationException, MemoryError),
                ):
                    raise e
                else:
                    raise DatabaseOperationException("upload", "backup", str(e))

    async def _read_file_chunks(
        self, file: "UploadFile", chunk_size: int = 8192
    ) -> AsyncIterator[bytes]:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            yield chunk


# ---------------------------------------------------------------------------
# ORM-shaped views (legacy compatibility for BackupFileService)
# ---------------------------------------------------------------------------


class _ServerView:
    """Duck-typed substitute for `Server` ORM passed to BackupFileService.

    The file service only reads `.id`, `.name`, `.directory_path`, so
    this lightweight namespace is enough — keeps the application
    layer free of ORM concerns.
    """

    __slots__ = ("id", "name", "directory_path", "minecraft_version")

    def __init__(
        self,
        id: int,
        name: str,
        directory_path: str,
        minecraft_version: str,
    ):
        self.id = id
        self.name = name
        self.directory_path = directory_path
        self.minecraft_version = minecraft_version


class _BackupView:
    """Duck-typed substitute for `Backup` ORM passed to BackupFileService."""

    __slots__ = ("id", "file_path")

    def __init__(self, id: int, file_path: str):
        self.id = id
        self.file_path = file_path
