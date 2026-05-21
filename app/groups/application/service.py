"""Group service (application layer).

Orchestrates group CRUD, player management, and server attachments
through the `GroupsUnitOfWork`. Depends only on the groups domain Ports
and the minimal cross-domain `ServerReadPort` + `AuditWriter`. Must not
import from `adapters/`, `api/`, FastAPI, or SQLAlchemy.

Authorization helpers (`_check_group_access`,
`_can_manage_server_groups`) are pure functions at module scope so
tests can exercise them without instantiating the service.
"""

import logging
from pathlib import Path
from typing import Any, List, Optional

from app.audit.domain.entities import AuditEventCommand
from app.audit.domain.ports import AuditWriter
from app.groups.application.file_syncer import GroupFileSyncer
from app.groups.domain.entities import (
    AttachedGroupView,
    AttachedServerView,
    AttachServerGroupCommand,
    CreateGroupCommand,
    GroupEntity,
    GroupListSpec,
    UpdateGroupCommand,
)
from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupHasAttachmentsError,
    GroupNotFoundError,
    ServerGroupAttachmentExistsError,
    ServerGroupAttachmentNotFoundError,
    ServerNotFoundForAttachment,
)
from app.groups.domain.ports import GroupsUnitOfWork
from app.groups.models import GroupType
from app.servers.domain.entities import ServerEntity
from app.servers.domain.ports import ServerReadPort

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-function authorization helpers
# ---------------------------------------------------------------------------


def _check_group_access(viewer_id: int, group: GroupEntity) -> None:
    """Phase 1: all authenticated viewers may access all groups.

    Kept as a stub function so when visibility hardens (Phase 2) the
    change is local to this helper rather than scattered across each
    use case.
    """
    return None


