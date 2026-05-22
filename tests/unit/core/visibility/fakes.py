"""In-memory fakes for the visibility-domain Ports.

Structurally implement the Protocols in
`app.core.visibility.domain.ports` so unit tests can exercise the
application service without touching a real database.
"""

from dataclasses import replace
from datetime import datetime, timezone
from types import TracebackType
from typing import Dict, List, Optional

from app.core.visibility.domain.entities import (
    GrantAccessCommand,
    ResourceUserAccessEntity,
    ResourceVisibilityEntity,
    SetVisibilityCommand,
)
from app.core.visibility.domain.exceptions import (
    DuplicateGrantError,
    InvalidVisibilityTypeError,
    VisibilityNotFoundError,
)
from app.core.visibility.models import ResourceType, VisibilityType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FakeVisibilityRepository:
    """Dict-backed `VisibilityRepository` for unit tests."""

    def __init__(
        self,
        server_ids: Optional[List[int]] = None,
        group_ids: Optional[List[int]] = None,
    ) -> None:
        # `(resource_type, resource_id) -> ResourceVisibilityEntity`
        self._rows: Dict[tuple, ResourceVisibilityEntity] = {}
        self._next_visibility_id = 1
        self._next_access_id = 1
        # Cross-domain state used by the migration helpers; tests inject
        # whichever ids they want to pretend exist in the servers/groups
        # tables.
        self.server_ids: List[int] = list(server_ids or [])
        self.group_ids: List[int] = list(group_ids or [])

    # ----- Reads -----

    async def get(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[ResourceVisibilityEntity]:
        return self._rows.get((resource_type, resource_id))

    async def get_user_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
    ) -> Optional[ResourceUserAccessEntity]:
        row = self._rows.get((resource_type, resource_id))
        if row is None:
            return None
        for grant in row.granted_users:
            if grant.user_id == user_id:
                return grant
        return None

    # ----- Writes -----

    async def set(self, command: SetVisibilityCommand) -> ResourceVisibilityEntity:
        key = (command.resource_type, command.resource_id)
        existing = self._rows.get(key)
        now = _utcnow()
        if existing is None:
            entity = ResourceVisibilityEntity(
                id=self._next_visibility_id,
                resource_type=command.resource_type,
                resource_id=command.resource_id,
                visibility_type=command.visibility_type,
                role_restriction=command.role_restriction,
                created_at=now,
                updated_at=now,
                granted_users=[],
            )
            self._next_visibility_id += 1
        else:
            grants = list(existing.granted_users)
            if command.visibility_type != VisibilityType.SPECIFIC_USERS:
                grants = []
            entity = replace(
                existing,
                visibility_type=command.visibility_type,
                role_restriction=command.role_restriction,
                updated_at=now,
                granted_users=grants,
            )
        self._rows[key] = entity
        return entity

    async def grant_access(self, command: GrantAccessCommand) -> ResourceUserAccessEntity:
        key = (command.resource_type, command.resource_id)
        existing = self._rows.get(key)
        if existing is None:
            raise VisibilityNotFoundError("Resource visibility configuration not found")
        if existing.visibility_type != VisibilityType.SPECIFIC_USERS:
            raise InvalidVisibilityTypeError(
                "Resource must have SPECIFIC_USERS visibility type"
            )
        for grant in existing.granted_users:
            if grant.user_id == command.user_id:
                raise DuplicateGrantError("User already has access to this resource")
        new_grant = ResourceUserAccessEntity(
            id=self._next_access_id,
            resource_visibility_id=existing.id,
            user_id=command.user_id,
            granted_by_user_id=command.granted_by_user_id,
            created_at=_utcnow(),
        )
        self._next_access_id += 1
        updated = replace(
            existing,
            granted_users=[*existing.granted_users, new_grant],
        )
        self._rows[key] = updated
        return new_grant

    async def revoke_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
    ) -> bool:
        key = (resource_type, resource_id)
        existing = self._rows.get(key)
        if existing is None:
            return False
        remaining = [g for g in existing.granted_users if g.user_id != user_id]
        if len(remaining) == len(existing.granted_users):
            return False
        self._rows[key] = replace(existing, granted_users=remaining)
        return True

    # ----- Migration helpers -----

    async def list_missing_server_ids(self) -> List[int]:
        present = {rid for (rt, rid) in self._rows.keys() if rt == ResourceType.SERVER}
        return [rid for rid in self.server_ids if rid not in present]

    async def list_missing_group_ids(self) -> List[int]:
        present = {rid for (rt, rid) in self._rows.keys() if rt == ResourceType.GROUP}
        return [rid for rid in self.group_ids if rid not in present]

    async def add_many_public(
        self,
        resource_type: ResourceType,
        resource_ids: List[int],
    ) -> int:
        for rid in resource_ids:
            await self.set(
                SetVisibilityCommand(
                    resource_type=resource_type,
                    resource_id=rid,
                    visibility_type=VisibilityType.PUBLIC,
                    role_restriction=None,
                )
            )
        return len(resource_ids)

    # ----- Counts -----

    async def count_resources(self, resource_type: ResourceType) -> int:
        if resource_type == ResourceType.SERVER:
            return len(self.server_ids)
        if resource_type == ResourceType.GROUP:
            return len(self.group_ids)
        return 0

    async def count_visibility(self, resource_type: ResourceType) -> int:
        return sum(1 for (rt, _) in self._rows.keys() if rt == resource_type)

    async def count_by_visibility_type(
        self,
    ) -> Dict[ResourceType, Dict[VisibilityType, int]]:
        out: Dict[ResourceType, Dict[VisibilityType, int]] = {}
        for row in self._rows.values():
            inner = out.setdefault(row.resource_type, {})
            inner[row.visibility_type] = inner.get(row.visibility_type, 0) + 1
        return out


class FakeVisibilityUnitOfWork:
    """Minimal in-memory `VisibilityUnitOfWork`.

    Holds a single `FakeVisibilityRepository` (shared across `async
    with` enters) and tracks `commit_count` / `rollback_count` so tests
    can assert on transactional intent.
    """

    def __init__(self, repository: Optional[FakeVisibilityRepository] = None):
        self.visibility = repository or FakeVisibilityRepository()
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self) -> "FakeVisibilityUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1
