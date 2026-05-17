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


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeRefreshTokenRepository(), id="fake"),
        pytest.param(
            SqlAlchemyRefreshTokenRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_implementation_covers_protocol_methods(
    implementation: RefreshTokenRepository,
) -> None:
    missing = _public_methods(RefreshTokenRepository) - _public_methods(implementation)
    assert missing == set()


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeRefreshTokenRepository(), id="fake"),
        pytest.param(
            SqlAlchemyRefreshTokenRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_async_methods_match_protocol(implementation: RefreshTokenRepository) -> None:
    diff = _async_methods(RefreshTokenRepository) - _async_methods(implementation)
    assert diff == set()
