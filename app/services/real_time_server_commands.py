import json
import logging
from pathlib import Path
from typing import Set

from app.groups.models import GroupType
from app.servers.models import ServerStatus
from app.services.minecraft_server import minecraft_server_manager

logger = logging.getLogger(__name__)


class RealTimeServerCommandService:
    """Service for sending real-time commands to running Minecraft servers"""

    def __init__(self):
        pass

    async def reload_whitelist_if_running(self, server_id: int) -> bool:
        """
        Reload whitelist for a running server
        
        Args:
            server_id: The ID of the server to reload whitelist for
            
        Returns:
            bool: True if command was sent successfully, False if server not running
        """
        try:
            # Check if server is running
            status = minecraft_server_manager.get_server_status(server_id)
            if status != ServerStatus.running:
                logger.debug(f"Server {server_id} is not running ({status.value}), skipping whitelist reload")
                return False

            # Send whitelist reload command
            success = await minecraft_server_manager.send_command(server_id, "whitelist reload")
            if success:
                logger.info(f"Successfully sent whitelist reload command to server {server_id}")
            else:
                logger.warning(f"Failed to send whitelist reload command to server {server_id}")
                
            return success

        except Exception as e:
            logger.error(f"Error reloading whitelist for server {server_id}: {e}")
            return False

    async def sync_op_changes_if_running(self, server_id: int, server_path: Path) -> bool:
        """
        Sync OP changes for a running server by comparing current ops.json with server state
        
        Args:
            server_id: The ID of the server to sync OP changes for
            server_path: Path to the server directory
            
        Returns:
            bool: True if all commands were sent successfully
        """
        try:
            # Check if server is running
            status = minecraft_server_manager.get_server_status(server_id)
            if status != ServerStatus.running:
                logger.debug(f"Server {server_id} is not running ({status.value}), skipping OP sync")
                return False

            # Read current ops.json
            ops_file = server_path / "ops.json"
            if not ops_file.exists():
                logger.warning(f"ops.json not found for server {server_id}, creating empty list")
                current_ops = []
            else:
                try:
                    with open(ops_file, "r", encoding="utf-8") as f:
                        current_ops = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Failed to read ops.json for server {server_id}: {e}")
                    return False

            # Get current OP player names (Minecraft commands work with names, not UUIDs)
            current_op_names = {op.get("name") for op in current_ops if op.get("name")}
            
            # For real-time sync, we need to determine what changed
            # Since we don't have the previous state, we'll use a simple approach:
            # Apply all current OPs to ensure server state matches file
            
            success_count = 0
            total_commands = len(current_op_names)
            
            for player_name in current_op_names:
                try:
                    # Send OP command (this is idempotent - won't hurt if player is already OP)
                    success = await minecraft_server_manager.send_command(server_id, f"op {player_name}")
                    if success:
                        success_count += 1
                        logger.debug(f"Successfully sent OP command for {player_name} to server {server_id}")
                    else:
                        logger.warning(f"Failed to send OP command for {player_name} to server {server_id}")
                        
                except Exception as e:
                    logger.error(f"Error sending OP command for {player_name} to server {server_id}: {e}")

            if total_commands > 0:
                logger.info(f"Sent {success_count}/{total_commands} OP commands to server {server_id}")
            
            return success_count == total_commands

        except Exception as e:
            logger.error(f"Error syncing OP changes for server {server_id}: {e}")
            return False

    async def apply_op_diff_if_running(self, server_id: int, added_players: Set[str], removed_players: Set[str]) -> bool:
        """
        Apply specific OP differences to a running server
        
        Args:
            server_id: The ID of the server
            added_players: Set of player names to add as OP
            removed_players: Set of player names to remove from OP
            
        Returns:
            bool: True if all commands were sent successfully
        """
        try:
            # Check if server is running
            status = minecraft_server_manager.get_server_status(server_id)
            if status != ServerStatus.running:
                logger.debug(f"Server {server_id} is not running ({status.value}), skipping OP diff")
                return False

            success_count = 0
            total_commands = len(added_players) + len(removed_players)
            
            # Add new OPs
            for player_name in added_players:
                try:
                    success = await minecraft_server_manager.send_command(server_id, f"op {player_name}")
                    if success:
                        success_count += 1
                        logger.info(f"Added OP: {player_name} on server {server_id}")
                    else:
                        logger.warning(f"Failed to add OP: {player_name} on server {server_id}")
                except Exception as e:
                    logger.error(f"Error adding OP {player_name} to server {server_id}: {e}")

            # Remove OPs
            for player_name in removed_players:
                try:
                    success = await minecraft_server_manager.send_command(server_id, f"deop {player_name}")
                    if success:
                        success_count += 1
                        logger.info(f"Removed OP: {player_name} from server {server_id}")
                    else:
                        logger.warning(f"Failed to remove OP: {player_name} from server {server_id}")
                except Exception as e:
                    logger.error(f"Error removing OP {player_name} from server {server_id}: {e}")

            if total_commands > 0:
                logger.info(f"Applied {success_count}/{total_commands} OP changes to server {server_id}")
            
            return success_count == total_commands

        except Exception as e:
            logger.error(f"Error applying OP diff to server {server_id}: {e}")
            return False

    async def handle_group_change_commands(
        self, 
        server_id: int, 
        server_path: Path, 
        group_type: GroupType, 
        change_type: str = "update"
    ) -> bool:
        """
        Handle real-time commands for group changes
        
        Args:
            server_id: The ID of the affected server
            server_path: Path to the server directory  
            group_type: Type of group that changed (op or whitelist)
            change_type: Type of change (update, attach, detach, player_add, player_remove)
            
        Returns:
            bool: True if commands were sent successfully
        """
        try:
            # Check if server is running
            status = minecraft_server_manager.get_server_status(server_id)
            if status != ServerStatus.running:
                logger.debug(f"Server {server_id} is not running ({status.value}), skipping real-time commands")
                return True  # Return True since file update already happened

            success = True

            if group_type == GroupType.whitelist:
                # For whitelist changes, only reload the whitelist
                reload_success = await self.reload_whitelist_if_running(server_id)
                if reload_success:
                    logger.info(f"Reloaded whitelist for server {server_id} after {change_type}")
                else:
                    logger.warning(f"Failed to reload whitelist for server {server_id} after {change_type}")
                    success = False

            elif group_type == GroupType.op:
                # For OP changes, only sync the current OP state (don't reload whitelist)
                sync_success = await self.sync_op_changes_if_running(server_id, server_path)
                if sync_success:
                    logger.info(f"Synced OP changes for server {server_id} after {change_type}")
                else:
                    logger.warning(f"Failed to sync OP changes for server {server_id} after {change_type}")
                    success = False

            return success

        except Exception as e:
            logger.error(f"Error handling group change commands for server {server_id}: {e}")
            return False


# Global service instance
real_time_server_commands = RealTimeServerCommandService()
