"""Pure domain entities for the visibility module.

These dataclasses are the language the application layer speaks. They
have no SQLAlchemy, Pydantic, FastAPI, or any framework dependency
beyond the Python standard library (plus `VisibilityType` /
`ResourceType` / `Role` which are plain `enum.Enum`).

Adapters convert to/from ORM rows; the api layer converts to/from
Pydantic DTOs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from app.core.visibility.models import (  # known deviation, see __init__.py
    ResourceType,
    VisibilityType,
)
from app.users.domain.value_objects import Role

# ---------------------------------------------------------------------------
# Aggregate entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceUserAccessEntity:
    """A persisted per-user access grant for `SPECIFIC_USERS` visibility.

    `granted_by_user_id` may be `None` when the granter was later
    deleted (ON DELETE SET NULL on the FK column).
    """

    id: int
    resource_visibility_id: int
    user_id: int
    granted_by_user_id: Optional[int]
    created_at: datetime


@dataclass(frozen=True)
class ResourceVisibilityEntity:
    """A persisted visibility configuration for one resource.

    `granted_users` is denormalised onto the entity so the application
    service does not need to issue a separate query per resource — the
    adapter eager-loads the `user_access_grants` relationship.
    """

    id: int
    resource_type: ResourceType
    resource_id: int
    visibility_type: VisibilityType
    role_restriction: Optional[Role]
    created_at: datetime
    updated_at: datetime
    granted_users: List[ResourceUserAccessEntity] = field(default_factory=list)

    def has_user_access(self, user_id: int) -> bool:
        """Check whether a specific user has been granted access.

        Only meaningful for `VisibilityType.SPECIFIC_USERS`; returns
        `False` for every other visibility type, matching the legacy
        `ResourceVisibility.has_user_access` ORM helper.
        """
        if self.visibility_type != VisibilityType.SPECIFIC_USERS:
            return False
        return any(grant.user_id == user_id for grant in self.granted_users)


# ---------------------------------------------------------------------------
# Command DTOs (inputs to repository writes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetVisibilityCommand:
    """Inputs to upsert a `ResourceVisibility` row.

    The adapter upserts on `(resource_type, resource_id)`: existing rows
    are updated in place. When the new `visibility_type` is anything
    other than `SPECIFIC_USERS`, any pre-existing `ResourceUserAccess`
    grants for the row are cleared to keep the data consistent with the
    legacy `set_resource_visibility` behaviour.
    """

    resource_type: ResourceType
    resource_id: int
    visibility_type: VisibilityType
    role_restriction: Optional[Role] = None


@dataclass(frozen=True)
class GrantAccessCommand:
    """Inputs to grant a specific user access to a resource."""

    resource_type: ResourceType
    resource_id: int
    user_id: int
    granted_by_user_id: int


__all__ = [
    "GrantAccessCommand",
    "ResourceUserAccessEntity",
    "ResourceVisibilityEntity",
    "SetVisibilityCommand",
]
