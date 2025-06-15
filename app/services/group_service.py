import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.core.exceptions import FileOperationException
from app.groups.models import Group, GroupType, ServerGroup
from app.servers.models import Server
from app.services.real_time_server_commands import real_time_server_commands
from app.users.models import Role, User

logger = logging.getLogger(__name__)


class GroupAccessService:
    """Service for handling group and server access validation.

    This service centralizes access control logic for groups and servers,
    ensuring proper permission checks throughout the system.
    """

    @staticmethod
    def check_group_access(
        user: Annotated[User, "User requesting access"],
        group: Annotated[Group, "Group to access"],
    ) -> None:
        """Check if user has access to the specified group.

        Args:
            user: The user requesting access
            group: The group to access

        Raises:
            HTTPException: If user doesn't have permission to access the group
        """
        if user.role != Role.admin and group.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this group",
            )

    @staticmethod
    def check_server_access(
        user: Annotated[User, "User requesting access"],
        server: Annotated[Server, "Server to access"],
    ) -> None:
        """Check if user has access to the specified server.

        Args:
            user: The user requesting access
            server: The server to access

        Raises:
            HTTPException: If user doesn't have permission to access the server
        """
        if user.role != Role.admin and server.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this server",
            )


class GroupFileService:
    """Service for handling group-related file operations.

    This service manages the synchronization of group data with server files,
    specifically handling ops.json and whitelist.json updates.
    """

    def __init__(self, db: Annotated[Session, "Database session"]):
        self.db = db

    async def update_server_files(
        self, server_id: Annotated[int, "ID of server to update"]
    ) -> None:
        """Update ops.json and whitelist.json files for a server.

        This method retrieves all groups attached to a server and regenerates
        the ops.json and whitelist.json files based on group memberships.

        Args:
            server_id: The ID of the server to update
        """
        try:
            # Get server info
            server = self.db.query(Server).filter(Server.id == server_id).first()
            if not server:
                logger.warning(f"Server {server_id} not found during file sync")
                return

            logger.info(
                f"Starting file sync for server {server_id} (name: {server.name}, path: {server.directory_path})"
            )

            # Get all groups attached to this server
            server_groups = (
                self.db.query(Group)
                .join(ServerGroup, Group.id == ServerGroup.group_id)
                .filter(ServerGroup.server_id == server_id)
                .order_by(ServerGroup.priority.desc())
                .all()
            )

            logger.info(
                f"Found {len(server_groups)} groups attached to server {server_id}: {[g.name for g in server_groups]}"
            )

            # Build ops and whitelist data
            ops_data = []
            whitelist_data = []

            for group in server_groups:
                players = group.get_players()

                for player in players:
                    player_entry = {
                        "uuid": player["uuid"],
                        "name": player["username"],
                        "level": 4 if group.type == GroupType.op else 0,
                        "bypassesPlayerLimit": group.type == GroupType.op,
                    }

                    if group.type == GroupType.op:
                        # Add to ops if not already present
                        if not any(op["uuid"] == player["uuid"] for op in ops_data):
                            ops_data.append(player_entry)

                    if group.type == GroupType.whitelist:
                        # Add to whitelist if not already present
                        whitelist_entry = {
                            "uuid": player["uuid"],
                            "name": player["username"],
                        }
                        if not any(wl["uuid"] == player["uuid"] for wl in whitelist_data):
                            whitelist_data.append(whitelist_entry)

            # Write to server files using the actual server directory path
            server_path = Path(server.directory_path)

            if server_path.exists():
                # Update ops.json
                ops_file = server_path / "ops.json"
                with open(ops_file, "w", encoding="utf-8") as f:
                    json.dump(ops_data, f, indent=2)
                logger.info(
                    f"Updated ops.json at {ops_file} with {len(ops_data)} entries"
                )

                # Update whitelist.json
                whitelist_file = server_path / "whitelist.json"
                with open(whitelist_file, "w", encoding="utf-8") as f:
                    json.dump(whitelist_data, f, indent=2)
                logger.info(
                    f"Updated whitelist.json at {whitelist_file} with {len(whitelist_data)} entries"
                )

                logger.info(
                    f"Successfully synchronized server files for server {server_id}"
                )

                # Send real-time commands to running server if needed
                try:
                    # Reload whitelist for running servers (if any whitelist groups are attached)
                    has_whitelist_groups = any(group.type == GroupType.whitelist for group in server_groups)
                    if has_whitelist_groups:
                        await real_time_server_commands.reload_whitelist_if_running(server_id)
                    # Sync OP changes for running servers (if any OP groups are attached)
                    # Don't fail the entire operation if real-time commands fail
                    has_op_groups = any(group.type == GroupType.op for group in server_groups)
                    if has_op_groups:
                        await real_time_server_commands.sync_op_changes_if_running(server_id, server_path)
                except Exception as cmd_error:
                    logger.warning(f"Failed to send real-time commands to server {server_id}: {cmd_error}")
            else:
                logger.error(
                    f"Server directory {server_path} does not exist - cannot sync files for server {server_id}"
                )

        except Exception as e:
            # Log error with proper logging and re-raise for better error handling
            logger.error(f"Failed to update server files for server {server_id}: {e}")
            raise FileOperationException(
                "update", f"server {server_id} files", str(e)
            ) from e

    async def batch_update_server_files(self, server_ids: List[int]):
        """Batch update server files for multiple servers to reduce N+1 queries"""
        if not server_ids:
            return

        try:
            # Get all servers in a single query using the existing db session
            servers = (
                self.db.query(Server)
                .filter(Server.id.in_(server_ids), ~Server.is_deleted)
                .all()
            )

            # Track failed updates for better error reporting
            failed_updates = []

            # Use the existing file service update logic for each server
            for server in servers:
                try:
                    # Call the original update method directly on the instance
                    await self.update_server_files(server.id)
                except Exception as e:
                    logger.error(
                        f"Failed to update server files for server {server.id}: {e}"
                    )
                    failed_updates.append((server.id, str(e)))

            # Report any failures
            if failed_updates:
                error_details = "; ".join(
                    [f"Server {sid}: {err}" for sid, err in failed_updates]
                )
                raise FileOperationException(
                    "update", "multiple server files", error_details
                )

        except Exception as e:
            logger.error(f"Critical error in batch server file update: {e}")
            raise FileOperationException("batch update", "server files", str(e)) from e

    async def update_all_affected_servers_with_retry(
        self, group_id: int, max_retries: int = 3, retry_delay: float = 1.0
    ) -> None:
        """Update all affected servers with retry logic for reliability"""
        last_exception = None

        for attempt in range(max_retries):
            try:
                await self.update_all_affected_servers(group_id)
                if attempt > 0:
                    logger.info(
                        f"Server file sync succeeded on attempt {attempt + 1} for group {group_id}"
                    )
                return  # Success
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Server file sync attempt {attempt + 1} failed for group {group_id}: {e}"
                )

                if attempt < max_retries - 1:
                    # Wait before retrying
                    await asyncio.sleep(
                        retry_delay * (attempt + 1)
                    )  # Exponential backoff

        # All retries failed
        logger.error(
            f"All {max_retries} attempts to sync server files failed for group {group_id}"
        )
        raise FileOperationException(
            "sync", f"server files (after {max_retries} attempts)", str(last_exception)
        ) from last_exception

    async def update_all_affected_servers(
        self, group_id: Annotated[int, "ID of group that was modified"]
    ) -> None:
        """Update all servers that have the specified group attached.

        Args:
            group_id: The ID of the group that was modified
        """
        affected_servers = (
            self.db.query(ServerGroup.server_id)
            .filter(ServerGroup.group_id == group_id)
            .all()
        )

        # Batch process server file updates for better performance
        if affected_servers:
            server_ids = [server_id for (server_id,) in affected_servers]
            await self.batch_update_server_files(server_ids)


