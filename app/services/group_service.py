"""Backward-compatibility shim for the migrated group service.

The real implementation lives at `app.groups.application.service` and
is wired in production via `app.groups.api.dependencies.get_group_service`.

Historically this shim carried a narrow legacy facade with a
deliberately-failing wrong-named attachment method to flag the latent
bug at `app/servers/service.py:699`. That bug was resolved in #228 PR
2c (the create-server flow now goes through the correct
`GroupService.attach_group_to_server` call via DI), so the facade
shrinks to a no-op alias that simply re-exports the domain exception
classes for any tests / external callers that still import them.
"""

from typing import Any

from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupError,
    GroupHasAttachmentsError,
    GroupNotFoundError,
    PlayerNotFoundInGroup,
    ServerGroupAttachmentExistsError,
    ServerGroupAttachmentNotFoundError,
    ServerNotFoundForAttachment,
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
]


class _LegacyGroupFacade:
    """Narrow legacy facade preserved for back-compat callers.

    Carries no methods today. The pre-#228 attribute that raised
    `NotImplementedError` for the wrong-name attachment call was
    deleted because the latent bug it was guarding is now fixed — see
    `app.servers.application.service.ServerService.create_server`,
    which uses the correct `attach_group_to_server` call shape.
    """

    def __init__(self, db: Any = None) -> None:
        self._db = db


# Public alias: legacy callers that still construct `GroupService(db)`
# get the facade class. The new DI-shaped application service is
# available at `app.groups.application.service.GroupService` for code
# that has migrated to Depends-based wiring.
GroupService = _LegacyGroupFacade
