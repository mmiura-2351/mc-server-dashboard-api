from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.groups.models import Group, GroupType, ServerGroup
from app.servers.models import Server
from app.users.models import Role, User


class GroupService:
    def __init__(self, db: Session):
        self.db = db

    def _check_group_access(self, user: User, group: Group) -> None:
        """Check if user has access to the group"""
        if user.role != Role.admin and group.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this group",
            )

    def _check_server_access(self, user: User, server: Server) -> None:
        """Check if user has access to the server"""
        if user.role != Role.admin and server.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this server",
            )

    def create_group(
        self,
        user: User,
        name: str,
        group_type: GroupType,
        description: Optional[str] = None,
    ) -> Group:
        """Create a new group"""
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

        self._check_group_access(user, group)
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

    def add_player_to_group(
        self, user: User, group_id: int, uuid: str, username: str
    ) -> Group:
        """Add a player to a group"""
        group = self.get_group_by_id(user, group_id)

        # Add player using model method
        group.add_player(uuid, username)

        self.db.commit()
        self.db.refresh(group)

        # Create audit log
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

    def remove_player_from_group(self, user: User, group_id: int, uuid: str) -> Group:
        """Remove a player from a group"""
        group = self.get_group_by_id(user, group_id)

        # Remove player using model method
        removed = group.remove_player(uuid)

        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Player not found in group"
            )

        self.db.commit()
        self.db.refresh(group)

        # Create audit log
        audit_log = AuditLog.create_log(
            action="player_removed_from_group",
            resource_type="group",
            user_id=user.id,
            resource_id=group.id,
            details={"player_uuid": uuid},
        )
        self.db.add(audit_log)
        self.db.commit()

        return group

    def attach_group_to_server(
        self, user: User, server_id: int, group_id: int, priority: int = 0
    ) -> None:
        """Attach a group to a server"""
        # Check server access
        server = self.db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        self._check_server_access(user, server)

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

        self.db.add(server_group)
        self.db.commit()

        # Create audit log
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

    def detach_group_from_server(self, user: User, server_id: int, group_id: int) -> None:
        """Detach a group from a server"""
        # Check server access
        server = self.db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        self._check_server_access(user, server)

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

    def get_server_groups(self, user: User, server_id: int) -> List[Dict[str, Any]]:
        """Get all groups attached to a server"""
        # Check server access
        server = self.db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        self._check_server_access(user, server)

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
            groups.append(
                {
                    "id": group.id,
                    "name": group.name,
                    "description": group.description,
                    "type": group.type.value,
                    "priority": server_group.priority,
                    "attached_at": server_group.attached_at.isoformat(),
                    "player_count": len(group.get_players()),
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
