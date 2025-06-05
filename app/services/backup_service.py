import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.servers.models import Backup, BackupStatus, BackupType, Server
from app.services.minecraft_server import minecraft_server_manager

logger = logging.getLogger(__name__)


class BackupError(Exception):
    """Base exception for backup operations"""

    pass


class BackupNotFoundError(BackupError):
    """Backup not found error"""

    pass


class ServerNotFoundError(BackupError):
    """Server not found error"""

    pass


class BackupCreationError(BackupError):
    """Error creating backup"""

    pass


class BackupRestorationError(BackupError):
    """Error restoring backup"""

    pass


class BackupService:
    """Service for managing server backups"""

    def __init__(self):
        self.backups_directory = Path("backups")
        self.backups_directory.mkdir(exist_ok=True)

    async def create_backup(
        self,
        server_id: int,
        name: str,
        description: Optional[str] = None,
        backup_type: BackupType = BackupType.manual,
        db: Session = None,
    ) -> Backup:
        """Create a backup of a server"""
        try:
            # Get server from database
            server = (
                db.query(Server)
                .filter(and_(Server.id == server_id, not Server.is_deleted))
                .first()
            )

            if not server:
                raise ServerNotFoundError(f"Server {server_id} not found")

            # Check if server is stopped (safer for backups)
            is_running = minecraft_server_manager.get_server_status(server_id)
            if is_running and is_running.value != "stopped":
                logger.warning(f"Creating backup of running server {server_id}")

            # Create backup record
            backup = Backup(
                server_id=server_id,
                name=name,
                description=description,
                file_path="",  # Will be set after successful creation
                file_size=0,  # Will be set after successful creation
                backup_type=backup_type,
                status=BackupStatus.creating,
            )

            db.add(backup)
            db.flush()  # Get backup ID

            # Create backup file
            backup_filename = await self._create_backup_file(
                server, backup.id, backup_type
            )
            backup_path = self.backups_directory / backup_filename

            # Update backup record with file information
            backup.file_path = str(backup_path)
            backup.file_size = backup_path.stat().st_size
            backup.status = BackupStatus.completed

            db.commit()
            db.refresh(backup)

            logger.info(
                f"Successfully created backup {backup.id} for server {server_id}: {backup_filename}"
            )
            return backup

        except Exception as e:
            if "backup" in locals():
                backup.status = BackupStatus.failed
                db.commit()

            logger.error(f"Failed to create backup for server {server_id}: {e}")
            raise BackupCreationError(f"Failed to create backup: {str(e)}")

    async def _create_backup_file(
        self, server: Server, backup_id: int, backup_type: BackupType
    ) -> str:
        """Create the actual backup file (tar.gz)"""
        try:
            server_dir = Path(server.directory_path)
            if not server_dir.exists():
                raise BackupCreationError(f"Server directory not found: {server_dir}")

            # Generate backup filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{server.id}_{backup_id}_{timestamp}.tar.gz"
            backup_path = self.backups_directory / backup_filename

            # Create tar.gz backup
            with tarfile.open(backup_path, "w:gz") as tar:
                # Add all files in server directory
                for item in server_dir.rglob("*"):
                    if item.is_file():
                        # Calculate relative path from server directory
                        arcname = item.relative_to(server_dir)
                        tar.add(item, arcname=arcname)

            logger.info(f"Created backup file: {backup_filename}")
            return backup_filename

        except Exception as e:
            logger.error(f"Failed to create backup file: {e}")
            raise BackupCreationError(f"Failed to create backup file: {str(e)}")

    async def restore_backup(
        self, backup_id: int, server_id: Optional[int] = None, db: Session = None
    ) -> bool:
        """Restore a backup to a server"""
        try:
            # Get backup from database
            backup = db.query(Backup).filter(Backup.id == backup_id).first()

            if not backup:
                raise BackupNotFoundError(f"Backup {backup_id} not found")

            if backup.status != BackupStatus.completed:
                raise BackupRestorationError(
                    f"Backup {backup_id} is not in completed state"
                )

            # Determine target server
            target_server_id = server_id or backup.server_id
            target_server = (
                db.query(Server)
                .filter(and_(Server.id == target_server_id, not Server.is_deleted))
                .first()
            )

            if not target_server:
                raise ServerNotFoundError(f"Target server {target_server_id} not found")

            # Ensure server is stopped
            server_status = minecraft_server_manager.get_server_status(target_server_id)
            if server_status and server_status.value != "stopped":
                raise BackupRestorationError(
                    f"Server {target_server_id} must be stopped before restoration"
                )

            # Restore backup
            await self._restore_backup_file(backup, target_server)

            logger.info(
                f"Successfully restored backup {backup_id} to server {target_server_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to restore backup {backup_id}: {e}")
            raise BackupRestorationError(f"Failed to restore backup: {str(e)}")

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
        try:
            # First restore the backup
            success = await self.restore_backup(backup_id, server_id, db)

            if not success:
                raise BackupRestorationError("Failed to restore backup")

            result = {"backup_restored": True, "template_created": False}

            # If template name is provided, create template from restored server
            if template_name:
                from app.services.template_service import TemplateService

                # Get the target server
                backup = db.query(Backup).filter(Backup.id == backup_id).first()
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

        except Exception as e:
            logger.error(f"Failed to restore backup and create template: {e}")
            raise BackupRestorationError(
                f"Failed to restore backup and create template: {str(e)}"
            )

    async def _restore_backup_file(self, backup: Backup, target_server: Server):
        """Restore the backup file to target server directory"""
        try:
            backup_path = Path(backup.file_path)
            if not backup_path.exists():
                raise BackupRestorationError(f"Backup file not found: {backup_path}")

            target_dir = Path(target_server.directory_path)

            # Create backup of current server state (if exists)
            if target_dir.exists():
                backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_backup_dir = (
                    target_dir.parent / f"{target_dir.name}_backup_{backup_timestamp}"
                )
                shutil.move(str(target_dir), str(temp_backup_dir))
                logger.info(
                    f"Created temporary backup of current state: {temp_backup_dir}"
                )

            # Create target directory
            target_dir.mkdir(parents=True, exist_ok=True)

            # Extract backup
            with tarfile.open(backup_path, "r:gz") as tar:
                tar.extractall(path=target_dir)

            logger.info(f"Extracted backup to: {target_dir}")

        except Exception as e:
            logger.error(f"Failed to restore backup file: {e}")
            raise BackupRestorationError(f"Failed to restore backup file: {str(e)}")

    async def delete_backup(self, backup_id: int, db: Session) -> bool:
        """Delete a backup and its file"""
        try:
            backup = db.query(Backup).filter(Backup.id == backup_id).first()

            if not backup:
                raise BackupNotFoundError(f"Backup {backup_id} not found")

            # Delete backup file
            backup_path = Path(backup.file_path)
            if backup_path.exists():
                backup_path.unlink()
                logger.info(f"Deleted backup file: {backup_path}")

            # Delete database record
            db.delete(backup)
            db.commit()

            logger.info(f"Successfully deleted backup {backup_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete backup {backup_id}: {e}")
            raise BackupError(f"Failed to delete backup: {str(e)}")

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
            raise BackupError(f"Failed to list backups: {str(e)}")

    def get_backup(self, backup_id: int, db: Session) -> Optional[Backup]:
        """Get backup by ID"""
        try:
            return db.query(Backup).filter(Backup.id == backup_id).first()

        except Exception as e:
            logger.error(f"Failed to get backup {backup_id}: {e}")
            raise BackupError(f"Failed to get backup: {str(e)}")

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
            raise BackupError(f"Failed to get backup statistics: {str(e)}")


# Global backup service instance
backup_service = BackupService()
