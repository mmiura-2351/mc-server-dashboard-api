"""Pure domain entities for the groups module.

These dataclasses are the language the application layer speaks. They have
no SQLAlchemy, Pydantic, FastAPI, or any framework dependency — only the
Python standard library (plus `GroupType` and `ServerStatus`, both
`enum.Enum`; see the deviation notes in `app.groups.domain.__init__`).

The application service receives and returns these types. Adapters convert
to/from ORM rows; the api layer converts to/from Pydantic DTOs.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.groups.domain.value_objects import GroupType
from app.servers.domain.value_objects import ServerStatus


@dataclass(frozen=True)
class GroupEntity:
    """A persisted group definition (op or whitelist).

    `players` is the materialised list-of-dicts payload that the ORM
    stores as JSON. Adapters call `Group.get_players()` so the application
    layer never has to know about JSON-vs-list coercion.
    """

    id: Optional[int]
    name: str
    description: Optional[str]
    type: GroupType
    players: List[Dict[str, Any]]
    owner_id: int
    is_template: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class CreateGroupCommand:
    """Inputs to persist a new group row.

    Pure domain DTO, not Pydantic. The adapter sets `id`, `created_at`,
    `updated_at`, and initialises `players=[]` / `is_template=False`.
    """

    name: str
    type: GroupType
    owner_id: int
    description: Optional[str] = None


@dataclass(frozen=True)
class UpdateGroupCommand:
    """Sparse update for an existing group.

    A field set to `None` is treated as "leave column untouched". This
    matches the legacy `GroupService.update_group` contract.
    """

    name: Optional[str] = None
    description: Optional[str] = None

    def applied_fields(self) -> Dict[str, Any]:
        """Return only the fields the caller actually set (non-None)."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class GroupListSpec:
    """Inputs for `GroupRepository.list`.

    Phase 1 visibility is pass-through (all authenticated users can see
    all groups), so no `viewer_id` is required. When visibility hardens
    this dataclass gains those fields without churning the call sites.
    """

    type: Optional[GroupType] = None


@dataclass(frozen=True)
class ServerGroupEntity:
    """A server↔group attachment row."""

    id: Optional[int]
    server_id: int
    group_id: int
    priority: int
    attached_at: Optional[datetime]


@dataclass(frozen=True)
class AttachServerGroupCommand:
    """Inputs to persist a new `ServerGroup` row."""

    server_id: int
    group_id: int
    priority: int = 0


@dataclass(frozen=True)
class AttachedGroupView:
    """Read view returned by `list_attachments_for_server`.

    Field-name parity with `AttachedGroupResponse` in
    `app.groups.schemas`: the router builds the wire response by
    spreading this dataclass into the Pydantic model, so the field
    `id` matches `AttachedGroupResponse.id` (not `group_id`).
    """

    id: int
    name: str
    description: Optional[str]
    type: GroupType
    priority: int
    attached_at: datetime
    player_count: int


@dataclass(frozen=True)
class AttachedServerView:
    """Read view returned by `list_attachments_for_group`.

    `status` is the `ServerStatus` enum value, not a string. The
    application layer is responsible for converting to `status.value`
    before crossing the wire (matches the wire shape on
    `AttachedServerResponse.status: str`).
    """

    id: int
    name: str
    status: ServerStatus
    priority: int
    attached_at: datetime
