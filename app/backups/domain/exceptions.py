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
"""


class BackupError(Exception):
    """Base exception for backup-domain operations."""


class BackupScheduleNotFoundError(BackupError):
    """Raised when a requested schedule does not exist."""


class BackupScheduleAlreadyExistsError(BackupError):
    """Raised when a schedule for the given server already exists."""
