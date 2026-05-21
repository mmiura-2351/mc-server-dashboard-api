"""In-memory fakes for the groups domain Ports.

`FakeGroupRepository`, `FakeServerGroupRepository`, and
`FakeGroupsUnitOfWork` structurally implement the Protocols in
`app.groups.domain.ports`. They let unit tests exercise the groups
application service without a database.

`FakeServerReadPort` is reused from `tests.unit.files.fakes` — it
already implements both `get_directory_path` and `get`, so duplicating
it here would only risk drift. `FakeAuditWriter` is reused from
`tests.unit.audit.fakes`.
"""

from dataclasses import replace
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Dict, List, Optional, Tuple

from app.core.datetime_utils import utcnow
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
from app.groups.models import GroupType
from app.servers.models import ServerStatus


class FakeGroupRepository:
    """Dict-backed `GroupRepository` for unit tests."""

    def __init__(self) -> None:
        self._records: Dict[int, GroupEntity] = {}
        self._next_id = 1

    # ----- Reads -----

    async def get(self, group_id: int) -> Optional[GroupEntity]:
        return self._records.get(group_id)

    async def find_by_owner_and_name(
        self, owner_id: int, name: str
    ) -> Optional[GroupEntity]:
        for entity in self._records.values():
            if entity.owner_id == owner_id and entity.name == name:
                return entity
        return None

    async def list(self, spec: GroupListSpec) -> List[GroupEntity]:
        rows = list(self._records.values())
        if spec.type is not None:
            rows = [r for r in rows if r.type == spec.type]
        return rows

    # ----- Writes -----

    async def add(self, command: CreateGroupCommand) -> GroupEntity:
        now = utcnow()
        entity = GroupEntity(
            id=self._next_id,
            name=command.name,
            description=command.description,
            type=command.type,
            players=[],
            owner_id=command.owner_id,
            is_template=False,
            created_at=now,
            updated_at=now,
        )
        self._records[self._next_id] = entity
        self._next_id += 1
        return entity

    async def update(
        self, group_id: int, command: UpdateGroupCommand
    ) -> Optional[GroupEntity]:
        existing = self._records.get(group_id)
        if existing is None:
            return None
        updated = replace(existing, **command.applied_fields(), updated_at=utcnow())
        self._records[group_id] = updated
        return updated

    async def delete(self, group_id: int) -> bool:
        if group_id not in self._records:
            return False
        del self._records[group_id]
        return True

    # ----- Players -----

    async def add_player(
        self, group_id: int, uuid: str, username: str
    ) -> GroupEntity:
        existing = self._records.get(group_id)
        if existing is None:
            raise GroupNotFoundError(f"Group {group_id} not found")

        # Upsert by uuid (same semantics as Group.add_player on the ORM)
        new_players: List[Dict[str, Any]] = []
        found = False
        for player in existing.players:
            if player.get("uuid") == uuid:
                found = True
                # Update username if changed
                new_player = dict(player)
                new_player["username"] = username
                new_players.append(new_player)
            else:
                new_players.append(player)
        if not found:
            new_players.append(
                {
                    "uuid": uuid,
                    "username": username,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        updated = replace(existing, players=new_players, updated_at=utcnow())
        self._records[group_id] = updated
        return updated

    async def remove_player(self, group_id: int, uuid: str) -> GroupEntity:
        existing = self._records.get(group_id)
        if existing is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        remaining = [p for p in existing.players if p.get("uuid") != uuid]
        if len(remaining) == len(existing.players):
            raise PlayerNotFoundInGroup(
                f"Player {uuid} is not a member of group {group_id}"
            )
        updated = replace(existing, players=remaining, updated_at=utcnow())
        self._records[group_id] = updated
        return updated

    # ----- Test helpers -----

    def seed(self, entity: GroupEntity) -> GroupEntity:
        assert entity.id is not None
        self._records[entity.id] = entity
        self._next_id = max(self._next_id, entity.id + 1)
        return entity


class FakeServerGroupRepository:
    """Dict-backed `ServerGroupRepository` for unit tests."""

    def __init__(
        self,
        group_repo: Optional[FakeGroupRepository] = None,
    ) -> None:
        # Sharing a `FakeGroupRepository` lets `list_groups_for_server`
        # return live entities. If absent (tests that don't care about
        # cross-aggregate lookups), the relevant methods return empty.
        self._group_repo = group_repo
        self._records: Dict[int, ServerGroupEntity] = {}
        self._next_id = 1
        # `(server_id) -> (name, directory_path, status)` for the
        # cross-domain attached-server view.
        self._server_meta: Dict[int, Tuple[str, str, ServerStatus]] = {}

    # ----- Test helpers -----

    def register_server(
        self,
        server_id: int,
        name: str,
        directory_path: str,
        status: ServerStatus = ServerStatus.stopped,
    ) -> None:
        self._server_meta[server_id] = (name, directory_path, status)

    # ----- Reads -----

    async def find(
        self, server_id: int, group_id: int
    ) -> Optional[ServerGroupEntity]:
        for entity in self._records.values():
            if entity.server_id == server_id and entity.group_id == group_id:
                return entity
        return None

    async def count_for_group(self, group_id: int) -> int:
        return sum(1 for e in self._records.values() if e.group_id == group_id)

    async def list_server_ids_for_group(self, group_id: int) -> List[int]:
        return [e.server_id for e in self._records.values() if e.group_id == group_id]

    async def list_groups_for_server(self, server_id: int) -> List[GroupEntity]:
        if self._group_repo is None:
            return []
        attached = [e for e in self._records.values() if e.server_id == server_id]
        attached.sort(key=lambda e: e.priority, reverse=True)
        out: List[GroupEntity] = []
        for sg in attached:
            entity = self._group_repo._records.get(sg.group_id)
            if entity is not None:
                out.append(entity)
        return out

    async def list_server_dirs_for_group(
        self, group_id: int
    ) -> List[Tuple[int, str]]:
        results: List[Tuple[int, str]] = []
        for e in self._records.values():
            if e.group_id != group_id:
                continue
            meta = self._server_meta.get(e.server_id)
            if meta is None:
                continue
            results.append((e.server_id, meta[1]))
        return results

    async def list_attachments_for_server(
        self, server_id: int
    ) -> List[AttachedGroupView]:
        if self._group_repo is None:
            return []
        rows = [e for e in self._records.values() if e.server_id == server_id]
        # priority desc, then name asc
        rows.sort(
            key=lambda e: (
                -e.priority,
                self._group_repo._records[e.group_id].name
                if e.group_id in self._group_repo._records
                else "",
            )
        )
        out: List[AttachedGroupView] = []
        for sg in rows:
            group = self._group_repo._records.get(sg.group_id)
            if group is None:
                continue
            out.append(
                AttachedGroupView(
                    id=group.id,
                    name=group.name,
                    description=group.description,
                    type=group.type,
                    priority=sg.priority,
                    attached_at=sg.attached_at or utcnow(),
                    player_count=len(group.players),
                )
            )
        return out

    async def list_attachments_for_group(
        self, group_id: int
    ) -> List[AttachedServerView]:
        rows = [e for e in self._records.values() if e.group_id == group_id]
        out: List[AttachedServerView] = []
        for sg in rows:
            meta = self._server_meta.get(sg.server_id)
            if meta is None:
                continue
            name, _dir, status = meta
            out.append(
                AttachedServerView(
                    id=sg.server_id,
                    name=name,
                    status=status,
                    priority=sg.priority,
                    attached_at=sg.attached_at or utcnow(),
                )
            )
        out.sort(key=lambda v: v.name)
        return out

    # ----- Writes -----

    async def attach(
        self, command: AttachServerGroupCommand
    ) -> ServerGroupEntity:
        entity = ServerGroupEntity(
            id=self._next_id,
            server_id=command.server_id,
            group_id=command.group_id,
            priority=command.priority,
            attached_at=utcnow(),
        )
        self._records[self._next_id] = entity
        self._next_id += 1
        return entity

    async def detach(self, server_id: int, group_id: int) -> bool:
        target_id: Optional[int] = None
        for rid, e in self._records.items():
            if e.server_id == server_id and e.group_id == group_id:
                target_id = rid
                break
        if target_id is None:
            return False
        del self._records[target_id]
        return True


class FakeGroupsUnitOfWork:
    """In-memory `GroupsUnitOfWork` for unit tests.

    Re-uses a single group-repo + server-group-repo across enters so
    test setup carries through into the code under test.

    **Caveat**: `rollback()` does NOT actually undo changes made to the
    in-memory stores — assert on the `rolled_back` counter or use
    hand-snapshotted state for before/after comparisons.
    """

    def __init__(
        self,
        groups: Optional[FakeGroupRepository] = None,
        server_groups: Optional[FakeServerGroupRepository] = None,
    ) -> None:
        self.groups: FakeGroupRepository = groups or FakeGroupRepository()
        self.server_groups: FakeServerGroupRepository = (
            server_groups or FakeServerGroupRepository(self.groups)
        )
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeGroupsUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


def make_group_entity(
    *,
    id: int,
    owner_id: int,
    name: str = "g",
    type: GroupType = GroupType.op,
    description: Optional[str] = None,
    players: Optional[List[Dict[str, Any]]] = None,
    is_template: bool = False,
) -> GroupEntity:
    """Convenience builder for tests."""
    now = utcnow()
    return GroupEntity(
        id=id,
        name=name,
        description=description,
        type=type,
        players=players if players is not None else [],
        owner_id=owner_id,
        is_template=is_template,
        created_at=now,
        updated_at=now,
    )


class RecordingRealTimeCommands:
    """Capture-and-no-op stand-in for `real_time_server_commands`.

    The application service and file syncer call several methods on
    the production singleton; this object records each call so tests
    can assert on side-effect dispatching without spinning up the
    Minecraft server manager.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...], Dict[str, Any]]] = []
        self.reload_whitelist_should_raise: Optional[Exception] = None
        self.sync_op_should_raise: Optional[Exception] = None
        self.handle_group_should_raise: Optional[Exception] = None

    async def reload_whitelist_if_running(self, server_id: int) -> bool:
        self.calls.append(("reload_whitelist_if_running", (server_id,), {}))
        if self.reload_whitelist_should_raise:
            raise self.reload_whitelist_should_raise
        return True

    async def sync_op_changes_if_running(
        self, server_id: int, server_path: Any
    ) -> bool:
        self.calls.append(
            ("sync_op_changes_if_running", (server_id, server_path), {})
        )
        if self.sync_op_should_raise:
            raise self.sync_op_should_raise
        return True

    async def handle_group_change_commands(
        self,
        server_id: int,
        server_path: Any,
        group_type: Any,
        change_type: str = "update",
        removed_players: Any = None,
    ) -> bool:
        self.calls.append(
            (
                "handle_group_change_commands",
                (server_id, server_path, group_type, change_type),
                {"removed_players": removed_players},
            )
        )
        if self.handle_group_should_raise:
            raise self.handle_group_should_raise
        return True
