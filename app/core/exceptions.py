import errno
import logging
from typing import Any, ClassVar, Dict, List, NoReturn, Optional

from fastapi import HTTPException, status

from app.core.error_schemas import ErrorDetail

logger = logging.getLogger(__name__)


class APIException(HTTPException):
    """Base exception class for API errors with consistent error handling.

    Subclasses set ``error_code`` (a ``ClassVar[str]``) to the canonical
    machine-readable identifier surfaced by the global exception handler
    (see :mod:`app.core.error_handlers` and :class:`app.core.error_schemas.ErrorResponse`).
    Issue #76 introduced this taxonomy; codes follow ``<DOMAIN>_<KIND>``
    in SCREAMING_SNAKE_CASE.
    """

    error_code: ClassVar[str] = "API_ERROR"

    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: Optional[Dict[str, Any]] = None,
        log_level: str = "warning",
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self._log_error(detail, log_level)

    def _log_error(self, detail: str, log_level: str):
        """Log the error with appropriate level."""
        log_func = getattr(logger, log_level, logger.warning)
        log_func(f"{self.__class__.__name__}: {detail}")


class ResourceNotFoundException(APIException):
    """Exception for when a requested resource is not found."""

    error_code: ClassVar[str] = "RESOURCE_NOT_FOUND"

    def __init__(self, resource_type: str, resource_id: str):
        detail = f"{resource_type} with ID {resource_id} not found"
        super().__init__(status.HTTP_404_NOT_FOUND, detail)


class ServerNotFoundException(ResourceNotFoundException):
    """Exception for when a server is not found."""

    error_code: ClassVar[str] = "SERVER_NOT_FOUND"

    def __init__(self, server_id: str):
        super().__init__("Server", server_id)


class UserNotFoundException(ResourceNotFoundException):
    """Exception for when a user is not found."""

    error_code: ClassVar[str] = "USER_NOT_FOUND"

    def __init__(self, user_id: str):
        super().__init__("User", user_id)


class GroupNotFoundException(ResourceNotFoundException):
    """Exception for when a group is not found."""

    error_code: ClassVar[str] = "GROUP_NOT_FOUND"

    def __init__(self, group_id: str):
        super().__init__("Group", group_id)


class BackupNotFoundException(ResourceNotFoundException):
    """Exception for when a backup is not found."""

    error_code: ClassVar[str] = "BACKUP_NOT_FOUND"

    def __init__(self, backup_id: str):
        super().__init__("Backup", backup_id)


class AccessDeniedException(APIException):
    """Exception for access denied scenarios."""

    error_code: ClassVar[str] = "ACCESS_DENIED"

    def __init__(self, resource_type: str = "resource", action: str = "access"):
        detail = f"Access denied: insufficient permissions to {action} {resource_type}"
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class ServerAccessDeniedException(AccessDeniedException):
    """Exception for server access denied."""

    error_code: ClassVar[str] = "SERVER_ACCESS_DENIED"

    def __init__(self, server_id: str):
        detail = f"Access denied: insufficient permissions to access server {server_id}"
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class InvalidRequestException(APIException):
    """Exception for invalid request data."""

    error_code: ClassVar[str] = "INVALID_REQUEST"

    def __init__(self, detail: str):
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class ConflictException(APIException):
    """Exception for resource conflicts."""

    error_code: ClassVar[str] = "RESOURCE_CONFLICT"

    def __init__(self, detail: str):
        super().__init__(status.HTTP_409_CONFLICT, detail)


