import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class APIException(HTTPException):
    """Base exception class for API errors with consistent error handling."""

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

    def __init__(self, resource_type: str, resource_id: str):
        detail = f"{resource_type} with ID {resource_id} not found"
        super().__init__(status.HTTP_404_NOT_FOUND, detail)


class ServerNotFoundException(ResourceNotFoundException):
    """Exception for when a server is not found."""

    def __init__(self, server_id: str):
        super().__init__("Server", server_id)


class UserNotFoundException(ResourceNotFoundException):
    """Exception for when a user is not found."""

    def __init__(self, user_id: str):
        super().__init__("User", user_id)


class GroupNotFoundException(ResourceNotFoundException):
    """Exception for when a group is not found."""

    def __init__(self, group_id: str):
        super().__init__("Group", group_id)


class BackupNotFoundException(ResourceNotFoundException):
    """Exception for when a backup is not found."""

    def __init__(self, backup_id: str):
        super().__init__("Backup", backup_id)


class TemplateNotFoundException(ResourceNotFoundException):
    """Exception for when a template is not found."""

    def __init__(self, template_id: str):
        super().__init__("Template", template_id)


class AccessDeniedException(APIException):
    """Exception for access denied scenarios."""

    def __init__(self, resource_type: str = "resource", action: str = "access"):
        detail = f"Access denied: insufficient permissions to {action} {resource_type}"
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class ServerAccessDeniedException(AccessDeniedException):
    """Exception for server access denied."""

    def __init__(self, server_id: str):
        detail = f"Access denied: insufficient permissions to access server {server_id}"
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class InvalidRequestException(APIException):
    """Exception for invalid request data."""

    def __init__(self, detail: str):
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class ConflictException(APIException):
    """Exception for resource conflicts."""

    def __init__(self, detail: str):
        super().__init__(status.HTTP_409_CONFLICT, detail)


class ServerStateException(APIException):
    """Exception for invalid server state operations."""

    def __init__(self, server_id: str, current_state: str, required_state: str):
        detail = f"Server {server_id} is {current_state}, but {required_state} is required for this operation"
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class FileOperationException(APIException):
    """Exception for file operation errors."""

    def __init__(self, operation: str, file_path: str, reason: str = ""):
        detail = f"Failed to {operation} file {file_path}"
        if reason:
            detail += f": {reason}"
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, log_level="error")


class DatabaseOperationException(APIException):
    """Exception for database operation errors."""

    def __init__(self, operation: str, table: str, reason: str = ""):
        detail = f"Database {operation} failed for {table}"
        if reason:
            detail += f": {reason}"
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, log_level="error")


class AuthenticationException(APIException):
    """Exception for authentication failures."""

    def __init__(self, detail: str = "Invalid authentication credentials"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail)


class UserNotApprovedException(APIException):
    """Exception for unapproved user access attempts."""

    def __init__(self):
        detail = "User account is not approved yet"
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


class MinecraftServerException(APIException):
    """Exception for Minecraft server operation errors."""

    def __init__(self, server_id: str, operation: str, reason: str = ""):
        detail = f"Failed to {operation} Minecraft server {server_id}"
        if reason:
            detail += f": {reason}"
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, detail, log_level="error")


def handle_database_error(operation: str, table: str, error: Exception) -> None:
    """Utility function to handle and raise database errors consistently."""
    logger.error(f"Database {operation} failed for {table}: {str(error)}")
    raise DatabaseOperationException(operation, table, str(error))


def handle_file_error(operation: str, file_path: str, error: Exception) -> None:
    """Utility function to handle and raise file operation errors consistently."""
    logger.error(f"File {operation} failed for {file_path}: {str(error)}")
    raise FileOperationException(operation, file_path, str(error))


def validate_server_access(server, user_id: str) -> None:
    """Validate if user has access to the server."""
    if server.owner_id != user_id:
        raise ServerAccessDeniedException(str(server.id))


def validate_user_approved(user) -> None:
    """Validate if user is approved."""
    if not user.is_approved:
        raise UserNotApprovedException()
