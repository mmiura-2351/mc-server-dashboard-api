"""Backward-compatibility shim for the migrated group service.

The real implementation lives at `app.groups.application.service` and
is wired in production via `app.groups.api.dependencies.get_group_service`.
Only `app/servers/service.py:699` still imports this module — that
callsite contains a latent bug (`attach_server_to_group` was never a
real method; the actual name is `attach_group_to_server` with the
arguments reversed). To make that bug fail loudly, the alias on this
shim raises `NotImplementedError` rather than silently masking the
problem. See the follow-up issue referenced from the #226 PR.

TODO: once `app/servers/service.py` migrates to DI, delete this file.
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
    """Narrow legacy facade for `app/servers/service.py:699`.

    The only in-tree consumer outside the router invoked
    `GroupService(db).attach_server_to_group(group_id=..., server_id=..., db=db)`,
    which is a latent bug: the real method on the old service was
    `attach_group_to_server(user, server_id, group_id, priority)` and
    the call would raise `AttributeError` at runtime.

    Rather than silently masking the bug, this facade re-raises with a
    clear `NotImplementedError`. The bug is filed as a follow-up issue;
    see the PR description.

    For any other call shape, callers should depend on the hexagonal
    service via `Depends(get_group_service)` (see
    `app.groups.api.dependencies`).
    """

    def __init__(self, db: Any = None) -> None:
        # Accept `db=` so the call-site signature in
        # `app/servers/service.py:699` doesn't fail at construction time
        # — the AttributeError-equivalent surfaces on attribute access.
        self._db = db

    def attach_server_to_group(self, *args: Any, **kwargs: Any) -> Any:
        """Always raises.

        The legacy `app/servers/service.py:699` call expected this
        method to exist; it never did. Surfacing this as
        `NotImplementedError` makes the latent bug fail loudly instead
        of silently when someone exercises the
        `ServerCreateRequest.attach_groups` code path. The correct call
        is `attach_group_to_server(server_id=..., group_id=..., priority=0)`
        on the hexagonal `GroupService`; see the follow-up issue linked
        from the #226 PR.
        """
        raise NotImplementedError(
            "attach_server_to_group is not a valid method; use "
            "attach_group_to_server(server_id, group_id) via "
            "Depends(get_group_service)"
        )


# Public alias: legacy callers that still construct `GroupService(db)`
# get the facade class. The new DI-shaped application service is
# available at `app.groups.application.service.GroupService` for code
# that has migrated to Depends-based wiring.
GroupService = _LegacyGroupFacade