class ServerStateException(APIException):
    """Exception for invalid server state operations."""

    error_code: ClassVar[str] = "SERVER_INVALID_STATE"

    def __init__(self, server_id: str, current_state: str, required_state: str):
        detail = f"Server {server_id} is {current_state}, but {required_state} is required for this operation"
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class FileOperationException(APIException):
    """Exception for file operation errors (generic 500 fallback).

    Issue #35 split out targeted subclasses (:class:`FileMissingError`,
    :class:`FileAccessDeniedError`, :class:`FileTooLargeError`,
    :class:`InvalidFileTypeError`, :class:`DiskSpaceError`) that map to
    more accurate HTTP statuses and carry actionable
    ``suggested_actions`` via :meth:`extra_details`. ``FileOperationException``
    is retained as the catch-all for unexpected I/O failures that don't
    fit those categories — mapped to HTTP 500.
    """

    error_code: ClassVar[str] = "FILE_OPERATION_FAILED"
    _http_status: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR
    _log_level: ClassVar[str] = "error"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "",
        *,
        technical_details: Optional[str] = None,
    ):
        self.operation = operation
        self.file_path = file_path
        self.reason = reason
        self.technical_details = technical_details or reason
        detail = self._build_detail(operation, file_path, reason)
        super().__init__(self._http_status, detail, log_level=self._log_level)

    @staticmethod
    def _build_detail(operation: str, file_path: str, reason: str) -> str:
        detail = f"Failed to {operation} file {file_path}"
        if reason:
            detail += f": {reason}"
        return detail

    def _suggested_actions(self) -> List[str]:
        return []

    def extra_details(self) -> List[ErrorDetail]:
        """Surface structured context through the standard error envelope.

        Adds the operation target, machine-readable technical details,
        and a small list of suggested next steps that the frontend can
        render inline. Mirrors the pattern established by the Issue #33
        server-creation exceptions.
        """
        details: List[ErrorDetail] = [
            ErrorDetail(
                field="file_path",
                message=self.file_path,
                code="FILE_PATH",
            )
        ]
        if self.technical_details:
            details.append(
                ErrorDetail(
                    field=None,
                    message=self.technical_details,
                    code="TECHNICAL_DETAILS",
                )
            )
        for action in self._suggested_actions():
            details.append(
                ErrorDetail(
                    field=None,
                    message=action,
                    code="SUGGESTED_ACTION",
                )
            )
        return details


class FileMissingError(FileOperationException):
    """Raised when an expected file or directory does not exist.

    Mapped to HTTP 404. Distinct from Python's builtin
    :class:`FileNotFoundError` so callers can ``except`` either kind
    explicitly. Carries the missing path via :attr:`file_path`.
    """

    error_code: ClassVar[str] = "FILE_NOT_FOUND"
    _http_status: ClassVar[int] = status.HTTP_404_NOT_FOUND
    _log_level: ClassVar[str] = "warning"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "Path not found",
        *,
        technical_details: Optional[str] = None,
    ):
        super().__init__(
            operation, file_path, reason, technical_details=technical_details
        )

    def _suggested_actions(self) -> List[str]:
        return [
            "Verify the file path is correct and exists on the server",
            "Refresh the file listing to see the current directory contents",
        ]


class FileAccessDeniedError(FileOperationException):
    """Raised when the filesystem or policy denies access to a file.

    Mapped to HTTP 403. Use this for OS-level ``PermissionError`` /
    ``EACCES`` as well as policy denials (e.g. attempting to modify a
    restricted file without the admin role).
    """

    error_code: ClassVar[str] = "FILE_ACCESS_DENIED"
    _http_status: ClassVar[int] = status.HTTP_403_FORBIDDEN
    _log_level: ClassVar[str] = "warning"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "Permission denied",
        *,
        technical_details: Optional[str] = None,
    ):
        super().__init__(
            operation, file_path, reason, technical_details=technical_details
        )

    def _suggested_actions(self) -> List[str]:
        return [
            "Confirm you have permission to modify this file",
            "Contact an administrator if the file is restricted",
        ]


