"""SQLAlchemy implementations of `GroupRepository` and
`ServerGroupRepository`.

The adapters are the only layer that knows about the SQLAlchemy ORM
and the `Group` / `ServerGroup` / `Server` columns; they convert ORM
rows to/from domain entities so the application layer never sees ORM
types.

Per the UnitOfWork pattern, repository methods **do not commit**. They
stage changes on the session and rely on the surrounding
`SqlAlchemyGroupsUnitOfWork` (or the caller) to commit.

Cross-domain JOINs against `Server` are intentionally kept inside this
adapter rather than dispatched through `ServerReadPort.list_for_ids`:
the alternative would issue one query per attached server (N+1) for
the attachment-list endpoints. See `docs/ARCHITECTURE.md` §4.3 — the
adapter layer is allowed to touch the ORM directly; only the
**application** layer is forbidden from doing so.
"""

import json
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.groups.domain.entities import (
    AttachedGroupView,
    AttachedServerView,
    AttachServerGroupCommand,
    CreateGroupCommand,
    GroupEntity,
    GroupListSpec,
    ServerGroupEntity,
    UpdateGroupCommand,
)
from app.groups.domain.exceptions import (
    GroupNotFoundError,
    PlayerNotFoundInGroup,
)
from app.groups.models import Group, ServerGroup
from app.servers.models import Server


def _group_to_entity(row: Group) -> GroupEntity:
    """Convert an ORM row into a domain entity."""
    return GroupEntity(
        id=row.id,
        name=row.name,
        description=row.description,
        type=row.type,
        players=row.get_players(),
        owner_id=row.owner_id,
        is_template=bool(row.is_template),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _server_group_to_entity(row: ServerGroup) -> ServerGroupEntity:
    return ServerGroupEntity(
        id=row.id,
        server_id=row.server_id,
        group_id=row.group_id,
        priority=row.priority,
        attached_at=row.attached_at,
    )


def _player_count(group: Group) -> int:
    """Cheap player-count over the raw JSON without materialising the list.

    Mirrors the legacy `GroupService.get_server_groups` optimisation:
    avoids re-parsing every player dict when only the count is needed.
    """
    raw = group.players
    if raw is None:
        return 0
    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return len(parsed) if parsed else 0
        return len(raw)
    except (json.JSONDecodeError, TypeError):
        return 0


class SqlAlchemyGroupRepository:
    """SQLAlchemy-backed implementation of the groups persistence Port."""

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Reads
    # ===================

    async def get(self, group_id: int) -> Optional[GroupEntity]:
        row = self.db.query(Group).filter(Group.id == group_id).first()
        return _group_to_entity(row) if row else None

    async def find_by_owner_and_name(
        self, owner_id: int, name: str
    ) -> Optional[GroupEntity]:
        row = (
            self.db.query(Group)
            .filter(Group.owner_id == owner_id, Group.name == name)
            .first()
        )
        return _group_to_entity(row) if row else None

    async def list(self, spec: GroupListSpec) -> List[GroupEntity]:
        # Phase 1 visibility: all authenticated users see all groups.
        query = self.db.query(Group)
        if spec.type is not None:
            query = query.filter(Group.type == spec.type)
        return [_group_to_entity(r) for r in query.all()]

    # ===================
    # Writes
    # ===================

    async def add(self, command: CreateGroupCommand) -> GroupEntity:
        row = Group(
            name=command.name,
            description=command.description,
            type=command.type,
            players=[],
            owner_id=command.owner_id,
        )
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row, attribute_names=["created_at", "updated_at"])
        return _group_to_entity(row)

    async def update(
        self, group_id: int, command: UpdateGroupCommand
    ) -> Optional[GroupEntity]:
        row = self.db.query(Group).filter(Group.id == group_id).first()
        if row is None:
            return None
        for field, value in command.applied_fields().items():
            setattr(row, field, value)
        self.db.flush()
        return _group_to_entity(row)

    async def delete(self, group_id: int) -> bool:
        row = self.db.query(Group).filter(Group.id == group_id).first()
        if row is None:
            return False
        self.db.delete(row)
        return True

    # ===================
    # Players (sub-aggregate)
    # ===================

    async def add_player(self, group_id: int, uuid: str, username: str) -> GroupEntity:
        row = self.db.query(Group).filter(Group.id == group_id).first()
        if row is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        # Reuse the model's idempotent helper: it handles upsert on
        # `(uuid)` and calls `flag_modified` so SQLAlchemy detects the
        # JSON-list mutation.
        row.add_player(uuid, username)
        self.db.flush()
        return _group_to_entity(row)

    async def remove_player(self, group_id: int, uuid: str) -> GroupEntity:
        row = self.db.query(Group).filter(Group.id == group_id).first()
        if row is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        removed = row.remove_player(uuid)
        if not removed:
            raise PlayerNotFoundInGroup(
                f"Player {uuid} is not a member of group {group_id}"
            )
        self.db.flush()
        return _group_to_entity(row)


