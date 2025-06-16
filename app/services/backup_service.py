import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from fastapi import UploadFile

from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
    ServerStateException,
    handle_database_error,
    handle_file_error,
)
from app.core.security import SecurityError, TarExtractor
from app.servers.models import Backup, BackupStatus, BackupType, Server
from app.services.minecraft_server import minecraft_server_manager

logger = logging.getLogger(__name__)


class BackupValidationService:
    """Service for validating backup operations.

    This service handles all validation logic for backup operations including
    server existence, backup availability, and state checks.
    """

    @staticmethod
    def validate_server_for_backup(
        server_id: Annotated[int, "ID of the server to validate"],
        db: Annotated[Session, "Database session for queries"],
    ) -> Annotated[Server, "Validated server instance"]:
        """Validate that a server exists and can be backed up.

        Args:
            server_id: The ID of the server to validate
            db: Database session for querying

        Returns:
            Server instance if validation passes

        Raises:
            ServerNotFoundException: If server doesn't exist or is deleted
        """
        server = (
            db.query(Server)
            .filter(and_(Server.id == server_id, Server.is_deleted.is_(False)))
            .first()
        )

        if not server:
            raise ServerNotFoundException(str(server_id))

        return server

    @staticmethod
    def validate_backup_exists(
        backup_id: Annotated[int, "ID of the backup to validate"],
        db: Annotated[Session, "Database session for queries"],
    ) -> Annotated[Backup, "Validated backup instance"]:
        """Validate that a backup exists in the database.

        Args:
            backup_id: The ID of the backup to validate
            db: Database session for querying

        Returns:
            Backup instance if validation passes

        Raises:
            BackupNotFoundException: If backup doesn't exist
        """
        backup = db.query(Backup).filter(Backup.id == backup_id).first()

        if not backup:
            raise BackupNotFoundException(str(backup_id))

        return backup

    @staticmethod
    def validate_backup_status_for_restore(backup: Backup) -> None:
        """Validate backup can be restored"""
        if backup.status != BackupStatus.completed:
            raise ServerStateException(
                str(backup.id), backup.status.value, BackupStatus.completed.value
            )

    @staticmethod
    def validate_server_stopped_for_restore(server_id: int) -> None:
        """Validate server is stopped for safe restoration"""
        server_status = minecraft_server_manager.get_server_status(server_id)
        if server_status and server_status.value != "stopped":
            raise ServerStateException(str(server_id), server_status.value, "stopped")


