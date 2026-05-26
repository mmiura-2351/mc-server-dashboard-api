"""SQLAlchemy implementation of `VisibilityRepository`.

The adapter is the only layer that knows about the SQLAlchemy ORM and
the `ResourceVisibility` / `ResourceUserAccess` columns; it converts
ORM rows to/from domain entities so the application layer never sees
ORM types.

Per the UnitOfWork pattern, repository methods **do not commit**. They
stage changes on the session and rely on the surrounding
`SqlAlchemyVisibilityUnitOfWork` (or the caller) to commit.

Cross-domain reads against `Server` and `Group` (the
`list_missing_*_ids` migration helpers) live here intentionally: a
single anti-join is markedly cheaper than two list-and-diff passes
through dedicated Read Ports, and the alternative would force the
application layer to know the legacy column names. See
`docs/ARCHITECTURE.md` §4.3.
"""

from typing import Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

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
from app.core.visibility.models import (
    ResourceType,
    ResourceUserAccess,
    ResourceVisibility,
    VisibilityType,
)
from app.groups.models import Group
from app.servers.models import Server


def _access_to_entity(row: ResourceUserAccess) -> ResourceUserAccessEntity:
    return ResourceUserAccessEntity(
        id=row.id,
        resource_visibility_id=row.resource_visibility_id,
        user_id=row.user_id,
        granted_by_user_id=row.granted_by_user_id,
        created_at=row.created_at,
    )


def _visibility_to_entity(row: ResourceVisibility) -> ResourceVisibilityEntity:
    """Convert an ORM row to a `ResourceVisibilityEntity`.

    `row.user_access_grants` is declared `lazy="dynamic"` on the ORM
    model, so iterating it issues a SELECT. The cost mirrors the legacy
    behaviour exactly; only callers that read `granted_users` pay it.
    """
    grants = [_access_to_entity(g) for g in row.user_access_grants]
    return ResourceVisibilityEntity(
        id=row.id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        visibility_type=row.visibility_type,
        role_restriction=row.role_restriction,
        created_at=row.created_at,
        updated_at=row.updated_at,
        granted_users=grants,
    )


