"""Domain exceptions raised by the backups application service.

The router catches these and maps them to HTTPException; the legacy
shim re-exports them so callers can `except BackupError` regardless of
import path.

Most backup operations bubble up the legacy
`app.core.exceptions` types (`BackupNotFoundException`,
`ServerNotFoundException`, `FileOperationException`, ...) verbatim —
those already carry HTTP status codes and the router relies on them.
The exceptions defined here are reserved for the few cases that the
legacy module did not name explicitly (e.g. schedule duplicates).

``error_code`` (``ClassVar[str]``) feeds the global exception handler
(`app.core.error_handlers`) so :class:`app.core.error_schemas.ErrorResponse`
carries a stable machine identifier (Issue #76).
"""

from typing import ClassVar


class BackupError(Exception):
    """Base exception for backup-domain operations."""

    error_code: ClassVar[str] = "BACKUP_ERROR"


class BackupScheduleNotFoundError(BackupError):
    """Raised when a requested schedule does not exist."""

    error_code: ClassVar[str] = "BACKUP_SCHEDULE_NOT_FOUND"


class BackupScheduleAlreadyExistsError(BackupError):
    """Raised when a schedule for the given server already exists."""

    error_code: ClassVar[str] = "BACKUP_SCHEDULE_ALREADY_EXISTS"


# Aliases for the framework-agnostic authorization-service raise sites
# introduced in #273. ``BackupDomainError`` is the umbrella base used by
# the global exception handlers; the two concrete subclasses pair with
# the legacy HTTP-404 raises that previously lived inside
# ``AuthorizationService.check_backup_access``.
class BackupDomainError(BackupError):
    """Base for domain errors surfaced by the backups application layer."""

    error_code: ClassVar[str] = "BACKUP_DOMAIN_ERROR"


class BackupNotFoundError(BackupDomainError):
    """Raised when a requested backup does not exist (HTTP 404)."""

    error_code: ClassVar[str] = "BACKUP_NOT_FOUND"


class BackupParentServerMissingError(BackupDomainError):
    """Raised when a backup's parent server cannot be resolved (HTTP 404)."""

    error_code: ClassVar[str] = "BACKUP_PARENT_SERVER_MISSING"
