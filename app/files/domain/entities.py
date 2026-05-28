"""Pure domain entities for the file-history module.

These dataclasses are the language the application layer speaks. They have
no SQLAlchemy, Pydantic, FastAPI, or any framework dependency — only the
Python standard library.

The application service receives and returns these types. Adapters convert
to/from ORM rows; the api layer converts to/from Pydantic DTOs. This
isolation is what gives `domain/` swappability per `docs/app/ARCHITECTURE.md`
Section 4.1.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FileHistoryEntity:
    """A single recorded version of an edited file, independent of how
    it is persisted.

    `editor_username` is eagerly resolved by the adapter (via
    `joinedload`) so the application layer never has to touch ORM lazy
    relationships.
    """

    server_id: int
    file_path: str
    version_number: int
    backup_file_path: str
    file_size: int
    content_hash: Optional[str]
    editor_user_id: Optional[int]
    editor_username: Optional[str]
    created_at: datetime
    description: Optional[str]
    id: Optional[int] = None


@dataclass(frozen=True)
class CreateHistoryCommand:
    """Inputs to persist a new file-history record.

    Pure domain DTO, not Pydantic. The adapter sets `id` and `created_at`
    when it materialises the row.
    """

    server_id: int
    file_path: str
    version_number: int
    backup_file_path: str
    file_size: int
    content_hash: Optional[str]
    editor_user_id: Optional[int]
    description: Optional[str]


@dataclass(frozen=True)
class FileHistoryStatsEntity:
    """Aggregate statistics for a single server's edit history."""

    server_id: int
    total_files_with_history: int
    total_versions: int
    total_storage_used: int
    oldest_version_date: Optional[datetime]
    most_edited_file: Optional[str]
    most_edited_file_versions: Optional[int]


@dataclass(frozen=True)
class CleanupResultEntity:
    """Result of a bulk cleanup operation."""

    deleted_versions: int
    freed_storage: int
    cleanup_type: str
