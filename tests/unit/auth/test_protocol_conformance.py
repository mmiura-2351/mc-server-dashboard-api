"""Static (mypy) + runtime Protocol conformance for the auth domain."""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.auth.adapters.repository import SqlAlchemyRefreshTokenRepository
from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
from app.auth.domain.ports import AuthUnitOfWork, RefreshTokenRepository
from tests.unit.auth.fakes import FakeAuthUnitOfWork, FakeRefreshTokenRepository

if TYPE_CHECKING:
    _real_repo: RefreshTokenRepository = SqlAlchemyRefreshTokenRepository(
        db=MagicMock(spec=Session)
    )
    _fake_repo: RefreshTokenRepository = FakeRefreshTokenRepository()
    _real_uow: AuthUnitOfWork = SqlAlchemyAuthUnitOfWork(db=MagicMock(spec=Session))
    _fake_uow: AuthUnitOfWork = FakeAuthUnitOfWork()


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


def _build_implementation(name: str) -> RefreshTokenRepository:
    # Constructed inside the test (not at parametrize-collection time) so
    # pytest-xdist does not have to pickle SQLAlchemy mocks across worker
    # boundaries — see PR #230 review follow-up for the CI failure.
    if name == "fake":
        return FakeRefreshTokenRepository()
    if name == "sqlalchemy":
        return SqlAlchemyRefreshTokenRepository(db=MagicMock(spec=Session))
    raise ValueError(f"unknown implementation: {name}")


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_implementation_covers_protocol_methods(impl_name: str) -> None:
    implementation = _build_implementation(impl_name)
    missing = _public_methods(RefreshTokenRepository) - _public_methods(implementation)
    assert missing == set()


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_async_methods_match_protocol(impl_name: str) -> None:
    implementation = _build_implementation(impl_name)
    diff = _async_methods(RefreshTokenRepository) - _async_methods(implementation)
    assert diff == set()