def _can_manage_server_groups(
    viewer_id: int, viewer_is_admin: bool, server: ServerEntity
) -> bool:
    """Whether viewer may attach/detach groups to/from a server.

    Special rule (legacy contract): admins OR the server owner.
    """
    return viewer_is_admin or server.owner_id == viewer_id


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GroupService:
    """Use cases over the group catalogue, players, and attachments.

    Receives a `GroupsUnitOfWork`, a `ServerReadPort`, an
    `AuditWriter`, and a `GroupFileSyncer` via constructor injection.
    Each public method opens a fresh UoW (one transaction) per logical
    operation; the SQLAlchemy adapter shares the underlying session
    across entries in `db=session` mode (see `SqlAlchemyGroupsUnitOfWork`
    for the re-entry semantics).
    """

    def __init__(
        self,
        uow: GroupsUnitOfWork,
        server_read: ServerReadPort,
        audit: AuditWriter,
        file_syncer: GroupFileSyncer,
    ):
        self._uow = uow
        self._server_read = server_read
        self._audit = audit
        self._file_syncer = file_syncer

    # ===================
    # Group CRUD
    # ===================

    async def create_group(
        self,
        actor_id: int,
        name: str,
        group_type: GroupType,
        description: Optional[str] = None,
    ) -> GroupEntity:
        """Create a new group, raising on (owner, name) collision."""
        async with self._uow as uow:
            existing = await uow.groups.find_by_owner_and_name(actor_id, name)
            if existing is not None:
                raise GroupAlreadyExistsError("Group with this name already exists")
            entity = await uow.groups.add(
                CreateGroupCommand(
                    name=name,
                    type=group_type,
                    owner_id=actor_id,
                    description=description,
                )
            )
            await uow.commit()

        # Fire-and-forget audit AFTER commit (post-#238 pattern; see
        # `SqlAlchemyAuditWriter` for the transaction-isolation rationale).
        self._audit.record(
            AuditEventCommand(
                action="group_created",
                resource_type="group",
                resource_id=entity.id,
                user_id=actor_id,
                details={"name": name, "type": group_type.value},
            )
        )
        return entity

    async def list_groups(
        self,
        actor_id: int,
        group_type: Optional[GroupType] = None,
    ) -> List[GroupEntity]:
        """List groups visible to the viewer (Phase 1 = all groups)."""
        spec = GroupListSpec(type=group_type)
        async with self._uow as uow:
            return await uow.groups.list(spec)

    async def get_group(self, actor_id: int, group_id: int) -> GroupEntity:
        """Get a group by id, enforcing access rules.

        Raises `GroupNotFoundError` if no row matches.
        """
        async with self._uow as uow:
            group = await uow.groups.get(group_id)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        _check_group_access(actor_id, group)
        return group

    async def update_group(
        self,
        actor_id: int,
        group_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> GroupEntity:
        """Update group name / description.

        Preserves the legacy "no-op short-circuit": if the caller did
        not request a name change, no rename-collision check fires and
        no audit entry is emitted under the rename action — matches the
        existing behaviour exactly.
        """
        async with self._uow as uow:
            existing = await uow.groups.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, existing)

            old_name = existing.name
            old_description = existing.description

            # Rename collision check fires only if the name actually changed
            if name is not None and name != existing.name:
                duplicate = await uow.groups.find_by_owner_and_name(actor_id, name)
                if duplicate is not None and duplicate.id != group_id:
                    raise GroupAlreadyExistsError("Group with this name already exists")

            command = UpdateGroupCommand(name=name, description=description)
            updated = await uow.groups.update(group_id, command)
            assert updated is not None  # get() succeeded just above
            await uow.commit()

        self._audit.record(
            AuditEventCommand(
                action="group_updated",
                resource_type="group",
                resource_id=updated.id,
                user_id=actor_id,
                details={
                    "old_values": {
                        "name": old_name,
                        "description": old_description,
                    },
                    "new_values": {
                        "name": updated.name,
                        "description": updated.description,
                    },
                },
            )
        )
        return updated

    async def delete_group(self, actor_id: int, group_id: int) -> None:
        """Delete a group; refuses if any servers are attached."""
        async with self._uow as uow:
            existing = await uow.groups.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, existing)

            attached = await uow.server_groups.count_for_group(group_id)
            if attached > 0:
                raise GroupHasAttachmentsError(
                    "Cannot delete group that is attached to servers"
                )

            await uow.groups.delete(group_id)
            await uow.commit()

        self._audit.record(
            AuditEventCommand(
                action="group_deleted",
                resource_type="group",
                resource_id=group_id,
                user_id=actor_id,
                details={"name": existing.name, "type": existing.type.value},
            )
        )

    # ===================
    # Player management
    # ===================

    async def add_player(
        self,
        actor_id: int,
        group_id: int,
        uuid: Optional[str] = None,
        username: Optional[str] = None,
    ) -> GroupEntity:
        """Add (or upsert) a player into a group.

        UUID/username resolution falls back to the Mojang API, with
        an offline-UUID fallback if Mojang is unavailable. After the
        DB commit, file sync runs with retry; sync failures are
        logged but do **not** roll back the player addition (legacy
        contract preserved).
        """
        if not uuid and not username:
            raise ValueError("Either uuid or username must be provided")

        # Resolve missing field via Mojang (legacy behaviour). Local
        # import: keeps the module load graph small and matches the
        # legacy code shape.
        if uuid and not username:
            from app.services.minecraft_api_service import MinecraftAPIService

            username = await MinecraftAPIService.get_username_from_uuid(uuid)
            if not username:
                username = uuid[:8]
        elif username and not uuid:
            from app.services.minecraft_api_service import MinecraftAPIService

            uuid = await MinecraftAPIService.get_uuid_from_username(username)
            if not uuid:
                uuid = MinecraftAPIService.generate_offline_uuid(username)

        assert uuid is not None
        assert username is not None

        async with self._uow as uow:
            existing = await uow.groups.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, existing)

            entity = await uow.groups.add_player(group_id, uuid, username)
            await uow.commit()

        # File sync with retry — failures logged, never rolled back
        try:
            await self._file_syncer.update_all_affected_servers_with_retry(group_id)
            logger.info(
                f"Successfully synchronized server files after adding player "
                f"{username} to group {group_id}"
            )
        except Exception as sync_error:
            logger.error(
                f"Failed to synchronize server files after adding player "
                f"{username} to group {group_id}: {sync_error}"
            )
            logger.warning(
                f"Player {username} was successfully added to group "
                f"{group_id} but server file sync failed. Manual file sync "
                f"may be required. Error: {sync_error}"
            )

        # Best-effort real-time commands
        await self._broadcast_player_change(
            group_id, entity.type, "player_add", removed_players=None
        )

        self._audit.record(
            AuditEventCommand(
                action="player_added_to_group",
                resource_type="group",
                resource_id=group_id,
                user_id=actor_id,
                details={"player_uuid": uuid, "player_username": username},
            )
        )
        return entity

    async def remove_player(self, actor_id: int, group_id: int, uuid: str) -> GroupEntity:
        """Remove a player from a group.

        Raises `GroupNotFoundError` / `PlayerNotFoundInGroup`. File sync
        afterwards is best-effort, as with `add_player`.
        """
        removed_player_info: Optional[dict[str, Any]] = None

        async with self._uow as uow:
            existing = await uow.groups.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, existing)

            # Capture player info before removal for real-time commands
            for player in existing.players:
                if player.get("uuid") == uuid:
                    removed_player_info = dict(player)
                    break

            # raises PlayerNotFoundInGroup if absent
            entity = await uow.groups.remove_player(group_id, uuid)
            await uow.commit()

        try:
            await self._file_syncer.update_all_affected_servers_with_retry(group_id)
            logger.info(
                f"Successfully synchronized server files after removing "
                f"player {uuid} from group {group_id}"
            )
        except Exception as sync_error:
            logger.error(
                f"Failed to synchronize server files after removing player "
                f"{uuid} from group {group_id}: {sync_error}"
            )
            logger.warning(
                f"Player {uuid} was successfully removed from group "
                f"{group_id} but server file sync failed. Manual file sync "
                f"may be required. Error: {sync_error}"
            )

        await self._broadcast_player_change(
            group_id,
            entity.type,
            "player_remove",
            removed_players=([removed_player_info] if removed_player_info else None),
        )

        self._audit.record(
            AuditEventCommand(
                action="player_removed_from_group",
                resource_type="group",
                resource_id=group_id,
                user_id=actor_id,
                details={"player_uuid": uuid},
            )
        )
        return entity

    # ===================
    # Attachments
    # ===================

    async def attach_group_to_server(
        self,
        actor_id: int,
        actor_is_admin: bool,
        server_id: int,
        group_id: int,
        priority: int = 0,
    ) -> None:
        """Attach a group to a server (admin or server-owner only)."""
        server = await self._server_read.get(server_id)
        if server is None:
            raise ServerNotFoundForAttachment(f"Server {server_id} not found")

        # NB: access check before group lookup to avoid leaking existence to
        # non-owners (legacy parity).
        if not _can_manage_server_groups(actor_id, actor_is_admin, server):
            raise GroupAccessError(
                "Only server owners and admins can attach groups to servers"
            )

        async with self._uow as uow:
            existing = await uow.groups.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, existing)

            already = await uow.server_groups.find(server_id, group_id)
            if already is not None:
                raise ServerGroupAttachmentExistsError(
                    "Group is already attached to this server"
                )

            await uow.server_groups.attach(
                AttachServerGroupCommand(
                    server_id=server_id,
                    group_id=group_id,
                    priority=priority,
                )
            )
            await uow.commit()

        # File sync (single server, with retry) — failures logged, not raised
        try:
            await self._file_syncer.update_single_server_with_retry(server_id)
            logger.info(
                f"Successfully synchronized server files after attaching "
                f"group {group_id} to server {server_id}"
            )
        except Exception as sync_error:
            logger.error(
                f"Failed to synchronize server files after attaching group "
                f"{group_id} to server {server_id}: {sync_error}"
            )
            logger.warning(
                f"Group {group_id} was successfully attached to server "
                f"{server_id} but server file sync failed. Manual file sync "
                f"may be required. Error: {sync_error}"
            )

        # Best-effort real-time commands
        try:
            await self._file_syncer._real_time_commands.handle_group_change_commands(
                server_id, Path(server.directory_path), existing.type, "attach"
            )
        except Exception as cmd_error:
            logger.warning(
                f"Failed to send real-time commands after attaching group "
                f"{group_id} to server {server_id}: {cmd_error}"
            )

        self._audit.record(
            AuditEventCommand(
                action="group_attached_to_server",
                resource_type="server_group",
                resource_id=None,
                user_id=actor_id,
                details={
                    "server_id": server_id,
                    "group_id": group_id,
                    "group_name": existing.name,
                    "group_type": existing.type.value,
                    "priority": priority,
                },
            )
        )

    async def detach_group_from_server(
        self,
        actor_id: int,
        actor_is_admin: bool,
        server_id: int,
        group_id: int,
    ) -> None:
        """Detach a group from a server (admin or server-owner only)."""
        server = await self._server_read.get(server_id)
        if server is None:
            raise ServerNotFoundForAttachment(f"Server {server_id} not found")

        if not _can_manage_server_groups(actor_id, actor_is_admin, server):
            raise GroupAccessError(
                "Only server owners and admins can detach groups from servers"
            )

        # Pre-fetch removed-players info BEFORE the detach (op groups
        # need this list for the deop broadcast). Carries through to
        # the real-time command after commit.
        removed_players: Optional[List[dict[str, Any]]] = None

        async with self._uow as uow:
            existing = await uow.groups.get(group_id)
            if existing is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, existing)

            attachment = await uow.server_groups.find(server_id, group_id)
            if attachment is None:
                raise ServerGroupAttachmentNotFoundError(
                    "Group is not attached to this server"
                )

            if existing.type == GroupType.op:
                removed_players = [
                    {"username": p["username"], "uuid": p["uuid"]}
                    for p in existing.players
                ]

            await uow.server_groups.detach(server_id, group_id)
            await uow.commit()

        # File sync (single server, no retry — legacy parity)
        try:
            await self._file_syncer.update_server_files(server_id)
        except Exception as sync_error:
            logger.error(
                f"Failed to synchronize server files after detaching group "
                f"{group_id} from server {server_id}: {sync_error}"
            )

        try:
            await self._file_syncer._real_time_commands.handle_group_change_commands(
                server_id,
                Path(server.directory_path),
                existing.type,
                "detach",
                removed_players,
            )
        except Exception as cmd_error:
            logger.warning(
                f"Failed to send real-time commands after detaching group "
                f"{group_id} from server {server_id}: {cmd_error}"
            )

        self._audit.record(
            AuditEventCommand(
                action="group_detached_from_server",
                resource_type="server_group",
                resource_id=None,
                user_id=actor_id,
                details={
                    "server_id": server_id,
                    "group_id": group_id,
                    "group_name": existing.name,
                    "group_type": existing.type.value,
                },
            )
        )

    async def get_server_groups(
        self, actor_id: int, server_id: int
    ) -> List[AttachedGroupView]:
        """Return groups attached to a server, sorted by priority desc."""
        server = await self._server_read.get(server_id)
        if server is None:
            raise ServerNotFoundForAttachment(f"Server {server_id} not found")
        async with self._uow as uow:
            return await uow.server_groups.list_attachments_for_server(server_id)

    async def get_group_servers(
        self, actor_id: int, group_id: int
    ) -> List[AttachedServerView]:
        """Return servers attached to a group, sorted by name."""
        async with self._uow as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError(f"Group {group_id} not found")
            _check_group_access(actor_id, group)
            return await uow.server_groups.list_attachments_for_group(group_id)

    # ===================
    # Helpers
    # ===================

    async def _broadcast_player_change(
        self,
        group_id: int,
        group_type: GroupType,
        change_type: str,
        removed_players: Optional[List[Optional[dict[str, Any]]]] = None,
    ) -> None:
        """Fan-out real-time commands across every server the group is
        attached to. Best-effort: failures are logged but never raised.
        """
        try:
            # NB: re-enters the request-scoped UoW (db=session mode);
            # commands fan out after exit by design.
            async with self._uow as uow:
                attached = await uow.server_groups.list_server_dirs_for_group(group_id)
            for server_id, directory_path in attached:
                await self._file_syncer._real_time_commands.handle_group_change_commands(
                    server_id,
                    Path(directory_path),
                    group_type,
                    change_type,
                    removed_players=removed_players,
                )
        except Exception as cmd_error:
            logger.warning(
                f"Failed to send real-time commands for group {group_id} "
                f"({change_type}): {cmd_error}"
            )
