"""Legacy group-service no-op facade.

Migrated from `app.services.group_service` under #228 PR 3. The real
group service lives at `app.groups.application.service` and is wired
through `Depends(get_group_service)` in production.

The class `_LegacyGroupFacade` carries no methods today. The pre-#228
attribute that raised `NotImplementedError` for the wrong-name
attachment call was deleted because the latent bug it was guarding
is now fixed in `app.servers.application.service.ServerService.create_server`.
"""

from typing import Any

from app.groups.domain.exceptions import (
    GroupAccessError,  # noqa: F401
    GroupAlreadyExistsError,  # noqa: F401
    GroupError,  # noqa: F401
    GroupHasAttachmentsError,  # noqa: F401
    GroupNotFoundError,  # noqa: F401
    PlayerNotFoundInGroup,  # noqa: F401
    ServerGroupAttachmentExistsError,  # noqa: F401
    ServerGroupAttachmentNotFoundError,  # noqa: F401
    ServerNotFoundForAttachment,  # noqa: F401
)

__all__ = [
    "GroupService",
    "GroupError",
    "GroupNotFoundError",
    "GroupAlreadyExistsError",
    "GroupAccessError",
    "GroupHasAttachmentsError",
    "PlayerNotFoundInGroup",
    "ServerNotFoundForAttachment",
    "ServerGroupAttachmentExistsError",
    "ServerGroupAttachmentNotFoundError",
    "_LegacyGroupFacade",
]


class _LegacyGroupFacade:
    """Narrow legacy facade preserved for back-compat callers."""

    def __init__(self, db: Any = None) -> None:
        # db kwarg retained for legacy signature parity; unused since #228 PR 2b.
        pass


# Public alias: legacy callers that still construct `GroupService(db)`
# get the facade class.
GroupService = _LegacyGroupFacade
