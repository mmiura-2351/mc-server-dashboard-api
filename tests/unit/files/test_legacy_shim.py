"""Backward-compatibility tests for `app.services.file_history_service`.

This shim exists for callers (currently
`app.files.application.management`) that still pass an explicit DB
session and expect a module-level `file_history_service` singleton.
Pin both the import path and the call shape so a future cleanup
cannot silently break the only remaining legacy consumer.

TODO(#228): delete this file when the shim is removed.
"""

import inspect

import pytest

from app.files.application import legacy as shim_module
from app.files.application.service import FileHistoryService as ApplicationService


def test_shim_exposes_singleton():
    assert hasattr(shim_module, "file_history_service")
    assert shim_module.file_history_service is not None


def test_shim_reexports_application_class():
    """`FileHistoryService` is exported from the shim for any deep
    import that bypasses `app.files.application.service`."""
    assert shim_module.FileHistoryService is ApplicationService


def test_legacy_singleton_create_version_backup_requires_db():
    """Legacy callers must pass `db=`; the security check is part of
    the contract."""
    coro = shim_module.file_history_service.create_version_backup(
        server_id=1, file_path="x.txt", content="x\n", db=None
    )
    with pytest.raises(ValueError, match="Database session is required"):
        # `create_version_backup` is async; consume the coroutine to surface
        # the ValueError synchronously.
        coro.send(None)


def test_legacy_singleton_method_is_async():
    """Pin async-ness so a refactor cannot accidentally drop it."""
    method = shim_module.file_history_service.create_version_backup
    assert inspect.iscoroutinefunction(method)
