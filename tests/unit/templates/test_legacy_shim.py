"""Backward-compatibility tests for `app.services.template_service`.

This shim exists for callers (currently `app.services.backup_service`)
that still pass an explicit DB session and expect a module-level
`template_service` singleton. Pin both the import path and the call
shape so a future cleanup cannot silently break the only remaining
legacy consumer.

TODO(#228): delete this file when the shim is removed.
"""

import inspect

import pytest

from app.templates.application import legacy as shim_module
from app.templates.application.legacy import _LegacyTemplateFacade
from app.templates.domain.exceptions import (
    TemplateAccessError,
    TemplateCreationError,
    TemplateError,
    TemplateNotFoundError,
)


def test_shim_exposes_singleton():
    assert hasattr(shim_module, "template_service")
    assert shim_module.template_service is not None
    assert isinstance(shim_module.template_service, _LegacyTemplateFacade)


def test_template_service_alias_is_facade_class():
    """Per the orchestrator spec, `TemplateService` exported from the
    shim is an alias to `_LegacyTemplateFacade` so legacy callers can
    instantiate it with `TemplateService()` (no args). This pins the
    backup_service callsite (`app/services/backup_service.py`) — if
    someone refactors the alias away, that path breaks at import-time."""
    assert shim_module.TemplateService is _LegacyTemplateFacade
    # And it must be zero-arg constructible (the backup-service callsite
    # `TemplateService()` used to work; legacy callers may still rely on it)
    instance = shim_module.TemplateService()
    assert isinstance(instance, _LegacyTemplateFacade)


def test_shim_reexports_exception_classes():
    """Exception class identity is part of the public contract — both
    `app.services.template_service.TemplateError` and
    `app.templates.domain.exceptions.TemplateError` must reference the
    same class so `except` blocks work whichever import path callers used."""
    assert shim_module.TemplateError is TemplateError
    assert shim_module.TemplateNotFoundError is TemplateNotFoundError
    assert shim_module.TemplateCreationError is TemplateCreationError
    assert shim_module.TemplateAccessError is TemplateAccessError


def test_shim_has_explicit_all():
    """No `from X import *` allowed — the shim must declare `__all__`
    so accidental re-exports are caught at review time."""
    assert hasattr(shim_module, "__all__")
    expected = {
        "TemplateService",
        "TemplateError",
        "TemplateNotFoundError",
        "TemplateCreationError",
        "TemplateAccessError",
        "template_service",
    }
    assert expected.issubset(set(shim_module.__all__))


def test_legacy_create_template_from_server_requires_db():
    """The legacy security contract: passing `db=None` raises
    `TemplateError`, NOT `ValueError`. This is the boundary documented
    on the original `TemplateService.create_template_from_server`."""
    coro = shim_module.template_service.create_template_from_server(
        server_id=1, name="x", db=None, creator=None
    )
    with pytest.raises(TemplateError, match="Database session is required"):
        coro.send(None)


def test_legacy_create_template_from_server_requires_creator():
    """Pin the second legacy security contract: even when a `db=` session
    is supplied, omitting `creator=` must raise `TemplateError`. The
    `db` check runs first, so we pass a sentinel session to reach the
    `creator is None` branch."""
    sentinel_db = object()  # never touched: creator check raises first
    coro = shim_module.template_service.create_template_from_server(
        server_id=1, name="x", db=sentinel_db, creator=None
    )
    with pytest.raises(TemplateError, match="Creator user is required"):
        coro.send(None)


def test_legacy_create_template_from_server_is_async():
    """Pin async-ness so a refactor cannot accidentally drop it."""
    method = shim_module.template_service.create_template_from_server
    assert inspect.iscoroutinefunction(method)


def test_legacy_create_custom_template_is_async():
    method = shim_module.template_service.create_custom_template
    assert inspect.iscoroutinefunction(method)
