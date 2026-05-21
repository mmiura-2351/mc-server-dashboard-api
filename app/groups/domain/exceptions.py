"""Domain exceptions raised by the groups application service.

The router catches these and maps them to HTTPException; the legacy
shim re-exports them so callers can `except GroupError` regardless of
import path.
"""


class GroupError(Exception):
    """Base exception for group operations."""


class GroupNotFoundError(GroupError):
    """Raised when a referenced group does not exist."""


class GroupAlreadyExistsError(GroupError):
    """Raised when a (owner, name) pair collides with an existing group."""


class GroupAccessError(GroupError):
    """Raised when a viewer lacks permission to read or modify a group."""


class GroupHasAttachmentsError(GroupError):
    """Raised when attempting to delete a group still attached to servers."""


class PlayerNotFoundInGroup(GroupError):
    """Raised when removing a player who is not a member of the group."""


class ServerNotFoundForAttachment(GroupError):
    """Raised when an attach/detach target server does not exist."""


class ServerGroupAttachmentExistsError(GroupError):
    """Raised when attaching a group already attached to the same server."""


class ServerGroupAttachmentNotFoundError(GroupError):
    """Raised when detaching a group that is not currently attached."""