class FileTooLargeError(FileOperationException):
    """Raised when a file exceeds the operation's size limit.

    Mapped to HTTP 413 (Payload Too Large). Carries the offending size
    and (optionally) the configured limit so the client can render an
    actionable message.
    """

    error_code: ClassVar[str] = "FILE_TOO_LARGE"
    _http_status: ClassVar[int] = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    _log_level: ClassVar[str] = "warning"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "File exceeds maximum allowed size",
        *,
        size_bytes: Optional[int] = None,
        max_bytes: Optional[int] = None,
        technical_details: Optional[str] = None,
    ):
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        super().__init__(
            operation, file_path, reason, technical_details=technical_details
        )

    def _suggested_actions(self) -> List[str]:
        actions = ["Compress or split the file before retrying"]
        if self.max_bytes is not None:
            actions.append(f"Keep file size at or below {self.max_bytes} bytes")
        return actions

    def extra_details(self) -> List[ErrorDetail]:
        details = super().extra_details()
        if self.size_bytes is not None:
            details.append(
                ErrorDetail(
                    field="size_bytes",
                    message=str(self.size_bytes),
                    code="FILE_SIZE_BYTES",
                )
            )
        if self.max_bytes is not None:
            details.append(
                ErrorDetail(
                    field="max_bytes",
                    message=str(self.max_bytes),
                    code="FILE_MAX_BYTES",
                )
            )
        return details


class InvalidFileTypeError(FileOperationException):
    """Raised when an operation is attempted on an unsupported file type.

    Mapped to HTTP 400. Examples: reading a directory as text, uploading
    an archive with an unrecognised extension, treating a binary file as
    an image.
    """

    error_code: ClassVar[str] = "INVALID_FILE_TYPE"
    _http_status: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    _log_level: ClassVar[str] = "warning"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "Invalid or unsupported file type",
        *,
        detected_type: Optional[str] = None,
        expected_types: Optional[List[str]] = None,
        technical_details: Optional[str] = None,
    ):
        self.detected_type = detected_type
        self.expected_types = list(expected_types or [])
        super().__init__(
            operation, file_path, reason, technical_details=technical_details
        )

    def _suggested_actions(self) -> List[str]:
        actions = ["Choose a file of a supported type and try again"]
        if self.expected_types:
            actions.append("Supported types: " + ", ".join(self.expected_types))
        return actions

    def extra_details(self) -> List[ErrorDetail]:
        details = super().extra_details()
        if self.detected_type:
            details.append(
                ErrorDetail(
                    field="detected_type",
                    message=self.detected_type,
                    code="DETECTED_FILE_TYPE",
                )
            )
        for expected in self.expected_types:
            details.append(
                ErrorDetail(
                    field="expected_types",
                    message=expected,
                    code="EXPECTED_FILE_TYPE",
                )
            )
        return details


class FileAlreadyExistsError(FileOperationException):
    """Raised when an operation targets a path that is already occupied.

    Mapped to HTTP 409 (Conflict). Use for rename/move/upload destinations
    that would clobber an existing file or directory. Carries the
    conflicting path via :attr:`existing_path` so the frontend can offer
    an inline resolution (rename, overwrite, delete-then-retry).
    """

    error_code: ClassVar[str] = "FILE_ALREADY_EXISTS"
    _http_status: ClassVar[int] = status.HTTP_409_CONFLICT
    _log_level: ClassVar[str] = "warning"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "Destination already exists",
        *,
        existing_path: Optional[str] = None,
        technical_details: Optional[str] = None,
    ):
        self.existing_path = existing_path or file_path
        super().__init__(
            operation, file_path, reason, technical_details=technical_details
        )

    def _suggested_actions(self) -> List[str]:
        return [
            "Use a different destination name or path",
            "Delete the existing file or directory first, then retry",
        ]

    def extra_details(self) -> List[ErrorDetail]:
        details = super().extra_details()
        if self.existing_path:
            details.append(
                ErrorDetail(
                    field="existing_path",
                    message=self.existing_path,
                    code="EXISTING_PATH",
                )
            )
        return details


class DiskSpaceError(FileOperationException):
    """Raised when a write fails because the device is out of space.

    Mapped to HTTP 507 (Insufficient Storage). Triggered by
    :data:`errno.ENOSPC` from the OS layer.
    """

    error_code: ClassVar[str] = "DISK_SPACE_INSUFFICIENT"
    _http_status: ClassVar[int] = status.HTTP_507_INSUFFICIENT_STORAGE
    _log_level: ClassVar[str] = "error"

    def __init__(
        self,
        operation: str,
        file_path: str,
        reason: str = "Insufficient disk space",
        *,
        technical_details: Optional[str] = None,
    ):
        super().__init__(
            operation, file_path, reason, technical_details=technical_details
        )

    def _suggested_actions(self) -> List[str]:
        return [
            "Free up space on the server's storage volume",
            "Delete unused backups or old log files",
            "Contact an administrator to provision additional storage",
        ]


