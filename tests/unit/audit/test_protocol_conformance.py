"""Static (mypy) + runtime Protocol conformance for the audit domain.

Same two-layer approach as `tests.unit.versions.test_protocol_conformance`:
the `TYPE_CHECKING` block lets mypy verify structural conformance, and
the runtime parametrize confirms that the public method names line up
(catches drift caused by renaming a Port method without updating an
adapter).
"""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.audit.adapters.repository import (
    SqlAlchemyAuditRepository,
    SqlAlchemyAuditWriter,
)
from app.audit.domain.ports import AuditRepository, AuditWriter
from tests.unit.audit.fakes import FakeAuditRepository, FakeAuditWriter

if TYPE_CHECKING:
    _real_repo: AuditRepository = SqlAlchemyAuditRepository(db=MagicMock(spec=Session))
    _fake_repo: AuditRepository = FakeAuditRepository()
    _real_writer: AuditWriter = SqlAlchemyAuditWriter(db=MagicMock(spec=Session))
    _fake_writer: AuditWriter = FakeAuditWriter()


def _public_methods(obj: object) -> set[str]:
    return {
        name
        for name, value in inspect.getmembers(obj, predicate=callable)
        if not name.startswith("_")
    }


def _async_methods(obj: object) -> set[str]:
    return {
        name
        for name in _public_methods(obj)
        if inspect.iscoroutinefunction(getattr(obj, name))
    }


def _build_repo(name: str) -> AuditRepository:
    # Constructed inside the test (not at parametrize collection time)
    # so pytest-xdist does not need to pickle SQLAlchemy mocks across
    # worker boundaries — see the PR #230 follow-up notes for the
    # CI failure that motivated this pattern.
    if name == "fake":
        return FakeAuditRepository()
    if name == "sqlalchemy":
        return SqlAlchemyAuditRepository(db=MagicMock(spec=Session))
    raise ValueError(f"unknown repo implementation: {name}")


def _build_writer(name: str) -> AuditWriter:
    if name == "fake":
        return FakeAuditWriter()
    if name == "sqlalchemy":
        return SqlAlchemyAuditWriter(db=MagicMock(spec=Session))
    raise ValueError(f"unknown writer implementation: {name}")


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_repository_covers_protocol_methods(impl_name: str) -> None:
    impl = _build_repo(impl_name)
    missing = _public_methods(AuditRepository) - _public_methods(impl)
    assert missing == set()


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_repository_async_methods_match_protocol(impl_name: str) -> None:
    impl = _build_repo(impl_name)
    diff = _async_methods(AuditRepository) - _async_methods(impl)
    assert diff == set()


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_writer_covers_protocol_methods(impl_name: str) -> None:
    impl = _build_writer(impl_name)
    missing = _public_methods(AuditWriter) - _public_methods(impl)
    assert missing == set()


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_writer_methods_are_sync(impl_name: str) -> None:
    """`AuditWriter.record` is intentionally **sync** — see ports.py docstring."""
    impl = _build_writer(impl_name)
    assert "record" in _public_methods(impl)
    assert not inspect.iscoroutinefunction(impl.record)
