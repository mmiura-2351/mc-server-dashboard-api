"""Pure domain entities for the templates module.

These dataclasses are the language the application layer speaks. They have
no SQLAlchemy, Pydantic, FastAPI, or any framework dependency — only the
Python standard library (plus `ServerType`, an `enum.Enum`; see the
deviation note in `app.templates.domain.__init__`).

The application service receives and returns these types. Adapters convert
to/from ORM rows; the api layer converts to/from Pydantic DTOs.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.servers.models import ServerType  # known deviation: see __init__.py


@dataclass(frozen=True)
class TemplateEntity:
    """A persisted template definition.

    `creator_name` is eagerly resolved by the adapter (via
    `joinedload(Template.creator)`) so the application layer never has
    to touch ORM lazy relationships. The field name matches the wire
    format (`TemplateResponse.creator_name`).
    """

    id: Optional[int]
    name: str
    description: Optional[str]
    minecraft_version: str
    server_type: ServerType
    configuration: Dict[str, Any]
    default_groups: Dict[str, List[int]]
    is_public: bool
    created_by: int
    creator_name: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class CreateTemplateCommand:
    """Inputs to persist a new template row.

    Pure domain DTO, not Pydantic. The adapter sets `id`, `created_at`,
    and `updated_at` when it materialises the row.
    """

    name: str
    minecraft_version: str
    server_type: ServerType
    configuration: Dict[str, Any]
    default_groups: Dict[str, List[int]]
    is_public: bool
    created_by: int
    description: Optional[str] = None


@dataclass(frozen=True)
class UpdateTemplateCommand:
    """Sparse update for an existing template.

    A field set to `None` is treated as "leave column untouched". This
    matches the legacy `TemplateService.update_template` contract.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    configuration: Optional[Dict[str, Any]] = None
    default_groups: Optional[Dict[str, List[int]]] = None
    is_public: Optional[bool] = None

    def applied_fields(self) -> Dict[str, Any]:
        """Return only the fields the caller actually set (non-None)."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class TemplateListSpec:
    """Inputs for `TemplateRepository.list_paged`.

    The viewer pair (`viewer_id`, `viewer_is_admin`) is required so the
    adapter can apply the visibility predicate at the SQL level rather
    than after materialising rows.
    """

    viewer_id: int
    viewer_is_admin: bool
    minecraft_version: Optional[str] = None
    server_type: Optional[ServerType] = None
    is_public: Optional[bool] = None
    page: int = 1
    size: int = 50


@dataclass(frozen=True)
class TemplateListPage:
    """One page of a `list_paged` result with the unsliced total."""

    entities: List[TemplateEntity]
    total: int
    page: int
    size: int
