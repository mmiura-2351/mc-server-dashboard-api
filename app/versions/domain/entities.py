"""Pure domain entities for the versions module.

These dataclasses are the language the application layer speaks. They have
no SQLAlchemy, Pydantic, FastAPI, or any framework dependency — only the
Python standard library and `app.servers.models.ServerType` (an enum, also
framework-free).

The application service receives and returns these types. Adapters convert
to/from ORM rows; the api layer converts to/from Pydantic DTOs. This
isolation is what gives `domain/` swappability per `docs/ARCHITECTURE.md`
§4.1.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.servers.models import ServerType


@dataclass(frozen=True)
class MinecraftVersionEntity:
    """A Minecraft server version, independent of how it is persisted."""

    server_type: ServerType
    version: str
    download_url: str
    is_stable: bool
    is_active: bool
    id: Optional[int] = None
    release_date: Optional[datetime] = None
    build_number: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class VersionUpdateLogEntity:
    """A single record describing one version-update operation."""

    update_type: str
    status: str
    id: Optional[int] = None
    server_type: Optional[str] = None
    versions_added: int = 0
    versions_updated: int = 0
    versions_removed: int = 0
    execution_time_ms: Optional[int] = None
    external_api_calls: int = 0
    error_message: Optional[str] = None
    executed_by_user_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass(frozen=True)
class CreateVersionCommand:
    """Inputs to create or upsert a version. Pure domain DTO, not Pydantic."""

    server_type: ServerType
    version: str
    download_url: str
    is_stable: bool = True
    release_date: Optional[datetime] = None
    build_number: Optional[int] = None


@dataclass(frozen=True)
class UpdateVersionCommand:
    """Sparse update fields.

    `None` means "leave the existing column untouched" — only non-`None`
    fields are applied by the adapter. There is currently no way to set
    a nullable column back to NULL through this command; if that case
    arises, introduce a `MISSING` sentinel and switch `applied_fields`
    to `value is not MISSING`. Tracked in PR #229 review item B as a
    pilot-scope known limitation.
    """

    download_url: Optional[str] = None
    release_date: Optional[datetime] = None
    is_stable: Optional[bool] = None
    build_number: Optional[int] = None
    is_active: Optional[bool] = None

    def applied_fields(self) -> dict:
        """Return only the fields the caller actually set (i.e. non-`None`).

        Note: a `None` argument is treated as "skip", not "set to NULL".
        See the class docstring for the rationale.
        """
        return {name: value for name, value in self.__dict__.items() if value is not None}


@dataclass(frozen=True)
class CreateUpdateLogCommand:
    """Inputs to open a new update log entry."""

    update_type: str
    status: str
    server_type: Optional[str] = None
    executed_by_user_id: Optional[int] = None


@dataclass(frozen=True)
class VersionStatsEntity:
    """Aggregate statistics over the version catalogue."""

    total_versions: int
    active_versions: int
    by_server_type: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DuplicateVersionEntity:
    """One row of the `find_duplicate_versions` report."""

    server_type: str
    version: str
    count: int