class DatabaseOperationException(APIException):
    """Exception for database operation errors."""

    error_code: ClassVar[str] = "DATABASE_OPERATION_FAILED"

    def __init__(self, operation: str, table: str, reason: str = ""):
        detail = f"Database {operation} failed for {table}"
        if reason:
            detail += f": {reason}"
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, log_level="error")


class AuthenticationException(APIException):
    """Exception for authentication failures."""

    error_code: ClassVar[str] = "AUTHENTICATION_FAILED"

    def __init__(self, detail: str = "Invalid authentication credentials"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail)


class UserNotApprovedException(APIException):
    """Exception for unapproved user access attempts."""

    error_code: ClassVar[str] = "USER_NOT_APPROVED"

    def __init__(self):
        detail = "User account is not approved yet"
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class MinecraftServerException(APIException):
    """Exception for Minecraft server operation errors."""

    error_code: ClassVar[str] = "MINECRAFT_SERVER_ERROR"

    def __init__(self, server_id: str, operation: str, reason: str = ""):
        detail = f"Failed to {operation} Minecraft server {server_id}"
        if reason:
            detail += f": {reason}"
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, log_level="error")


def handle_database_error(operation: str, table: str, error: Exception) -> NoReturn:
    """Utility function to handle and raise database errors consistently."""
    logger.error(f"Database {operation} failed for {table}: {str(error)}")
    raise DatabaseOperationException(operation, table, str(error))


def handle_file_error(operation: str, file_path: str, error: Exception) -> NoReturn:
    """Utility function to map OS / library errors to the right exception.

    Issue #35 introduced :class:`FileMissingError`,
    :class:`FileAccessDeniedError`, :class:`FileTooLargeError`,
    :class:`InvalidFileTypeError`, :class:`DiskSpaceError`, and (under
    #341) :class:`FileAlreadyExistsError` so the standard error response
    carries the correct HTTP status and actionable ``suggested_actions``. This helper dispatches on
    ``errno`` and built-in exception type before falling back to the
    generic 500 :class:`FileOperationException`.

    If ``error`` is already one of the new ``FileOperationException``
    subclasses (or the base class itself) it is re-raised unchanged —
    callers can safely raise a specific subclass and route it through
    this helper without losing context.
    """
    logger.error(f"File {operation} failed for {file_path}: {str(error)}")

    # Pass-through: a more specific subclass already carries the right
    # status/code/details — preserve it instead of demoting to generic.
    if isinstance(error, FileOperationException):
        raise error

    reason = str(error)
    err_no = getattr(error, "errno", None)

    if err_no == errno.ENOSPC:
        raise DiskSpaceError(operation, file_path, technical_details=reason)
    if isinstance(error, PermissionError) or err_no == errno.EACCES:
        raise FileAccessDeniedError(operation, file_path, technical_details=reason)
    if isinstance(error, FileNotFoundError) or err_no == errno.ENOENT:
        raise FileMissingError(operation, file_path, technical_details=reason)
    if isinstance(error, IsADirectoryError) or err_no == errno.EISDIR:
        raise InvalidFileTypeError(
            operation,
            file_path,
            "Path is a directory, not a file",
            detected_type="directory",
            technical_details=reason,
        )

    raise FileOperationException(operation, file_path, reason)


def validate_server_access(server, user_id: str) -> None:
    """Validate if user has access to the server."""
    if server.owner_id != user_id:
        raise ServerAccessDeniedException(str(server.id))


def validate_user_approved(user) -> None:
    """Validate if user is approved."""
    if not user.is_approved:
        raise UserNotApprovedException()