class SqlAlchemyServerGroupRepository:
    """SQLAlchemy-backed implementation of the server-group Port."""

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Reads
    # ===================

    async def find(self, server_id: int, group_id: int) -> Optional[ServerGroupEntity]:
        row = (
            self.db.query(ServerGroup)
            .filter(
                ServerGroup.server_id == server_id,
                ServerGroup.group_id == group_id,
            )
            .first()
        )
        return _server_group_to_entity(row) if row else None

    async def count_for_group(self, group_id: int) -> int:
        return self.db.query(ServerGroup).filter(ServerGroup.group_id == group_id).count()

    async def list_server_ids_for_group(self, group_id: int) -> List[int]:
        rows = (
            self.db.query(ServerGroup.server_id)
            .filter(ServerGroup.group_id == group_id)
            .all()
        )
        return [server_id for (server_id,) in rows]

    async def list_groups_for_server(self, server_id: int) -> List[GroupEntity]:
        rows = (
            self.db.query(Group)
            .join(ServerGroup, Group.id == ServerGroup.group_id)
            .filter(ServerGroup.server_id == server_id)
            .order_by(ServerGroup.priority.desc())
            .all()
        )
        return [_group_to_entity(r) for r in rows]

    async def list_server_dirs_for_group(self, group_id: int) -> List[Tuple[int, str]]:
        # Cross-domain JOIN — see module docstring for rationale.
        # Soft-deleted servers are NOT filtered here: the legacy
        # broadcaster sends commands to whatever was attached at the
        # time, and #228 will revisit this filtering when the servers
        # domain is properly Port-ified.
        rows = (
            self.db.query(ServerGroup.server_id, Server.directory_path)
            .join(Server, ServerGroup.server_id == Server.id)
            .filter(ServerGroup.group_id == group_id)
            .all()
        )
        return [(server_id, directory_path) for server_id, directory_path in rows]

    async def list_attachments_for_server(
        self, server_id: int
    ) -> List[AttachedGroupView]:
        rows = (
            self.db.query(ServerGroup, Group)
            .join(Group, ServerGroup.group_id == Group.id)
            .filter(ServerGroup.server_id == server_id)
            .order_by(ServerGroup.priority.desc(), Group.name)
            .all()
        )
        return [
            AttachedGroupView(
                id=group.id,
                name=group.name,
                description=group.description,
                type=group.type,
                priority=server_group.priority,
                attached_at=server_group.attached_at,
                player_count=_player_count(group),
            )
            for server_group, group in rows
        ]

    async def list_attachments_for_group(self, group_id: int) -> List[AttachedServerView]:
        # Legacy parity: does NOT filter `~Server.is_deleted` (see
        # PR description). #228 reconsiders this filter alongside the
        # server-domain refactor.
        rows = (
            self.db.query(ServerGroup, Server)
            .join(Server, ServerGroup.server_id == Server.id)
            .filter(ServerGroup.group_id == group_id)
            .order_by(Server.name)
            .all()
        )
        return [
            AttachedServerView(
                id=server.id,
                name=server.name,
                status=server.status,
                priority=server_group.priority,
                attached_at=server_group.attached_at,
            )
            for server_group, server in rows
        ]

    # ===================
    # Writes
    # ===================

    async def attach(self, command: AttachServerGroupCommand) -> ServerGroupEntity:
        row = ServerGroup(
            server_id=command.server_id,
            group_id=command.group_id,
            priority=command.priority,
        )
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row, attribute_names=["attached_at"])
        return _server_group_to_entity(row)

    async def detach(self, server_id: int, group_id: int) -> bool:
        row = (
            self.db.query(ServerGroup)
            .filter(
                ServerGroup.server_id == server_id,
                ServerGroup.group_id == group_id,
            )
            .first()
        )
        if row is None:
            return False
        self.db.delete(row)
        return True
