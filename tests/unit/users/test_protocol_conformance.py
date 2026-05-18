"""Static (mypy) + runtime Protocol conformance for the users domain.

Mirrors `tests.unit.versions.test_protocol_conformance` — see that file
for the rationale behind the two-layer (mypy + runtime smoke) approach.
"""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.users.adapters.read_port import SqlAlchemyUserReadPort
from app.users.adapters.repository import SqlAlchemyUserRepository
from app.users.adapters.uow import SqlAlchemyUsersUnitOfWork
from app.users.domain.ports import UserReadPort, UserRepository, UsersUnitOfWork
from tests.unit.users.fakes import FakeUserRepository, FakeUsersUnitOfWork

if TYPE_CHECKING:
    _real_repo: UserRepository = SqlAlchemyUserRepository(db=MagicMock(spec=Session))
    _fake_repo: UserRepository = FakeUserRepository()
    _real_read: UserReadPort = SqlAlchemyUserReadPort(db=MagicMock(spec=Session))
    _fake_read: UserReadPort = FakeUserRepository()
    _real_uow: UsersUnitOfWork = SqlAlchemyUsersUnitOfWork(db=MagicMock(spec=Session))
    _fake_uow: UsersUnitOfWork = FakeUsersUnitOfWork()


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


def _build_implementation(name: str) -> UserRepository:
    # Constructed inside the test (not at parametrize-collection time) so
    # pytest-xdist does not have to pickle SQLAlchemy mocks across worker
    # boundaries — that path is what triggered the CI RecursionError.
    if name == "fake":
        return FakeUserRepository()
    if name == "sqlalchemy":
        return SqlAlchemyUserRepository(db=MagicMock(spec=Session))
    raise ValueError(f"unknown implementation: {name}")


@pytest.fixture
def protocol_methods() -> set[str]:
    return _public_methods(UserRepository)


@pytest.fixture
def protocol_async_methods() -> set[str]:
    return _async_methods(UserRepository)


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_implementation_covers_protocol_methods(
    impl_name: str, protocol_methods: set[str]
) -> None:
    implementation = _build_implementation(impl_name)
    missing = protocol_methods - _public_methods(implementation)
    assert missing == set()


@pytest.mark.parametrize("impl_name", ["fake", "sqlalchemy"])
def test_async_methods_match_protocol(
    impl_name: str, protocol_async_methods: set[str]
) -> None:
    implementation = _build_implementation(impl_name)
    impl_async = _async_methods(implementation)
    diff = protocol_async_methods - impl_async
    assert diff == set()


def test_protocol_imports_succeed() -> None:
    assert UserRepository is not None
    assert UserReadPort is not None
    assert UsersUnitOfWork is not None
    assert SqlAlchemyUserRepository is not None
    assert FakeUserRepository is not None
