"""
Bidirectional synchronization service for server configuration files.
Handles sync between database and server.properties based on modification times.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.servers.models import Server

logger = logging.getLogger(__name__)


class BidirectionalSyncService:
    """Service for bidirectional synchronization between database and server.properties"""

    def __init__(self):
        pass

    def get_properties_file_port(self, properties_path: Path) -> Optional[int]:
        """Extract port from server.properties file"""
        try:
            if not properties_path.exists():
                return None

            with open(properties_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        if key.strip() == "server-port":
                            return int(value.strip())
            return None
        except Exception as e:
            logger.error(f"Failed to read port from {properties_path}: {e}")
            return None

    def get_file_modification_time(self, file_path: Path) -> Optional[datetime]:
        """Get file modification time as timezone-aware datetime"""
        try:
            if not file_path.exists():
                return None

            # Get modification time and convert to timezone-aware datetime
            mtime = os.path.getmtime(file_path)
            return datetime.fromtimestamp(mtime, tz=timezone.utc)
        except Exception as e:
            logger.error(f"Failed to get modification time for {file_path}: {e}")
            return None

    def should_sync_from_file(
        self, server: Server, properties_path: Path
    ) -> Tuple[bool, Optional[int], str]:
        """
        Determine if we should sync from file to database.

        Returns:
            Tuple of (should_sync, file_port, reason)
        """
        try:
            # Get port from file
            file_port = self.get_properties_file_port(properties_path)
            if file_port is None:
                return False, None, "No port found in properties file"

            # If ports are the same, no sync needed
            if file_port == server.port:
                return False, file_port, "Ports are already in sync"

            # Get file modification time
            file_mtime = self.get_file_modification_time(properties_path)
            if file_mtime is None:
                return False, file_port, "Could not get file modification time"

            # Compare with database updated_at
            # Ensure both timestamps are timezone-aware for comparison
            db_updated_at = server.updated_at
            if db_updated_at.tzinfo is None:
                db_updated_at = db_updated_at.replace(tzinfo=timezone.utc)

            # If file is newer than database, sync from file
            if file_mtime > db_updated_at:
                return (
                    True,
                    file_port,
                    f"File is newer (file: {file_mtime}, db: {server.updated_at})",
                )
            else:
                return (
                    False,
                    file_port,
                    f"Database is newer (db: {db_updated_at}, file: {file_mtime})",
                )

        except Exception as e:
            logger.error(f"Error in should_sync_from_file for server {server.id}: {e}")
            return False, None, f"Error: {e}"

    def sync_port_from_file_to_database(
        self, server: Server, new_port: int, db: Session
    ) -> bool:
        """Sync port from file to database"""
        try:
            old_port = server.port
            server.port = new_port
            db.commit()
            db.refresh(server)

            logger.info(
                f"Synced port from file to database for server {server.id}: {old_port} -> {new_port}"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to sync port from file to database for server {server.id}: {e}"
            )
            db.rollback()
            return False

    def sync_port_from_database_to_file(
        self, server: Server, properties_path: Path
    ) -> bool:
        """Sync port from database to file"""
        try:
            # Read existing properties
            properties = {}
            if properties_path.exists():
                with open(properties_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            properties[key] = value

            # Update port and max_players from database
            properties["server-port"] = str(server.port)
            properties["max-players"] = str(server.max_players)

            # Write updated properties back
            with open(properties_path, "w", encoding="utf-8") as f:
                f.write("#Minecraft server properties\n")
                f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
                for key, value in sorted(properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(
                f"Synced port from database to file for server {server.id}: port={server.port}"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to sync port from database to file for server {server.id}: {e}"
            )
            return False

    def perform_bidirectional_sync(
        self, server: Server, properties_path: Path, db: Session
    ) -> Tuple[bool, str]:
        """
        Perform bidirectional sync based on modification times.

        Returns:
            Tuple of (success, description)
        """
        try:
            should_sync, file_port, reason = self.should_sync_from_file(
                server, properties_path
            )

            if should_sync and file_port is not None:
                # Sync from file to database
                success = self.sync_port_from_file_to_database(server, file_port, db)
                if success:
                    return True, f"Synced from file to database: {reason}"
                else:
                    return False, f"Failed to sync from file to database: {reason}"
            else:
                # Sync from database to file (default behavior)
                success = self.sync_port_from_database_to_file(server, properties_path)
                if success:
                    return True, f"Synced from database to file: {reason}"
                else:
                    return False, f"Failed to sync from database to file: {reason}"

        except Exception as e:
            logger.error(f"Error in bidirectional sync for server {server.id}: {e}")
            return False, f"Sync error: {e}"


# Global bidirectional sync service instance
bidirectional_sync_service = BidirectionalSyncService()
