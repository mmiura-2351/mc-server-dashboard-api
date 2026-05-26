"""Port (Protocol) definitions for the groups domain.

Per `docs/ARCHITECTURE.md` §4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types crossing
these Protocols are pure domain entities defined in `entities.py`.

Three Ports are defined:
- `GroupRepository`: persistence Port for the `Group` aggregate
  (group rows + the in-row `players` JSON list).
- `ServerGroupRepository`: persistence Port for the `ServerGroup`
  attachment aggregate. Split from `GroupRepository` because the two
  aggregates have independent transactional lifetimes and the
  attachment table joins cross-domain into `Server`.
- `GroupsUnitOfWork`: transactional boundary Port. Application code
  wraps a set of repository calls in `async with uow:` and calls
  `await uow.commit()` to finalise.
"""

from types import TracebackType
from typing import List, Optional, Protocol, Tuple

from app.groups.domain.entities import (
    AttachedGroupView,
    AttachedServerView,
    AttachServerGroupCommand,
    CreateGroupCommand,
    GroupEntity,
    GroupListPage,
    GroupListSpec,
    ServerGroupEntity,
    UpdateGroupCommand,
)


class GroupRepository(Protocol):
    """Persistence port for the `Group` aggregate.

    Concrete implementations: `SqlAlchemyGroupRepository` (production),
    `FakeGroupRepository` (unit tests).

    Repository methods **do not commit**. Wrap calls in a
    `GroupsUnitOfWork` context and call `await uow.commit()` once
    you are done.

    Player operations (`add_player`, `remove_player`) are exposed here
    rather than on a separate "players" Port because the JSON list is
    a true child of the group aggregate; modifying it is conceptually
    a single group write. Both methods raise on missing aggregates
    (group / player) so callers do not need a "did anything happen?"
    nullable check.
    """

    # ----- Reads -----

    async def get(self, group_id: int) -> Optional[GroupEntity]: ...

    async def find_by_owner_and_name(
        self, owner_id: int, name: str
    ) -> Optional[GroupEntity]: ...

    async def list(self, spec: GroupListSpec) -> GroupListPage: ...

    # ----- Writes -----

    async def add(self, command: CreateGroupCommand) -> GroupEntity: ...

    async def update(
        self, group_id: int, command: UpdateGroupCommand
    ) -> Optional[GroupEntity]: ...

    async def delete(self, group_id: int) -> bool: ...

    # ----- Player sub-aggregate -----

    async def add_player(self, group_id: int, uuid: str, username: str) -> GroupEntity:
        """Add (or upsert) a player into the group's player list.

        Raises `GroupNotFoundError` if no group with `group_id` exists.
        Idempotent on `(uuid)`: a second call with the same UUID
        updates the username without raising.
        """
        ...

    async def remove_player(self, group_id: int, uuid: str) -> GroupEntity:
        """Remove a player from the group's player list.

        Raises `GroupNotFoundError` if no group exists, or
        `PlayerNotFoundInGroup` if the UUID is not a member.
        """
        ...


class ServerGroupRepository(Protocol):
    """Persistence port for the `ServerGroup` attachment aggregate.

    Cross-domain JOINs against `Server` are intentionally kept here
    (rather than dispatched through `ServerReadPort.list_for_ids`) so
    the adapter can use a single SQL statement and avoid N+1 round
    trips. The "no N+1 via Port hopping" trade-off is revisited in
    Issue #228 once the servers domain is fully refactored.
    """

    # ----- Reads -----

    async def find(
        self, server_id: int, group_id: int
    ) -> Optional[ServerGroupEntity]: ...

    async def count_for_group(self, group_id: int) -> int: ...

    async def list_server_ids_for_group(self, group_id: int) -> List[int]: ...

    async def list_groups_for_server(self, server_id: int) -> List[GroupEntity]:
        """Return groups attached to `server_id`, ordered priority desc."""
        ...

    async def list_server_dirs_for_group(self, group_id: int) -> List[Tuple[int, str]]:
        """Return `(server_id, directory_path)` pairs for the group's
        attached servers, used by the real-time command broadcaster."""
        ...

    async def list_attachments_for_server(
        self, server_id: int
    ) -> List[AttachedGroupView]: ...

    async def list_attachments_for_group(
        self, group_id: int
    ) -> List[AttachedServerView]: ...

    # ----- Writes -----

    async def attach(self, command: AttachServerGroupCommand) -> ServerGroupEntity: ...

    async def detach(self, server_id: int, group_id: int) -> bool: ...


class GroupsUnitOfWork(Protocol):
    """Transactional boundary Port for the groups domain.

    Application services enter a UoW context, perform repository
    operations through the same session, then call `commit()` to
    persist atomically. Exiting the context without committing rolls
    back.
    """

    groups: GroupRepository
    server_groups: ServerGroupRepository

    async def __aenter__(self) -> "GroupsUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
