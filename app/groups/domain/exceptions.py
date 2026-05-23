"""Domain exceptions raised by the groups application service.

The router catches these and maps them to HTTPException; the legacy
shim re-exports them so callers can `except GroupError` regardless of
import path.

``error_code`` (``ClassVar[str]``) is consumed by the global
exception handler (`app.core.error_handlers`) to populate
:class:`app.core.error_schemas.ErrorResponse.error` (Issue #76).
"""

from typing import ClassVar


class GroupError(Exception):
    """Base exception for group operations."""

    error_code: ClassVar[str] = "GROUP_ERROR"


class GroupNotFoundError(GroupError):
    """Raised when a referenced group does not exist."""

    error_code: ClassVar[str] = "GROUP_NOT_FOUND"


class GroupAlreadyExistsError(GroupError):
    """Raised when a (owner, name) pair collides with an existing group."""

    error_code: ClassVar[str] = "GROUP_ALREADY_EXISTS"


class GroupAccessError(GroupError):
    """Raised when a viewer lacks permission to read or modify a group."""

    error_code: ClassVar[str] = "GROUP_ACCESS_DENIED"


class GroupHasAttachmentsError(GroupError):
    """Raised when attempting to delete a group still attached to servers."""

    error_code: ClassVar[str] = "GROUP_HAS_ATTACHMENTS"


class PlayerNotFoundInGroup(GroupError):
    """Raised when removing a player who is not a member of the group."""

    error_code: ClassVar[str] = "GROUP_PLAYER_NOT_FOUND"


class ServerNotFoundForAttachment(GroupError):
    """Raised when an attach/detach target server does not exist."""

    error_code: ClassVar[str] = "GROUP_ATTACH_SERVER_NOT_FOUND"


class ServerGroupAttachmentExistsError(GroupError):
    """Raised when attaching a group already attached to the same server."""

    error_code: ClassVar[str] = "GROUP_ATTACHMENT_EXISTS"


class ServerGroupAttachmentNotFoundError(GroupError):
    """Raised when detaching a group that is not currently attached."""

    error_code: ClassVar[str] = "GROUP_ATTACHMENT_NOT_FOUND"
