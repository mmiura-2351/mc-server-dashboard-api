"""Backward-compatibility tests for `app.services.group_service`.

Pin the import path, the explicit `__all__`, and the exception
re-exports so a future cleanup cannot silently break the contract.

The pre-#228 contract that the facade's `attach_server_to_group`
attribute raise `NotImplementedError` has been removed because the
latent bug it guarded was fixed in #228 PR 2c — the create-server
flow now uses the correct `attach_group_to_server` call via DI.
"""

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
    `_LegacyGroupFacade`."""
    assert shim_module.GroupService is _LegacyGroupFacade
    instance = shim_module.GroupService(db=object())
    assert isinstance(instance, _LegacyGroupFacade)


def test_facade_no_longer_exposes_attach_server_to_group():
    """The latent-bug guard `attach_server_to_group` was removed in
    #228 PR 2c once the create-server flow stopped invoking it."""
    instance = shim_module.GroupService(db=object())
    assert not hasattr(instance, "attach_server_to_group")


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
