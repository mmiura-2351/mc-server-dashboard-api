"""Backup tar.gz file operations (application-layer helper).

Migrated verbatim from `app.services.backup_service.BackupFileService`
so the legacy behaviour (chunked async tar creation, large-file
streaming, secure extraction via `TarExtractor`) is preserved during
the strangler refactor. Lives in `application/` (not `adapters/`)
because it is an in-process file-IO helper, not an external
infrastructure boundary.
"""

import asyncio
import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

from app.backups.models import Backup, BackupType
from app.core.exceptions import FileOperationException, handle_file_error
from app.core.security import SecurityError, TarExtractor
from app.servers.models import Server

logger = logging.getLogger(__name__)


class BackupFileService:
    """Tar.gz creation, restoration, and on-disk deletion for backups.

    Pure file IO — does not touch the database.
    """

    def __init__(self, backups_directory: Path):
        self.backups_directory = backups_directory

    async def create_backup_file(
        self,
        server: Server,
        backup_id: int,
        backup_type: BackupType,
        progress_callback=None,
    ) -> str:
        """Create the actual backup file (tar.gz).

        Writes directly to the final path. Prefer
        :meth:`write_backup_file_to` (atomic-rename caller pattern) for
        new callers that must avoid orphan files on DB-commit failure.
        """
        try:
            server_dir = Path(server.directory_path)
            if not server_dir.exists():
                raise FileOperationException(
                    "backup", str(server_dir), "Server directory not found"
                )

            backup_filename = self._generate_backup_filename(server.id, backup_id)
            backup_path = self.backups_directory / backup_filename

            await self._create_tar_backup_async(
                server_dir, backup_path, progress_callback
            )

            logger.info(f"Created backup file: {backup_filename}")
            return backup_filename

        except Exception as e:
            handle_file_error("create backup", str(server_dir), e)

    async def write_backup_file_to(
        self,
        server: Server,
        target_path: Path,
        progress_callback=None,
    ) -> None:
        """Write a backup tar.gz to an explicit target path.

        Caller-controlled destination (typically a `.pending-*.tar.gz`
        temp file). Use this with `os.replace()` to implement the
        atomic-rename pattern: write to temp → DB commit → rename
        final. On DB-commit failure the caller deletes the temp file,
        guaranteeing no orphan archive ends up in the canonical
        backups directory.
        """
        server_dir = Path(server.directory_path)
        if not server_dir.exists():
            raise FileOperationException(
                "backup", str(server_dir), "Server directory not found"
            )

        try:
            await self._create_tar_backup_async(
                server_dir, target_path, progress_callback
            )
        except Exception as e:
            handle_file_error("create backup", str(server_dir), e)

    def _generate_backup_filename(self, server_id: int, backup_id: int) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"backup_{server_id}_{backup_id}_{timestamp}.tar.gz"

    async def _create_tar_backup_async(
        self, server_dir: Path, backup_path: Path, progress_callback=None
    ) -> None:
        await self._create_tar_backup_chunked(server_dir, backup_path, progress_callback)

    async def _calculate_directory_size_async(self, directory: Path) -> tuple[int, int]:
        """Calculate directory size and file count without blocking event loop."""
        total_files = 0
        total_size = 0

        def get_file_info(path: Path) -> tuple[int, int]:
            try:
                if path.is_file():
                    return 1, path.stat().st_size
                return 0, 0
            except OSError:
                return 0, 0

        paths = list(directory.rglob("*"))
        batch_size = 100
        for i in range(0, len(paths), batch_size):
            batch = paths[i : i + batch_size]
            loop = asyncio.get_event_loop()
            tasks = [loop.run_in_executor(None, get_file_info, path) for path in batch]
            results = await asyncio.gather(*tasks)
            for file_count, file_size in results:
                total_files += file_count
                total_size += file_size
            await asyncio.sleep(0)

        return total_files, total_size

    async def _create_tar_backup_chunked(
        self, server_dir: Path, backup_path: Path, progress_callback=None
    ) -> None:
        from app.core.concurrency import get_semaphores

        async with get_semaphores().file_io:
            total_files, total_size = await self._calculate_directory_size_async(
                server_dir
            )
            logger.info(
                f"Starting backup of {total_files} files "
                f"({total_size / (1024 * 1024):.1f}MB) from {server_dir}"
            )

            if progress_callback:
                progress_callback(0, total_files, 0, total_size)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._create_tar_archive_sync,
                server_dir,
                backup_path,
                total_files,
                total_size,
                progress_callback,
            )

            logger.info(
                f"Backup creation completed for {total_files} files "
                f"({total_size / (1024 * 1024):.1f}MB)"
            )

    def _create_tar_archive_sync(
        self,
        server_dir: Path,
        backup_path: Path,
        total_files: int,
        total_size: int,
        progress_callback=None,
    ) -> None:
        processed_files = 0
        processed_size = 0
        with tarfile.open(backup_path, "w:gz") as tar:
            for item in server_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(server_dir)
                    file_size = item.stat().st_size
                    try:
                        if file_size > 100 * 1024 * 1024:
                            logger.debug(
                                f"Processing large file: {item} "
                                f"({file_size / (1024 * 1024):.1f}MB)"
                            )
                            self._add_large_file_to_tar_chunked(tar, item, arcname)
                        else:
                            tar.add(item, arcname=arcname)
                        processed_files += 1
                        processed_size += file_size
                        if processed_files % 100 == 0 or file_size > 50 * 1024 * 1024:
                            if progress_callback:
                                progress_callback(
                                    processed_files,
                                    total_files,
                                    processed_size,
                                    total_size,
                                )
                    except Exception as e:
                        logger.warning(f"Failed to add file {item} to backup: {e}")
                        continue
        if progress_callback:
            progress_callback(processed_files, total_files, processed_size, total_size)

    def _add_large_file_to_tar_chunked(
        self, tar: tarfile.TarFile, file_path: Path, arcname
    ) -> None:
        try:
            tarinfo = tar.gettarinfo(file_path, arcname)
            tar.addfile(tarinfo)
            chunk_size = 64 * 1024
            bytes_written = 0
            with open(file_path, "rb") as source_file:
                while bytes_written < tarinfo.size:
                    remaining = tarinfo.size - bytes_written
                    chunk = source_file.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    tar.fileobj.write(chunk)
                    bytes_written += len(chunk)
            blocks_written = (tarinfo.size + 511) // 512
            padding_needed = (blocks_written * 512) - tarinfo.size
            if padding_needed > 0:
                tar.fileobj.write(b"\0" * padding_needed)
        except Exception as e:
            logger.warning(f"Failed to add large file {file_path} to backup: {e}")
            tar.add(file_path, arcname=arcname)

    async def restore_backup_file(self, backup: Backup, target_server: Server) -> None:
        from app.core.concurrency import get_semaphores

        async with get_semaphores().file_io:
            try:
                backup_path = Path(backup.file_path)
                if not backup_path.exists():
                    raise FileOperationException(
                        "restore",
                        str(backup_path),
                        "Backup file not found",
                    )

                target_dir = Path(target_server.directory_path)
                self._backup_current_server_state(target_dir)
                self._extract_backup_to_directory(backup_path, target_dir)

                logger.info(f"Extracted backup to: {target_dir}")
            except Exception as e:
                handle_file_error("restore backup", str(backup_path), e)

    def _backup_current_server_state(self, target_dir: Path) -> None:
        if target_dir.exists():
            backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_backup_dir = (
                target_dir.parent / f"{target_dir.name}_backup_{backup_timestamp}"
            )
            shutil.move(str(target_dir), str(temp_backup_dir))
            logger.info(f"Created temporary backup of current state: {temp_backup_dir}")

    def _extract_backup_to_directory(self, backup_path: Path, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(backup_path, "r:gz") as tar:
            members = tar.getmembers()
            total_members = len(members)
            processed = 0
            logger.info(
                f"Starting secure extraction of {total_members} files to {target_dir}"
            )
            for member in members:
                try:
                    TarExtractor.safe_extract_tar_member(tar, member, target_dir)
                    processed += 1
                except SecurityError as e:
                    logger.error(
                        f"Security violation during extraction of {member.name}: {e}"
                    )
                    raise FileOperationException(
                        "extract_backup",
                        str(backup_path),
                        f"Security violation: {e}",
                    )
                except Exception as e:
                    logger.warning(f"Failed to extract {member.name}: {e}")
                    continue
            logger.info(
                f"Secure extraction completed: {processed}/{total_members} files extracted"
            )

    def delete_backup_file(self, backup_path: str) -> None:
        backup_file = Path(backup_path)
        if backup_file.exists():
            backup_file.unlink()
            logger.info(f"Deleted backup file: {backup_file}")