class BackupFileService:
    """Service for handling backup file operations"""

    def __init__(self, backups_directory: Path):
        self.backups_directory = backups_directory

    async def create_backup_file(
        self,
        server: Server,
        backup_id: int,
        backup_type: BackupType,
        progress_callback=None,
    ) -> str:
        """Create the actual backup file (tar.gz)"""
        try:
            server_dir = Path(server.directory_path)
            if not server_dir.exists():
                raise FileOperationException(
                    "backup", str(server_dir), "Server directory not found"
                )

            backup_filename = self._generate_backup_filename(server.id, backup_id)
            backup_path = self.backups_directory / backup_filename

            # Use async backup creation for better performance
            await self._create_tar_backup_async(
                server_dir, backup_path, progress_callback
            )

            logger.info(f"Created backup file: {backup_filename}")
            return backup_filename

        except Exception as e:
            handle_file_error("create backup", str(server_dir), e)

    def _generate_backup_filename(self, server_id: int, backup_id: int) -> str:
        """Generate unique backup filename"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"backup_{server_id}_{backup_id}_{timestamp}.tar.gz"

    async def _create_tar_backup_async(
        self, server_dir: Path, backup_path: Path, progress_callback=None
    ) -> None:
        """Create tar.gz backup asynchronously with chunked processing"""
        import asyncio

        # Run the blocking tar creation in a thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._create_tar_backup_chunked,
            server_dir,
            backup_path,
            progress_callback,
        )

    def _create_tar_backup_chunked(
        self, server_dir: Path, backup_path: Path, progress_callback=None
    ) -> None:
        """Create tar.gz backup with chunked processing for large files"""
        total_files = 0
        processed_files = 0
        total_size = 0
        processed_size = 0

        # Count total files and calculate total size for progress tracking
        for item in server_dir.rglob("*"):
            if item.is_file():
                total_files += 1
                total_size += item.stat().st_size

        logger.info(
            f"Starting backup of {total_files} files ({total_size / (1024*1024):.1f}MB) from {server_dir}"
        )

        if progress_callback:
            progress_callback(0, total_files, 0, total_size)

        with tarfile.open(backup_path, "w:gz") as tar:
            for item in server_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(server_dir)
                    file_size = item.stat().st_size

                    try:
                        # Use streaming backup for large files (>100MB)
                        if file_size > 100 * 1024 * 1024:
                            logger.debug(
                                f"Processing large file: {item} ({file_size / (1024*1024):.1f}MB)"
                            )
                            self._add_large_file_to_tar_chunked(tar, item, arcname)
                        else:
                            tar.add(item, arcname=arcname)

                        processed_files += 1
                        processed_size += file_size

                        # Report progress every 100 files or for large files
                        if processed_files % 100 == 0 or file_size > 50 * 1024 * 1024:
                            progress = (processed_files / total_files) * 100
                            size_progress = (processed_size / total_size) * 100
                            logger.info(
                                f"Backup progress: {processed_files}/{total_files} files ({progress:.1f}%), {processed_size / (1024*1024):.1f}/{total_size / (1024*1024):.1f}MB ({size_progress:.1f}%)"
                            )

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

        logger.info(
            f"Backup completed: {processed_files}/{total_files} files processed ({processed_size / (1024*1024):.1f}MB)"
        )

        if progress_callback:
            progress_callback(processed_files, total_files, processed_size, total_size)

    def _create_tar_backup(self, server_dir: Path, backup_path: Path) -> None:
        """Create tar.gz backup of server directory with streaming for large files"""
        with tarfile.open(backup_path, "w:gz") as tar:
            for item in server_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(server_dir)
                    # Use streaming backup for large files (>100MB)
                    if item.stat().st_size > 100 * 1024 * 1024:
                        self._add_large_file_to_tar(tar, item, arcname)
                    else:
                        tar.add(item, arcname=arcname)

    def _add_large_file_to_tar_chunked(
        self, tar: tarfile.TarFile, file_path: Path, arcname: Path
    ) -> None:
        """Add large file to tar using chunked streaming to reduce memory usage"""
        try:
            # Get file info for tar header
            tarinfo = tar.gettarinfo(file_path, arcname)

            # Add file header first
            tar.addfile(tarinfo)

            # Stream file content in larger chunks for better performance
            chunk_size = 64 * 1024  # 64KB chunks for better I/O performance
            bytes_written = 0

            with open(file_path, "rb") as source_file:
                while bytes_written < tarinfo.size:
                    remaining = tarinfo.size - bytes_written
                    chunk_size_to_read = min(chunk_size, remaining)

                    chunk = source_file.read(chunk_size_to_read)
                    if not chunk:
                        break

                    tar.fileobj.write(chunk)
                    bytes_written += len(chunk)

            # Ensure proper padding for tar format
            blocks_written = (tarinfo.size + 511) // 512
            padding_needed = (blocks_written * 512) - tarinfo.size
            if padding_needed > 0:
                tar.fileobj.write(b"\0" * padding_needed)

        except Exception as e:
            logger.warning(f"Failed to add large file {file_path} to backup: {e}")
            # Fallback to regular add for problematic files
            tar.add(file_path, arcname=arcname)

    def _add_large_file_to_tar(
        self, tar: tarfile.TarFile, file_path: Path, arcname: Path
    ) -> None:
        """Add large file to tar using streaming to reduce memory usage"""
        try:
            # Get file info for tar header
            tarinfo = tar.gettarinfo(file_path, arcname)

            # Add file header first
            tar.addfile(tarinfo)

            # Stream file content in chunks
            with open(file_path, "rb") as source_file:
                while True:
                    chunk = source_file.read(8192)  # 8KB chunks
                    if not chunk:
                        break
                    tar.fileobj.write(chunk)

            # Ensure proper padding for tar format
            blocks_written = (tarinfo.size + 511) // 512
            padding_needed = (blocks_written * 512) - tarinfo.size
            if padding_needed > 0:
                tar.fileobj.write(b"\0" * padding_needed)

        except Exception as e:
            logger.warning(f"Failed to add large file {file_path} to backup: {e}")
            # Fallback to regular add for problematic files
            tar.add(file_path, arcname=arcname)

    async def restore_backup_file(self, backup: Backup, target_server: Server) -> None:
        """Restore the backup file to target server directory"""
        try:
            backup_path = Path(backup.file_path)
            if not backup_path.exists():
                raise FileOperationException(
                    "restore", str(backup_path), "Backup file not found"
                )

            target_dir = Path(target_server.directory_path)

            self._backup_current_server_state(target_dir)
            self._extract_backup_to_directory(backup_path, target_dir)

            logger.info(f"Extracted backup to: {target_dir}")

        except Exception as e:
            handle_file_error("restore backup", str(backup_path), e)

    def _backup_current_server_state(self, target_dir: Path) -> None:
        """Create backup of current server state before restoration"""
        if target_dir.exists():
            backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_backup_dir = (
                target_dir.parent / f"{target_dir.name}_backup_{backup_timestamp}"
            )
            shutil.move(str(target_dir), str(temp_backup_dir))
            logger.info(f"Created temporary backup of current state: {temp_backup_dir}")

    def _extract_backup_to_directory(self, backup_path: Path, target_dir: Path) -> None:
        """Extract backup archive to target directory with security validation and memory optimization"""
        target_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(backup_path, "r:gz") as tar:
            # Extract files one by one with security validation
            members = tar.getmembers()
            total_members = len(members)
            processed = 0

            logger.info(
                f"Starting secure extraction of {total_members} files to {target_dir}"
            )

            for member in members:
                try:
                    # Use secure extraction with validation
                    TarExtractor.safe_extract_tar_member(tar, member, target_dir)
                    processed += 1

                    # Log progress every 100 files
                    if processed % 100 == 0:
                        progress = (processed / total_members) * 100
                        logger.info(
                            f"Extraction progress: {processed}/{total_members} files ({progress:.1f}%)"
                        )

                except SecurityError as e:
                    logger.error(
                        f"Security violation during extraction of {member.name}: {e}"
                    )
                    raise FileOperationException(
                        "extract_backup", str(backup_path), f"Security violation: {e}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to extract {member.name}: {e}")
                    continue

            logger.info(
                f"Secure extraction completed: {processed}/{total_members} files extracted"
            )

    def delete_backup_file(self, backup_path: str) -> None:
        """Delete backup file from filesystem"""
        backup_file = Path(backup_path)
        if backup_file.exists():
            backup_file.unlink()
            logger.info(f"Deleted backup file: {backup_file}")


class BackupDatabaseService:
    """Service for database operations related to backups"""

    def create_backup_record(
        self,
        server_id: int,
        name: str,
        description: Optional[str],
        backup_type: BackupType,
        db: Session,
    ) -> Backup:
        """Create initial backup record in database"""
        try:
            backup = Backup(
                server_id=server_id,
                name=name,
                description=description,
                file_path="",
                file_size=0,
                backup_type=backup_type,
                status=BackupStatus.creating,
            )

            db.add(backup)
            db.flush()
            return backup

        except Exception as e:
            handle_database_error("create", "backup", e)

    def update_backup_with_file_info(
        self, backup: Backup, file_path: str, file_size: int, db: Session
    ) -> None:
        """Update backup record with file information"""
        try:
            backup.file_path = file_path
            backup.file_size = file_size
            backup.status = BackupStatus.completed

            db.commit()
            db.refresh(backup)

        except Exception as e:
            handle_database_error("update", "backup", e)

    def mark_backup_failed(self, backup: Backup, db: Session) -> None:
        """Mark backup as failed"""
        try:
            backup.status = BackupStatus.failed
            db.commit()

        except Exception as e:
            handle_database_error("update", "backup", e)

    def delete_backup_record(self, backup: Backup, db: Session) -> None:
        """Delete backup record from database"""
        try:
            db.delete(backup)
            db.commit()

        except Exception as e:
            handle_database_error("delete", "backup", e)


class BackupService:
    """Main service for orchestrating backup operations"""

    def __init__(self):
        self.backups_directory = Path("backups")
        self.backups_directory.mkdir(exist_ok=True)

        self.validation_service = BackupValidationService()
        self.file_service = BackupFileService(self.backups_directory)
        self.db_service = BackupDatabaseService()

    async def create_backup(
        self,
        server_id: Annotated[int, "ID of the server to backup"],
        name: Annotated[str, "Name for the backup"],
        description: Annotated[
            Optional[str], "Optional description for the backup"
        ] = None,
        backup_type: Annotated[
            BackupType, "Type of backup (manual/scheduled)"
        ] = BackupType.manual,
        db: Annotated[Session, "Database session"] = None,
    ) -> Annotated[Backup, "Created backup instance"]:
        """Create a comprehensive backup of a server.

        This method validates the server, creates backup records, performs the actual
        file backup operation, and updates the database with the results.

        Args:
            server_id: The ID of the server to backup
            name: Human-readable name for the backup
            description: Optional description of the backup purpose
            backup_type: Type of backup (manual, scheduled, etc.)
            db: Database session for operations

        Returns:
            The created backup instance with complete metadata

        Raises:
            ServerNotFoundException: If server doesn't exist
            FileOperationException: If backup creation fails
        """
        # Validate server
        server = self.validation_service.validate_server_for_backup(server_id, db)

        # Log warning if server is running
        self._log_running_server_warning(server_id)

        # Create backup record
        backup = self.db_service.create_backup_record(
            server_id, name, description, backup_type, db
        )

        try:
            # Create backup file
            backup_filename = await self.file_service.create_backup_file(
                server, backup.id, backup_type
            )
            backup_path = self.backups_directory / backup_filename

            # Update backup record with file information
            self.db_service.update_backup_with_file_info(
                backup, str(backup_path), backup_path.stat().st_size, db
            )

            logger.info(
                f"Successfully created backup {backup.id} for server {server_id}: {backup_filename}"
            )
            return backup

        except Exception as e:
            self.db_service.mark_backup_failed(backup, db)
            logger.error(f"Failed to create backup for server {server_id}: {e}")
            raise

    def _log_running_server_warning(self, server_id: int) -> None:
        """Log warning if server is running during backup"""
        is_running = minecraft_server_manager.get_server_status(server_id)
        if is_running and is_running.value != "stopped":
            logger.warning(f"Creating backup of running server {server_id}")

    async def restore_backup(
        self, backup_id: int, server_id: Optional[int] = None, db: Session = None
    ) -> bool:
        """Restore a backup to a server"""
        # Validate backup exists and can be restored
        backup = self.validation_service.validate_backup_exists(backup_id, db)
        self.validation_service.validate_backup_status_for_restore(backup)

        # Determine and validate target server
        target_server_id = server_id or backup.server_id
        target_server = self.validation_service.validate_server_for_backup(
            target_server_id, db
        )

        # Ensure server is stopped for safe restoration
        self.validation_service.validate_server_stopped_for_restore(target_server_id)

        # Restore backup file
        await self.file_service.restore_backup_file(backup, target_server)

        logger.info(
            f"Successfully restored backup {backup_id} to server {target_server_id}"
        )
        return True

    async def restore_backup_and_create_template(
        self,
        backup_id: int,
        template_name: str,
        template_description: Optional[str] = None,
        is_public: bool = False,
        user=None,
        server_id: Optional[int] = None,
        db: Session = None,
    ) -> dict:
        """Restore a backup and optionally create a template from the restored server"""
        # First restore the backup
        success = await self.restore_backup(backup_id, server_id, db)

        if not success:
            raise FileOperationException(
                "restore", f"backup {backup_id}", "Failed to restore backup"
            )

        result = {"backup_restored": True, "template_created": False}

        # If template name is provided, create template from restored server
        if template_name:
            from app.services.template_service import TemplateService

            # Get the target server
            backup = self.validation_service.validate_backup_exists(backup_id, db)
            target_server_id = server_id or backup.server_id

            template_service = TemplateService()
            template = await template_service.create_template_from_server(
                server_id=target_server_id,
                name=template_name,
                description=template_description
                or f"Template created from backup {backup.name}",
                is_public=is_public,
                creator=user,
                db=db,
            )

            result["template_created"] = True
            result["template_id"] = template.id
            result["template_name"] = template.name

            logger.info(
                f"Successfully created template {template.id} from restored backup {backup_id}"
            )

        return result

    async def create_scheduled_backups(self, server_ids: list[int], db: Session) -> dict:
        """Create backups for multiple servers"""
        results = {
            "successful": [],
            "failed": [],
            "total_servers": len(server_ids),
            "success_count": 0,
            "error_count": 0,
        }

        # Optimize: Get all servers in a single query instead of individual lookups
        valid_servers = (
            db.query(Server)
            .filter(and_(Server.id.in_(server_ids), Server.is_deleted.is_(False)))
            .all()
        )

        valid_server_ids = {server.id for server in valid_servers}
        server_lookup = {server.id: server for server in valid_servers}

        # Track invalid server IDs
        invalid_server_ids = set(server_ids) - valid_server_ids
        for server_id in invalid_server_ids:
            results["failed"].append(
                {"server_id": server_id, "error": f"Server {server_id} not found"}
            )
            results["error_count"] += 1

        for server_id in valid_server_ids:
            try:
                server = server_lookup[server_id]

                # Create backup with automatic naming
                backup_name = (
                    f"Scheduled backup {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                )
                backup = await self.create_backup(
                    server_id=server_id,
                    name=backup_name,
                    description="Automatically scheduled backup",
                    backup_type=BackupType.scheduled,
                    db=db,
                )

                results["successful"].append(
                    {
                        "server_id": server_id,
                        "server_name": server.name,
                        "backup_id": backup.id,
                        "backup_name": backup.name,
                    }
                )
                results["success_count"] += 1

            except Exception as e:
                results["failed"].append({"server_id": server_id, "error": str(e)})
                results["error_count"] += 1
                logger.error(
                    f"Failed to create scheduled backup for server {server_id}: {e}"
                )

        logger.info(
            f"Scheduled backup batch completed: {results['success_count']} success, "
            f"{results['error_count']} failed"
        )
        return results

    async def delete_backup(self, backup_id: int, db: Session) -> bool:
        """Delete a backup and its file"""
        # Validate backup exists
        backup = self.validation_service.validate_backup_exists(backup_id, db)

        # Delete backup file
        self.file_service.delete_backup_file(backup.file_path)

        # Delete database record
        self.db_service.delete_backup_record(backup, db)

        logger.info(f"Successfully deleted backup {backup_id}")
        return True

    def list_backups(
        self,
        server_id: Optional[int] = None,
        backup_type: Optional[BackupType] = None,
        page: int = 1,
        size: int = 50,
        db: Session = None,
    ) -> dict:
        """List backups with filtering and pagination"""
        try:
            query = db.query(Backup)

            if server_id:
                query = query.filter(Backup.server_id == server_id)

            if backup_type:
                query = query.filter(Backup.backup_type == backup_type)

            # Order by creation date (newest first)
            query = query.order_by(Backup.created_at.desc())

            total = query.count()
            backups = query.offset((page - 1) * size).limit(size).all()

            return {
                "backups": backups,
                "total": total,
                "page": page,
                "size": size,
            }

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            raise DatabaseOperationException("list", "backups", str(e))

    def get_backup(self, backup_id: int, db: Session) -> Optional[Backup]:
        """Get backup by ID"""
        try:
            return db.query(Backup).filter(Backup.id == backup_id).first()

        except Exception as e:
            logger.error(f"Failed to get backup {backup_id}: {e}")
            raise DatabaseOperationException("get", "backup", str(e))

    async def create_scheduled_backup(
        self, server_id: int, db: Session
    ) -> Optional[Backup]:
        """Create a scheduled backup for a server"""
        try:
            server = (
                db.query(Server)
                .filter(and_(Server.id == server_id, Server.is_deleted.is_(False)))
                .first()
            )

            if not server:
                return None

            # Generate scheduled backup name
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            backup_name = f"Scheduled backup - {timestamp}"

            return await self.create_backup(
                server_id=server_id,
                name=backup_name,
                description="Automatically created scheduled backup",
                backup_type=BackupType.scheduled,
                db=db,
            )

        except Exception as e:
            logger.error(f"Failed to create scheduled backup for server {server_id}: {e}")
            return None

    def get_backup_statistics(
        self, server_id: Optional[int] = None, db: Session = None
    ) -> dict:
        """Get backup statistics"""
        try:
            query = db.query(Backup)

            if server_id:
                query = query.filter(Backup.server_id == server_id)

            total_backups = query.count()
            completed_backups = query.filter(
                Backup.status == BackupStatus.completed
            ).count()
            failed_backups = query.filter(Backup.status == BackupStatus.failed).count()

            # Calculate total backup size using SQL aggregation instead of loading all records
            from sqlalchemy import func

            size_query = db.query(func.sum(Backup.file_size)).filter(
                Backup.status == BackupStatus.completed
            )

            if server_id:
                size_query = size_query.filter(Backup.server_id == server_id)

            total_size_result = size_query.scalar()
            total_size = total_size_result or 0

            return {
                "total_backups": total_backups,
                "completed_backups": completed_backups,
                "failed_backups": failed_backups,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
            }

        except Exception as e:
            logger.error(f"Failed to get backup statistics: {e}")
            raise DatabaseOperationException("get statistics", "backups", str(e))

    async def upload_backup(
        self,
        server_id: int,
        file: "UploadFile",
        name: Optional[str] = None,
        description: Optional[str] = None,
        db: Session = None,
    ) -> Backup:
        """Upload a backup file and create backup record"""
        try:
            # Validate server exists
            server = BackupValidationService.validate_server_for_backup(server_id, db)

            # Validate file is a valid tar.gz file
            if not file.filename.endswith((".tar.gz", ".tgz")):
                raise FileOperationException(
                    "upload", file.filename, "Only .tar.gz and .tgz files are supported"
                )

            # Generate backup name if not provided
            if not name:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                name = f"Uploaded backup - {timestamp}"

            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"server_{server_id}_{timestamp}.tar.gz"
            backup_path = self.backups_directory / backup_filename

            # Read file content
            content = await file.read()
            file_size = len(content)

            # Validate file size (max 500MB)
            max_size = 500 * 1024 * 1024  # 500MB
            if file_size > max_size:
                raise FileOperationException(
                    "upload",
                    file.filename,
                    f"File size ({file_size / (1024*1024):.1f}MB) exceeds maximum allowed size (500MB)",
                )

            # Validate content is a safe and valid tar.gz file
            import io
            import tarfile
            import tempfile

            # First, basic tar.gz format validation
            try:
                with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                    # Just check if we can open it as a tar.gz file
                    tar.getnames()
            except Exception as e:
                raise FileOperationException(
                    "upload", file.filename, f"Invalid tar.gz file: {str(e)}"
                )

            # Create temporary file for comprehensive security validation
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                temp_path = Path(temp_file.name)

            try:
                # Use comprehensive security validation
                TarExtractor.validate_archive_safety(temp_path)
                logger.info(f"Upload validation passed for {file.filename}")
            except SecurityError as e:
                # Clean up temp file
                temp_path.unlink(missing_ok=True)
                raise FileOperationException(
                    "upload", file.filename, f"Security validation failed: {str(e)}"
                )
            except Exception as e:
                # Clean up temp file
                temp_path.unlink(missing_ok=True)
                raise FileOperationException(
                    "upload", file.filename, f"Validation error: {str(e)}"
                )
            finally:
                # Always clean up temp file
                temp_path.unlink(missing_ok=True)

            # Create backup directory if it doesn't exist
            self.backups_directory.mkdir(exist_ok=True)

            # Write file to backup directory
            with open(backup_path, "wb") as f:
                f.write(content)

            logger.info(f"Uploaded backup file: {backup_path} ({file_size} bytes)")

            # Create backup record in database
            backup = Backup(
                server_id=server_id,
                name=name,
                description=description,
                file_path=str(backup_path),
                file_size=file_size,
                backup_type=BackupType.manual,
                status=BackupStatus.completed,  # Uploaded backups are immediately completed
                created_at=datetime.now(),
            )

            db.add(backup)
            db.commit()
            db.refresh(backup)

            logger.info(f"Created backup record: ID {backup.id}")

            return backup

        except Exception as e:
            logger.error(f"Failed to upload backup for server {server_id}: {e}")
            # Clean up file if it was created
            if "backup_path" in locals() and backup_path.exists():
                backup_path.unlink()

            if isinstance(e, (FileOperationException, DatabaseOperationException)):
                raise e
            else:
                raise DatabaseOperationException("upload", "backup", str(e))


# Global backup service instance
backup_service = BackupService()
