import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.database import engine
from app.servers.models import BackupType, Server
from app.services.backup_service import backup_service

logger = logging.getLogger(__name__)


class BackupScheduler:
    """Service for managing automated backup scheduling"""

    def __init__(self):
        self.scheduler_running = False
        self.scheduled_servers: Dict[int, Dict] = {}
        self.scheduler_task: Optional[asyncio.Task] = None

    async def start_scheduler(self):
        """Start the backup scheduler"""
        if self.scheduler_running:
            logger.warning("Backup scheduler is already running")
            return

        self.scheduler_running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Backup scheduler started")

    async def stop_scheduler(self):
        """Stop the backup scheduler"""
        if not self.scheduler_running:
            logger.warning("Backup scheduler is not running")
            return

        self.scheduler_running = False
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass

        logger.info("Backup scheduler stopped")

    def add_server_schedule(
        self,
        server_id: int,
        interval_hours: int = 24,
        max_backups: int = 7,
        enabled: bool = True,
    ):
        """Add or update a server's backup schedule"""
        self.scheduled_servers[server_id] = {
            "interval_hours": interval_hours,
            "max_backups": max_backups,
            "enabled": enabled,
            "last_backup": None,
            "next_backup": datetime.now() + timedelta(hours=interval_hours),
        }
        logger.info(
            f"Added backup schedule for server {server_id}: "
            f"every {interval_hours}h, max {max_backups} backups"
        )

    def remove_server_schedule(self, server_id: int):
        """Remove a server's backup schedule"""
        if server_id in self.scheduled_servers:
            del self.scheduled_servers[server_id]
            logger.info(f"Removed backup schedule for server {server_id}")

    def update_server_schedule(
        self,
        server_id: int,
        interval_hours: Optional[int] = None,
        max_backups: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Update a server's backup schedule"""
        if server_id not in self.scheduled_servers:
            logger.warning(f"No schedule found for server {server_id}")
            return

        schedule = self.scheduled_servers[server_id]

        if interval_hours is not None:
            schedule["interval_hours"] = interval_hours
            # Recalculate next backup time
            last_backup = schedule.get("last_backup")
            if last_backup:
                schedule["next_backup"] = last_backup + timedelta(hours=interval_hours)
            else:
                schedule["next_backup"] = datetime.now() + timedelta(hours=interval_hours)

        if max_backups is not None:
            schedule["max_backups"] = max_backups

        if enabled is not None:
            schedule["enabled"] = enabled

        logger.info(f"Updated backup schedule for server {server_id}")

    def get_server_schedule(self, server_id: int) -> Optional[Dict]:
        """Get a server's backup schedule"""
        return self.scheduled_servers.get(server_id)

    def list_scheduled_servers(self) -> Dict[int, Dict]:
        """List all scheduled servers"""
        return self.scheduled_servers.copy()

    async def _scheduler_loop(self):
        """Main scheduler loop that runs backup tasks"""
        try:
            while self.scheduler_running:
                await self._process_scheduled_backups()
                # Check every 10 minutes
                await asyncio.sleep(600)
        except asyncio.CancelledError:
            logger.info("Backup scheduler loop cancelled")
        except Exception as e:
            logger.error(f"Error in backup scheduler loop: {e}")

    async def _process_scheduled_backups(self):
        """Process all scheduled backups that are due"""
        now = datetime.now()

        for server_id, schedule in self.scheduled_servers.items():
            if not schedule.get("enabled", True):
                continue

            next_backup = schedule.get("next_backup")
            if not next_backup or now < next_backup:
                continue

            try:
                await self._create_scheduled_backup(server_id, schedule)
            except Exception as e:
                logger.error(
                    f"Failed to create scheduled backup for server {server_id}: {e}"
                )

    async def _create_scheduled_backup(self, server_id: int, schedule: Dict):
        """Create a scheduled backup for a server"""
        try:
            # Create database session
            from sqlalchemy.orm import sessionmaker

            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

            with SessionLocal() as db:
                # Check if server exists and is not deleted
                server = (
                    db.query(Server)
                    .filter(Server.id == server_id, not Server.is_deleted)
                    .first()
                )

                if not server:
                    logger.warning(
                        f"Server {server_id} not found, removing from schedule"
                    )
                    self.remove_server_schedule(server_id)
                    return

                # Create backup
                backup = await backup_service.create_scheduled_backup(server_id, db)

                if backup:
                    # Update schedule
                    schedule["last_backup"] = datetime.now()
                    schedule["next_backup"] = schedule["last_backup"] + timedelta(
                        hours=schedule["interval_hours"]
                    )

                    logger.info(
                        f"Created scheduled backup {backup.id} for server {server_id}"
                    )

                    # Clean up old backups if needed
                    await self._cleanup_old_backups(
                        server_id, schedule["max_backups"], db
                    )

        except Exception as e:
            logger.error(f"Failed to create scheduled backup for server {server_id}: {e}")

    async def _cleanup_old_backups(self, server_id: int, max_backups: int, db: Session):
        """Clean up old scheduled backups for a server"""
        try:
            from app.servers.models import Backup, BackupStatus

            # Get all completed scheduled backups for this server
            backups = (
                db.query(Backup)
                .filter(
                    Backup.server_id == server_id,
                    Backup.backup_type == BackupType.scheduled,
                    Backup.status == BackupStatus.completed,
                )
                .order_by(Backup.created_at.desc())
                .all()
            )

            # Delete excess backups
            if len(backups) > max_backups:
                backups_to_delete = backups[max_backups:]
                for backup in backups_to_delete:
                    await backup_service.delete_backup(backup.id, db)
                    logger.info(
                        f"Deleted old scheduled backup {backup.id} for server {server_id}"
                    )

        except Exception as e:
            logger.error(f"Failed to cleanup old backups for server {server_id}: {e}")

    def get_scheduler_status(self) -> Dict:
        """Get current scheduler status"""
        return {
            "running": self.scheduler_running,
            "scheduled_servers_count": len(self.scheduled_servers),
            "scheduled_servers": {
                server_id: {
                    "interval_hours": schedule["interval_hours"],
                    "max_backups": schedule["max_backups"],
                    "enabled": schedule["enabled"],
                    "last_backup": (
                        schedule.get("last_backup").isoformat()
                        if schedule.get("last_backup")
                        else None
                    ),
                    "next_backup": (
                        schedule.get("next_backup").isoformat()
                        if schedule.get("next_backup")
                        else None
                    ),
                }
                for server_id, schedule in self.scheduled_servers.items()
            },
        }


# Global backup scheduler instance
backup_scheduler = BackupScheduler()