class SqlAlchemyVisibilityRepository:
    """`VisibilityRepository` backed by SQLAlchemy."""

    def __init__(self, db: Session):
        self._db = db

    # ----- Reads -----

    async def get(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[ResourceVisibilityEntity]:
        row = self._get_row(resource_type, resource_id)
        if row is None:
            return None
        return _visibility_to_entity(row)

    async def get_user_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
    ) -> Optional[ResourceUserAccessEntity]:
        row = self._get_row(resource_type, resource_id)
        if row is None:
            return None
        grant = (
            self._db.query(ResourceUserAccess)
            .filter(
                ResourceUserAccess.resource_visibility_id == row.id,
                ResourceUserAccess.user_id == user_id,
            )
            .one_or_none()
        )
        if grant is None:
            return None
        return _access_to_entity(grant)

    # ----- Writes -----

    async def set(self, command: SetVisibilityCommand) -> ResourceVisibilityEntity:
        row = self._get_row(command.resource_type, command.resource_id)
        if row is None:
            row = ResourceVisibility(
                resource_type=command.resource_type,
                resource_id=command.resource_id,
                visibility_type=command.visibility_type,
                role_restriction=command.role_restriction,
            )
            self._db.add(row)
        else:
            row.visibility_type = command.visibility_type
            row.role_restriction = command.role_restriction
            # Clear SPECIFIC_USERS grants when switching to any other type,
            # matching the legacy `set_resource_visibility` invariant.
            if command.visibility_type != VisibilityType.SPECIFIC_USERS:
                for grant in list(row.user_access_grants):
                    self._db.delete(grant)
        # `flush` populates `id` and the server-default timestamps so the
        # entity we hand back is fully materialised before commit.
        self._db.flush()
        return _visibility_to_entity(row)

    async def grant_access(self, command: GrantAccessCommand) -> ResourceUserAccessEntity:
        row = self._get_row(command.resource_type, command.resource_id)
        if row is None:
            raise VisibilityNotFoundError("Resource visibility configuration not found")
        if row.visibility_type != VisibilityType.SPECIFIC_USERS:
            raise InvalidVisibilityTypeError(
                "Resource must have SPECIFIC_USERS visibility type"
            )
        existing = (
            self._db.query(ResourceUserAccess)
            .filter(
                ResourceUserAccess.resource_visibility_id == row.id,
                ResourceUserAccess.user_id == command.user_id,
            )
            .one_or_none()
        )
        if existing is not None:
            raise DuplicateGrantError("User already has access to this resource")
        grant = ResourceUserAccess(
            resource_visibility_id=row.id,
            user_id=command.user_id,
            granted_by_user_id=command.granted_by_user_id,
        )
        self._db.add(grant)
        self._db.flush()
        return _access_to_entity(grant)

    async def revoke_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
    ) -> bool:
        row = self._get_row(resource_type, resource_id)
        if row is None:
            return False
        grant = (
            self._db.query(ResourceUserAccess)
            .filter(
                ResourceUserAccess.resource_visibility_id == row.id,
                ResourceUserAccess.user_id == user_id,
            )
            .one_or_none()
        )
        if grant is None:
            return False
        self._db.delete(grant)
        self._db.flush()
        return True

    # ----- Migration helpers (cross-domain reads kept in adapter) -----

    async def list_missing_server_ids(self) -> List[int]:
        rows = (
            self._db.query(Server.id)
            .outerjoin(
                ResourceVisibility,
                and_(
                    Server.id == ResourceVisibility.resource_id,
                    ResourceVisibility.resource_type == ResourceType.SERVER,
                ),
            )
            .filter(ResourceVisibility.id.is_(None))
            .all()
        )
        return [row.id for row in rows]

    async def list_missing_group_ids(self) -> List[int]:
        rows = (
            self._db.query(Group.id)
            .outerjoin(
                ResourceVisibility,
                and_(
                    Group.id == ResourceVisibility.resource_id,
                    ResourceVisibility.resource_type == ResourceType.GROUP,
                ),
            )
            .filter(ResourceVisibility.id.is_(None))
            .all()
        )
        return [row.id for row in rows]

    async def add_many_public(
        self,
        resource_type: ResourceType,
        resource_ids: List[int],
    ) -> int:
        if not resource_ids:
            return 0
        rows = [
            ResourceVisibility(
                resource_type=resource_type,
                resource_id=rid,
                visibility_type=VisibilityType.PUBLIC,
                role_restriction=None,
            )
            for rid in resource_ids
        ]
        self._db.add_all(rows)
        return len(rows)

    # ----- Counts (migration verification + status) -----

    async def count_resources(self, resource_type: ResourceType) -> int:
        if resource_type == ResourceType.SERVER:
            return int(self._db.query(func.count(Server.id)).scalar() or 0)
        if resource_type == ResourceType.GROUP:
            return int(self._db.query(func.count(Group.id)).scalar() or 0)
        return 0

    async def count_visibility(self, resource_type: ResourceType) -> int:
        return int(
            self._db.query(func.count(ResourceVisibility.id))
            .filter(ResourceVisibility.resource_type == resource_type)
            .scalar()
            or 0
        )

    async def count_by_visibility_type(
        self,
    ) -> Dict[ResourceType, Dict[VisibilityType, int]]:
        rows = (
            self._db.query(
                ResourceVisibility.resource_type,
                ResourceVisibility.visibility_type,
                func.count(ResourceVisibility.id),
            )
            .group_by(
                ResourceVisibility.resource_type,
                ResourceVisibility.visibility_type,
            )
            .all()
        )
        out: Dict[ResourceType, Dict[VisibilityType, int]] = {}
        for resource_type, visibility_type, count in rows:
            if count <= 0:
                continue
            out.setdefault(resource_type, {})[visibility_type] = int(count)
        return out

    # ----- Internal helpers -----

    def _get_row(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[ResourceVisibility]:
        return (
            self._db.query(ResourceVisibility)
            .filter(
                ResourceVisibility.resource_type == resource_type,
                ResourceVisibility.resource_id == resource_id,
            )
            .one_or_none()
        )


__all__ = ["SqlAlchemyVisibilityRepository"]
