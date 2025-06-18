"""
Simplified synchronization service for server configuration files.

Key Logic:
- API updates always modify both database AND server.properties simultaneously
- Therefore, when database and server.properties differ, server.properties is always the latest
- This eliminates the need for complex timestamp comparisons
- Sync direction is always: server.properties → database when values differ
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.servers.models import Server

logger = logging.getLogger(__name__)


class SimplifiedSyncService:
    """
    Simplified synchronization service between database and server.properties.

    Core Principle:
    Since API updates always update both DB and file simultaneously,
    any difference between DB and file means the file was manually edited
    and should be considered the source of truth.
    """

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
                            try:
                                port = int(value.strip())
                                # Validate port range (1024-65535 for non-privileged ports)
                                if not (1024 <= port <= 65535):
                                    logger.warning(
                                        f"Invalid port {port} in properties file {properties_path}. "
                                        f"Port must be between 1024-65535."
                                    )
                                    return None
                                return port
                            except ValueError:
                                logger.warning(
                                    f"Invalid port value '{value.strip()}' in properties file {properties_path}"
                                )
                                return None
            return None
        except Exception as e:
            logger.error(f"Failed to read port from {properties_path}: {e}")
            return None

    def should_sync_from_file(
        self, server: Server, properties_path: Path
    ) -> Tuple[bool, Optional[int], str]:
        """
        Simplified sync determination logic.

        Since API updates always modify both DB and file simultaneously,
        any difference between DB and file means manual file edit occurred.
        Therefore, file should always take precedence when values differ.

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

            # If ports differ, file was manually edited and should be synced to DB
            # This is because API updates always update both DB and file together
            return (
                True,
                file_port,
                f"File port ({file_port}) differs from DB port ({server.port}) - manual edit detected, syncing file to DB",
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
            logger.info(
                f"DEBUG: Updating server {server.id} port: {old_port} -> {new_port}"
            )

            server.port = new_port
            db.commit()
            db.refresh(server)

            logger.info(
                f"Successfully synced port from file to database for server {server.id}: {old_port} -> {new_port}"
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
        """
        Sync port from database to file.

        Note: This method is kept for compatibility but should rarely be used
        in the new simplified logic, as file is always considered the source of truth
        when values differ.
        """
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
            from datetime import datetime

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

    def perform_simplified_sync(
        self, server: Server, properties_path: Path, db: Session
    ) -> Tuple[bool, str]:
        """
        Perform simplified sync operation.

        Logic:
        1. If DB and file ports match → no sync needed
        2. If DB and file ports differ → file was manually edited, sync file to DB

        This is much simpler than timestamp-based bidirectional sync because:
        - API updates always update both DB and file simultaneously
        - Manual file edits only update the file
        - Therefore, any difference means manual edit occurred

        Returns:
            Tuple of (success, description)
        """
        try:
            should_sync, file_port, reason = self.should_sync_from_file(
                server, properties_path
            )

            if should_sync and file_port is not None:
                # File differs from DB → manual edit detected → sync file to DB
                success = self.sync_port_from_file_to_database(server, file_port, db)
                if success:
                    return (
                        True,
                        f"Manual edit detected - synced file to database: {reason}",
                    )
                else:
                    return False, f"Failed to sync file to database: {reason}"
            else:
                # Ports match or file has no port → no sync needed
                return True, f"No sync needed: {reason}"

        except Exception as e:
            logger.error(f"Error in simplified sync for server {server.id}: {e}")
            return False, f"Sync error: {e}"


# Global simplified sync service instance
simplified_sync_service = SimplifiedSyncService()
