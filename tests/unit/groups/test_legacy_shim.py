"""Backward-compatibility tests for `app.services.group_service`.

The shim is intentionally narrow: the only in-tree consumer is
`app/servers/service.py:699`, which (latent bug, see PR description)
invokes a non-existent `attach_server_to_group` method. The shim
surfaces that as `NotImplementedError` so the bug fails loudly.

Pin the import path, the explicit `__all__`, and the exception
re-exports so a future cleanup cannot silently break the contract.
"""

import pytest

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
from app.services import group_service as shim_module
from app.services.group_service import _LegacyGroupFacade


def test_group_service_alias_is_facade_class():
    """`GroupService` exported from the shim is an alias to
    `_LegacyGroupFacade` so the legacy `GroupService(db)` construction
    in `app/servers/service.py:696` keeps working."""
    assert shim_module.GroupService is _LegacyGroupFacade
    instance = shim_module.GroupService(db=object())
    assert isinstance(instance, _LegacyGroupFacade)


@pytest.mark.asyncio
async def test_attach_server_to_group_raises_not_implemented():
    """Pin the latent-bug visibility contract: the legacy call shape
    used by `app/servers/service.py:699` must raise — silently
    swallowing the bug would be worse than reporting it."""
    instance = shim_module.GroupService(db=object())
    with pytest.raises(NotImplementedError, match="attach_server_to_group"):
        await instance.attach_server_to_group(group_id=1, server_id=1, db=object())


def test_shim_reexports_exception_classes():
    """Exception class identity is part of the public contract — both
    `app.services.group_service.GroupError` and
    `app.groups.domain.exceptions.GroupError` must reference the same
    class so `except` blocks work whichever import path callers used."""
    assert shim_module.GroupError is GroupError
    assert shim_module.GroupNotFoundError is GroupNotFoundError
    assert shim_module.GroupAlreadyExistsError is GroupAlreadyExistsError
    assert shim_module.GroupAccessError is GroupAccessError
    assert shim_module.GroupHasAttachmentsError is GroupHasAttachmentsError
    assert shim_module.PlayerNotFoundInGroup is PlayerNotFoundInGroup
    assert shim_module.ServerNotFoundForAttachment is ServerNotFoundForAttachment
    assert (
        shim_module.ServerGroupAttachmentExistsError
        is ServerGroupAttachmentExistsError
    )
    assert (
        shim_module.ServerGroupAttachmentNotFoundError
        is ServerGroupAttachmentNotFoundError
    )


def test_shim_has_explicit_all():
    """No `from X import *` allowed — the shim must declare `__all__`
    so accidental re-exports are caught at review time."""
    assert hasattr(shim_module, "__all__")
    assert set(shim_module.__all__) == {
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
    }


def test_no_legacy_helper_classes_exposed():
    """`GroupAccessService` / `GroupFileService` were removed with the
    shim shrink. Asserting their absence catches accidental
    reintroduction."""
    assert not hasattr(shim_module, "GroupAccessService")
    assert not hasattr(shim_module, "GroupFileService")