class GroupService:
    """Main service for orchestrating group management operations.

    This service handles CRUD operations for groups, player management,
    and server attachments with proper access control and audit logging.
    """

    def __init__(self, db: Annotated[Session, "Database session"]):
        self.db = db
        self.access_service = GroupAccessService()
        self.file_service = GroupFileService(db)

    def create_group(
        self,
        user: Annotated[User, "User creating the group"],
        name: Annotated[str, "Name of the group"],
        group_type: Annotated[GroupType, "Type of group (ops/whitelist)"],
        description: Annotated[Optional[str], "Optional description"] = None,
    ) -> Annotated[Group, "Created group instance"]:
        """Create a new group with the specified parameters.

        Args:
            user: The user creating the group
            name: Name of the group
            group_type: Type of group (ops or whitelist)
            description: Optional description of the group's purpose

        Returns:
            The created group instance

        Raises:
            HTTPException: If group name already exists for this user
        """
        # Check if group name already exists for this user
        existing_group = (
            self.db.query(Group)
            .filter(Group.owner_id == user.id, Group.name == name)
            .first()
        )

        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group with this name already exists",
            )

        group = Group(
            name=name,
            description=description,
            type=group_type,
            players=[],  # Empty list initially
            owner_id=user.id,
        )

        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)

        # Create audit log
        audit_log = AuditLog.create_log(
            action="group_created",
            resource_type="group",
            user_id=user.id,
            resource_id=group.id,
            details={"name": name, "type": group_type.value},
        )
        self.db.add(audit_log)
        self.db.commit()

        return group

    def get_user_groups(
        self, user: User, group_type: Optional[GroupType] = None
    ) -> List[Group]:
        """Get groups owned by user"""
        query = self.db.query(Group).filter(Group.owner_id == user.id)

        if group_type:
            query = query.filter(Group.type == group_type)

        return query.all()

    def get_group_by_id(self, user: User, group_id: int) -> Group:
        """Get group by ID with access check"""
        group = self.db.query(Group).filter(Group.id == group_id).first()

        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
            )

        self.access_service.check_group_access(user, group)
        return group

    def update_group(
        self,
        user: User,
        group_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Group:
        """Update group information"""
        group = self.get_group_by_id(user, group_id)

        old_values = {"name": group.name, "description": group.description}

        if name is not None and name != group.name:
            # Check if new name already exists for this user
            existing_group = (
                self.db.query(Group)
                .filter(
                    Group.owner_id == user.id, Group.name == name, Group.id != group_id
                )
                .first()
            )

            if existing_group:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Group with this name already exists",
                )

            group.name = name

        if description is not None:
            group.description = description

        self.db.commit()
        self.db.refresh(group)

        # Create audit log
        audit_log = AuditLog.create_log(
            action="group_updated",
            resource_type="group",
            user_id=user.id,
            resource_id=group.id,
            details={
                "old_values": old_values,
                "new_values": {"name": group.name, "description": group.description},
            },
        )
        self.db.add(audit_log)
        self.db.commit()

        return group

    def delete_group(self, user: User, group_id: int) -> None:
        """Delete a group"""
        group = self.get_group_by_id(user, group_id)

        # Check if group is attached to any servers
        attached_servers = (
            self.db.query(ServerGroup).filter(ServerGroup.group_id == group_id).count()
        )

        if attached_servers > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete group that is attached to servers",
            )

        # Create audit log before deletion
        audit_log = AuditLog.create_log(
            action="group_deleted",
            resource_type="group",
            user_id=user.id,
            resource_id=group.id,
            details={"name": group.name, "type": group.type.value},
        )
        self.db.add(audit_log)

        self.db.delete(group)
        self.db.commit()

    async def add_player_to_group(
        self,
        user: User,
        group_id: int,
        uuid: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Group:
        """Add a player to a group"""
        group = self.get_group_by_id(user, group_id)

        # Resolve UUID and username if one is missing
        if uuid and not username:
            # Try to get username from UUID
            from app.services.minecraft_api_service import MinecraftAPIService

            username = await MinecraftAPIService.get_username_from_uuid(uuid)
            if not username:
                # Fallback: use UUID as username if API fails
                username = uuid[:8]  # Use first 8 characters of UUID
        elif username and not uuid:
            # Try to get UUID from username
            from app.services.minecraft_api_service import MinecraftAPIService

            uuid = await MinecraftAPIService.get_uuid_from_username(username)
            if not uuid:
                # Fallback: generate offline UUID
                uuid = MinecraftAPIService.generate_offline_uuid(username)
        elif not uuid and not username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either uuid or username must be provided",
            )

        try:
            # Add player using model method
            group.add_player(uuid, username)

            # Commit the player addition first
            self.db.commit()
            self.db.refresh(group)

            # Update server files for all servers using this group with retry logic
            # This is critical - if this fails, we need to know about it
            try:
                await self.file_service.update_all_affected_servers_with_retry(group_id)
                logger.info(
                    f"Successfully synchronized server files after adding player {username} to group {group_id}"
                )
            except Exception as sync_error:
                logger.error(
                    f"Failed to synchronize server files after adding player {username} to group {group_id}: {sync_error}"
                )
                # Log the sync failure but don't rollback the player addition
                # This allows manual recovery while preserving the database state
                logger.warning(
                    f"Player {username} was successfully added to group {group_id} but server file sync failed. "
                    f"Manual file sync may be required. Error: {sync_error}"
                )

            # Send real-time commands for player addition
            try:
                # Get all servers this group is attached to and send commands
                attached_servers = (
                    self.db.query(ServerGroup.server_id, Server.directory_path)
                    .join(Server, ServerGroup.server_id == Server.id)
                    .filter(ServerGroup.group_id == group_id)
                    .all()
                )
                
                for server_id, directory_path in attached_servers:
                    await real_time_server_commands.handle_group_change_commands(
                        server_id, Path(directory_path), group.type, "player_add"
                    )
            except Exception as cmd_error:
                logger.warning(f"Failed to send real-time commands after adding player {username} to group {group_id}: {cmd_error}")

            # Create audit log after successful sync
            audit_log = AuditLog.create_log(
                action="player_added_to_group",
                resource_type="group",
                user_id=user.id,
                resource_id=group.id,
                details={"player_uuid": uuid, "player_username": username},
            )
            self.db.add(audit_log)
            self.db.commit()

            return group

        except HTTPException:
            # Re-raise HTTP exceptions (like sync failures)
            raise
        except Exception as e:
            # Rollback any database changes on unexpected errors
            self.db.rollback()
            logger.error(f"Failed to add player {username} to group {group_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to add player to group: {e}",
            ) from e

    async def remove_player_from_group(
        self, user: User, group_id: int, uuid: str
    ) -> Group:
        """Remove a player from a group"""
        group = self.get_group_by_id(user, group_id)

        try:
            # Remove player using model method
            removed = group.remove_player(uuid)

            if not removed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Player not found in group",
                )

            # Commit the player removal first
            self.db.commit()
            self.db.refresh(group)

            # Update server files for all servers using this group with retry logic
            # This is critical - if this fails, we need to know about it
            try:
                await self.file_service.update_all_affected_servers_with_retry(group_id)
                logger.info(
                    f"Successfully synchronized server files after removing player {uuid} from group {group_id}"
                )
            except Exception as sync_error:
                logger.error(
                    f"Failed to synchronize server files after removing player {uuid} from group {group_id}: {sync_error}"
                )
                # Log the sync failure but don't rollback the player removal
                logger.warning(
                    f"Player {uuid} was successfully removed from group {group_id} but server file sync failed. "
                    f"Manual file sync may be required. Error: {sync_error}"
                )

            # Send real-time commands for player removal
            try:
                # Get all servers this group is attached to and send commands
                attached_servers = (
                    self.db.query(ServerGroup.server_id, Server.directory_path)
                    .join(Server, ServerGroup.server_id == Server.id)
                    .filter(ServerGroup.group_id == group_id)
                    .all()
                )
                
                for server_id, directory_path in attached_servers:
                    await real_time_server_commands.handle_group_change_commands(
                        server_id, Path(directory_path), group.type, "player_remove"
                    )
            except Exception as cmd_error:
                logger.warning(f"Failed to send real-time commands after removing player {uuid} from group {group_id}: {cmd_error}")

            # Create audit log after successful sync
            audit_log = AuditLog.create_log(
                action="player_removed_from_group",
                resource_type="group",
                user_id=user.id,
                resource_id=group.id,
                details={"player_uuid": uuid},
            )
            self.db.add(audit_log)
            self.db.commit()

        except HTTPException:
            # Re-raise HTTP exceptions (like sync failures)
            raise
        except Exception as e:
            # Rollback any database changes on unexpected errors
            self.db.rollback()
            logger.error(f"Failed to remove player {uuid} from group {group_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to remove player from group: {e}",
            ) from e

        return group

    async def attach_group_to_server(
        self, user: User, server_id: int, group_id: int, priority: int = 0
    ) -> None:
        """Attach a group to a server"""
        # Check server access
        server = self.db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        self.access_service.check_server_access(user, server)

        # Check group access
        group = self.get_group_by_id(user, group_id)

        # Check if already attached
        existing_attachment = (
            self.db.query(ServerGroup)
            .filter(ServerGroup.server_id == server_id, ServerGroup.group_id == group_id)
            .first()
        )

        if existing_attachment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group is already attached to this server",
            )

        # Create attachment
        server_group = ServerGroup(
            server_id=server_id, group_id=group_id, priority=priority
        )

        try:
            self.db.add(server_group)
            self.db.commit()

            # Update server files immediately after attachment with retry logic
            try:
                # Use single server update with retry wrapper
                for attempt in range(3):
                    try:
                        await self.file_service.update_server_files(server_id)
                        if attempt > 0:
                            logger.info(
                                f"Server file sync succeeded on attempt {attempt + 1} for server {server_id}"
                            )
                        break
                    except Exception as e:
                        if attempt < 2:
                            logger.warning(
                                f"Server file sync attempt {attempt + 1} failed for server {server_id}: {e}"
                            )
                            await asyncio.sleep((attempt + 1) * 1.0)
                        else:
                            raise e

                logger.info(
                    f"Successfully synchronized server files after attaching group {group_id} to server {server_id}"
                )
            except Exception as sync_error:
                logger.error(
                    f"Failed to synchronize server files after attaching group {group_id} to server {server_id}: {sync_error}"
                )
                # Log the sync failure but don't rollback the attachment
                logger.warning(
                    f"Group {group_id} was successfully attached to server {server_id} but server file sync failed. "
                    f"Manual file sync may be required. Error: {sync_error}"
                )

            # Send real-time commands for attachment
            try:
                await real_time_server_commands.handle_group_change_commands(
                    server_id, Path(server.directory_path), group.type, "attach"
                )
            except Exception as cmd_error:
                logger.warning(f"Failed to send real-time commands after attaching group {group_id} to server {server_id}: {cmd_error}")

            # Create audit log after successful sync
            audit_log = AuditLog.create_log(
                action="group_attached_to_server",
                resource_type="server_group",
                user_id=user.id,
                details={
                    "server_id": server_id,
                    "group_id": group_id,
                    "group_name": group.name,
                    "group_type": group.type.value,
                    "priority": priority,
                },
            )
            self.db.add(audit_log)
            self.db.commit()

        except HTTPException:
            # Re-raise HTTP exceptions (like sync failures)
            raise
        except Exception as e:
            # Rollback any database changes on unexpected errors
            self.db.rollback()
            logger.error(f"Failed to attach group {group_id} to server {server_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to attach group to server: {e}",
            ) from e

    async def detach_group_from_server(
        self, user: User, server_id: int, group_id: int
    ) -> None:
        """Detach a group from a server"""
        # Check server access
        server = self.db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        self.access_service.check_server_access(user, server)

        # Check group access
        group = self.get_group_by_id(user, group_id)

        # Find attachment
        server_group = (
            self.db.query(ServerGroup)
            .filter(ServerGroup.server_id == server_id, ServerGroup.group_id == group_id)
            .first()
        )

        if not server_group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group is not attached to this server",
            )

        # Create audit log before deletion
        audit_log = AuditLog.create_log(
            action="group_detached_from_server",
            resource_type="server_group",
            user_id=user.id,
            details={
                "server_id": server_id,
                "group_id": group_id,
                "group_name": group.name,
                "group_type": group.type.value,
            },
        )
        self.db.add(audit_log)

        # Remove attachment
        self.db.delete(server_group)
        self.db.commit()

        # Update server files after detachment
        await self.file_service.update_server_files(server_id)

        # Send real-time commands for detachment
        try:
            await real_time_server_commands.handle_group_change_commands(
                server_id, Path(server.directory_path), group.type, "detach"
            )
        except Exception as cmd_error:
            logger.warning(f"Failed to send real-time commands after detaching group {group_id} from server {server_id}: {cmd_error}")

    def get_server_groups(self, user: User, server_id: int) -> List[Dict[str, Any]]:
        """Get all groups attached to a server"""
        # Check server access
        server = self.db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        self.access_service.check_server_access(user, server)

        # Get attached groups with details
        result = (
            self.db.query(ServerGroup, Group)
            .join(Group, ServerGroup.group_id == Group.id)
            .filter(ServerGroup.server_id == server_id)
            .order_by(ServerGroup.priority.desc(), Group.name)
            .all()
        )

        groups = []
        for server_group, group in result:
            # Optimize player count calculation - avoid loading full player data
            player_count = 0
            if group.players:
                try:
                    import json

                    players_data = (
                        json.loads(group.players)
                        if isinstance(group.players, str)
                        else group.players
                    )
                    player_count = len(players_data) if players_data else 0
                except (json.JSONDecodeError, TypeError):
                    player_count = 0

            groups.append(
                {
                    "id": group.id,
                    "name": group.name,
                    "description": group.description,
                    "type": group.type.value,
                    "priority": server_group.priority,
                    "attached_at": server_group.attached_at.isoformat(),
                    "player_count": player_count,
                }
            )

        return groups

    def get_group_servers(self, user: User, group_id: int) -> List[Dict[str, Any]]:
        """Get all servers that have this group attached"""
        # Validate group access
        self.get_group_by_id(user, group_id)

        # Get servers with this group attached
        result = (
            self.db.query(ServerGroup, Server)
            .join(Server, ServerGroup.server_id == Server.id)
            .filter(ServerGroup.group_id == group_id)
            .order_by(Server.name)
            .all()
        )

        servers = []
        for server_group, server in result:
            # Check if user has access to this server
            if user.role == Role.admin or server.owner_id == user.id:
                servers.append(
                    {
                        "id": server.id,
                        "name": server.name,
                        "status": server.status.value,
                        "priority": server_group.priority,
                        "attached_at": server_group.attached_at.isoformat(),
                    }
                )

        return servers
