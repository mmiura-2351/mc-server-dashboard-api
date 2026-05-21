"""Static (mypy) Protocol conformance checks for the templates domain.

Mirrors `tests.unit.files.test_protocol_conformance`: lets mypy verify
structural subtyping at type-check time and provides a runtime smoke
test that catches missing methods or sync/async drift without needing
mypy in the loop.

Pinning the async shape of every method also catches the failure mode
where a previously-sync method silently becomes async (`@patch`
callsites then need an `AsyncMock`); CI fails here before silently
broken integration tests can be merged.
"""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.templates.adapters.repository import SqlAlchemyTemplateRepository
from app.templates.adapters.uow import SqlAlchemyTemplatesUnitOfWork
from app.templates.domain.ports import TemplateRepository, TemplatesUnitOfWork
from tests.unit.templates.fakes import (
    FakeTemplateRepository,
    FakeTemplatesUnitOfWork,
)

if TYPE_CHECKING:
    _real_repo: TemplateRepository = SqlAlchemyTemplateRepository(
        db=MagicMock(spec=Session)
    )
    _fake_repo: TemplateRepository = FakeTemplateRepository()
    _real_uow: TemplatesUnitOfWork = SqlAlchemyTemplatesUnitOfWork(
        db=MagicMock(spec=Session)
    )
    _fake_uow: TemplatesUnitOfWork = FakeTemplatesUnitOfWork()


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


@pytest.fixture
def protocol_methods() -> set[str]:
    return _public_methods(TemplateRepository)


@pytest.fixture
def protocol_async_methods() -> set[str]:
    return _async_methods(TemplateRepository)


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeTemplateRepository(), id="fake"),
        pytest.param(
            SqlAlchemyTemplateRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_implementation_covers_protocol_methods(
    implementation: TemplateRepository, protocol_methods: set[str]
) -> None:
    missing = protocol_methods - _public_methods(implementation)
    assert missing == set(), (
        f"{type(implementation).__name__} is missing Port methods: {missing}"
    )


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeTemplateRepository(), id="fake"),
        pytest.param(
            SqlAlchemyTemplateRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_async_methods_match_protocol(
    implementation: TemplateRepository, protocol_async_methods: set[str]
) -> None:
    impl_async = _async_methods(implementation)
    diff = protocol_async_methods - impl_async
    assert diff == set(), (
        f"{type(implementation).__name__} declared these as sync but the "
        f"Port marks them async: {diff}"
    )


def test_protocol_imports_succeed() -> None:
    assert TemplateRepository is not None
    assert TemplatesUnitOfWork is not None
    assert SqlAlchemyTemplateRepository is not None
    assert SqlAlchemyTemplatesUnitOfWork is not None
    assert FakeTemplateRepository is not None
    assert FakeTemplatesUnitOfWork is not None
