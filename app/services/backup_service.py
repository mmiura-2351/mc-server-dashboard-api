import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
    ServerStateException,
    handle_database_error,
    handle_file_error,
)
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
            .filter(and_(Server.id == server_id, not Server.is_deleted))
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
        self, server: Server, backup_id: int, backup_type: BackupType
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

            self._create_tar_backup(server_dir, backup_path)

            logger.info(f"Created backup file: {backup_filename}")
            return backup_filename

        except Exception as e:
            handle_file_error("create backup", str(server_dir), e)

    def _generate_backup_filename(self, server_id: int, backup_id: int) -> str:
        """Generate unique backup filename"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"backup_{server_id}_{backup_id}_{timestamp}.tar.gz"

    def _create_tar_backup(self, server_dir: Path, backup_path: Path) -> None:
        """Create tar.gz backup of server directory"""
        with tarfile.open(backup_path, "w:gz") as tar:
            for item in server_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(server_dir)
                    tar.add(item, arcname=arcname)

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
        """Extract backup archive to target directory"""
        target_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(path=target_dir)

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

        for server_id in server_ids:
            try:
                # Check if server exists
                server = (
                    db.query(Server)
                    .filter(and_(Server.id == server_id, not Server.is_deleted))
                    .first()
                )

                if not server:
                    results["failed"].append(
                        {"server_id": server_id, "error": f"Server {server_id} not found"}
                    )
                    results["error_count"] += 1
                    continue

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
                .filter(and_(Server.id == server_id, not Server.is_deleted))
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

            # Calculate total backup size
            completed_query = query.filter(Backup.status == BackupStatus.completed)
            total_size = sum(backup.file_size for backup in completed_query.all())

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


# Global backup service instance
backup_service = BackupService()
