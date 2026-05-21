"""Pure domain entities for the servers domain.

This module is the language the application layer speaks. The dataclasses
have no SQLAlchemy, Pydantic, FastAPI, or any framework dependency — only
the Python standard library (plus `ServerType` / `ServerStatus`, both
`enum.Enum`, see deviation notes in `app.servers.domain.__init__`).

The application service receives and returns these types. Adapters convert
to/from ORM rows; the api layer converts to/from Pydantic DTOs.

TBD(#154-8): expanded under #228 (PR 1/3). The original 9-field
read-only seed introduced for #224 / #225 / #226 is preserved as a
prefix of the new shape; the additional columns (`status`,
`created_at`, `updated_at`, `description`, `template_id`,
`is_deleted`, `owner_username`) are added with defaults so the
existing cross-domain construction sites (e.g.
`app.servers.adapters.read_port.SqlAlchemyServerReadPort`, the
groups / templates / files unit-test fakes) keep compiling without
edits. The full required-vs-default distinction will be tightened
once PR #2 rewires the runtime to construct `ServerEntity` through
the new `ServerRepository`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.servers.models import ServerStatus, ServerType  # known deviation, #235/#228


def _epoch_utc() -> datetime:
    """Stable placeholder timestamp for entities constructed without one.

    Used as a `field(default_factory=...)` for `created_at` / `updated_at`
    so the existing 9-field `ServerEntity(...)` call sites (the legacy
    `ServerReadPort` adapter and the cross-domain test fakes) continue
    to compile during PR #1. Adapters built under #228 always populate
    these from the ORM row, so this placeholder is unreachable from
    production paths.
    """
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Server aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServerEntity:
    """A persisted Server row.

    `owner_username` is denormalised onto the entity because several
    wire responses surface it and the SQLAlchemy adapter eager-loads
    `Server.owner` via `joinedload` to avoid a per-row N+1. Adapters
    that do not eager-load the owner (or that intentionally skip the
    JOIN) leave the field as `None`.

    Frozen + dataclass-based: callers mutate by copying via
    `dataclasses.replace(...)`.
    """

    # ----- Identity / config (required from inception, #224-#226) -----
    id: int
    name: str
    directory_path: str
    minecraft_version: str
    server_type: ServerType
    port: int
    max_memory: int
    max_players: int
    owner_id: int

    # ----- Lifecycle columns (#228, see module docstring on defaults) -----
    status: ServerStatus = ServerStatus.stopped
    created_at: datetime = field(default_factory=_epoch_utc)
    updated_at: datetime = field(default_factory=_epoch_utc)

    # ----- Optional columns -----
    description: Optional[str] = None
    template_id: Optional[int] = None
    is_deleted: bool = False
    owner_username: Optional[str] = None


@dataclass(frozen=True)
class CreateServerCommand:
    """Inputs to persist a new server row.

    The adapter relies on the database to populate `id`, `status`
    (defaulted to `stopped` server-side), `created_at`, and
    `updated_at`.
    """

    name: str
    directory_path: str
    minecraft_version: str
    server_type: ServerType
    port: int
    max_memory: int
    max_players: int
    owner_id: int
    description: Optional[str] = None
    template_id: Optional[int] = None


@dataclass(frozen=True)
class UpdateServerCommand:
    """Sparse update for an existing server row.

    `None` always means "leave column untouched". There is no way to
    clear (set to NULL) a column via this command; future commands may
    add sentinel-based clearing semantics if needed.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    minecraft_version: Optional[str] = None
    port: Optional[int] = None
    max_memory: Optional[int] = None
    max_players: Optional[int] = None
    template_id: Optional[int] = None

    def applied_fields(self) -> Dict[str, Any]:
        """Return only the fields the caller actually set (non-None)."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class ServerListSpec:
    """Inputs for `ServerRepository.list_paged`."""

    owner_id: Optional[int] = None
    status: Optional[ServerStatus] = None
    server_type: Optional[ServerType] = None
    include_deleted: bool = False
    page: int = 1
    size: int = 50


@dataclass(frozen=True)
class ServerListPage:
    """Read result for `ServerRepository.list_paged`."""

    entities: List[ServerEntity]
    total: int
    page: int
    size: int
