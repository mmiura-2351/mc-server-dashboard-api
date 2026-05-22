"""Port (Protocol) definitions for the visibility domain.

Per `docs/ARCHITECTURE.md` §4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types
crossing these Protocols are pure domain entities defined in
`entities.py`.

Two Ports are defined:

- `VisibilityRepository`: persistence Port for the
  `ResourceVisibility` + `ResourceUserAccess` aggregates plus the
  cross-domain helpers used by the migration service (listing
  servers/groups that lack a visibility row).
- `VisibilityUnitOfWork`: transactional boundary Port. Application
  code wraps a set of repository calls in `async with uow:` and calls
  `await uow.commit()` to finalise.

Cross-domain reads against `Server` and `Group` for the migration
helpers are intentionally kept inside this Port rather than dispatched
through a `ServerReadPort` / `GroupReadPort`: the alternative would
issue per-row lookups to detect what is *not* in the visibility table.
See `docs/ARCHITECTURE.md` §4.3 — the adapter layer is allowed to touch
the ORM directly; only the **application** layer is forbidden.
"""

from types import TracebackType
from typing import Dict, List, Optional, Protocol

from app.core.visibility.domain.entities import (
    GrantAccessCommand,
    ResourceUserAccessEntity,
    ResourceVisibilityEntity,
    SetVisibilityCommand,
)
from app.core.visibility.models import ResourceType, VisibilityType


class VisibilityRepository(Protocol):
    """Persistence Port for the visibility aggregate.

    Concrete implementations: `SqlAlchemyVisibilityRepository`
    (production), `FakeVisibilityRepository` (unit tests).

    Repository methods **do not commit**. Wrap calls in a
    `VisibilityUnitOfWork` context and call `await uow.commit()` once
    you are done.
    """

    # ----- Reads -----

    async def get(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[ResourceVisibilityEntity]: ...

    async def get_user_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
    ) -> Optional[ResourceUserAccessEntity]: ...

    # ----- Writes -----

    async def set(self, command: SetVisibilityCommand) -> ResourceVisibilityEntity:
        """Upsert a visibility configuration row.

        If a row already exists for `(resource_type, resource_id)` it is
        updated in place. When the new `visibility_type` is anything
        other than `SPECIFIC_USERS`, all attached `ResourceUserAccess`
        grants are cleared to match the legacy
        `set_resource_visibility` behaviour.
        """
        ...

    async def grant_access(self, command: GrantAccessCommand) -> ResourceUserAccessEntity:
        """Insert a per-user access grant.

        Raises if the target resource has no visibility row, if the row
        is not `SPECIFIC_USERS`, or if the grant already exists. The
        application layer translates these into `HTTPException`s to
        preserve the legacy router contract.
        """
        ...

    async def revoke_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
    ) -> bool:
        """Delete a per-user access grant.

        Returns ``True`` when a grant was deleted, ``False`` when the
        resource had no visibility row or the grant did not exist.
        """
        ...

    # ----- Bulk / migration helpers (cross-domain reads kept in adapter) -----

    async def list_missing_server_ids(self) -> List[int]:
        """Return ids of `Server` rows that have no visibility config."""
        ...

    async def list_missing_group_ids(self) -> List[int]:
        """Return ids of `Group` rows that have no visibility config."""
        ...

    async def add_many_public(
        self,
        resource_type: ResourceType,
        resource_ids: List[int],
    ) -> int:
        """Stage `PUBLIC` visibility rows for each id.

        Returns the number of rows staged. The caller commits via the
        surrounding UoW.
        """
        ...

    async def count_resources(self, resource_type: ResourceType) -> int:
        """Total live `Server` / `Group` rows of the given type."""
        ...

    async def count_visibility(self, resource_type: ResourceType) -> int:
        """Visibility rows of the given resource type."""
        ...

    async def count_by_visibility_type(
        self,
    ) -> Dict[ResourceType, Dict[VisibilityType, int]]:
        """Distribution of visibility rows across (resource_type, visibility_type).

        Only entries with non-zero counts are included.
        """
        ...


class VisibilityUnitOfWork(Protocol):
    """Transactional boundary Port for the visibility domain."""

    visibility: VisibilityRepository

    async def __aenter__(self) -> "VisibilityUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


__all__ = [
    "VisibilityRepository",
    "VisibilityUnitOfWork",
]
