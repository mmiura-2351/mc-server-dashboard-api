"""Static (mypy) Protocol conformance checks for the groups domain.

Lets mypy
verify structural subtyping at type-check time and provides a runtime
smoke test that catches missing methods or sync/async drift without
needing mypy in the loop.

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

from app.groups.adapters.repository import (
    SqlAlchemyGroupRepository,
    SqlAlchemyServerGroupRepository,
)
from app.groups.adapters.uow import SqlAlchemyGroupsUnitOfWork
from app.groups.domain.ports import (
    GroupRepository,
    GroupsUnitOfWork,
    ServerGroupRepository,
)
from tests.unit.groups.fakes import (
    FakeGroupRepository,
    FakeGroupsUnitOfWork,
    FakeServerGroupRepository,
)

if TYPE_CHECKING:
    _real_repo: GroupRepository = SqlAlchemyGroupRepository(db=MagicMock(spec=Session))
    _fake_repo: GroupRepository = FakeGroupRepository()
    _real_sg_repo: ServerGroupRepository = SqlAlchemyServerGroupRepository(
        db=MagicMock(spec=Session)
    )
    _fake_sg_repo: ServerGroupRepository = FakeServerGroupRepository()
    _real_uow: GroupsUnitOfWork = SqlAlchemyGroupsUnitOfWork(db=MagicMock(spec=Session))
    _fake_uow: GroupsUnitOfWork = FakeGroupsUnitOfWork()


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


# ---- GroupRepository ----


@pytest.fixture
def group_repo_protocol_methods() -> set[str]:
    return _public_methods(GroupRepository)


@pytest.fixture
def group_repo_async_methods() -> set[str]:
    return _async_methods(GroupRepository)


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeGroupRepository(), id="fake"),
        pytest.param(
            SqlAlchemyGroupRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_group_repository_covers_protocol(
    implementation: GroupRepository,
    group_repo_protocol_methods: set[str],
) -> None:
    missing = group_repo_protocol_methods - _public_methods(implementation)
    assert missing == set(), (
        f"{type(implementation).__name__} is missing Port methods: {missing}"
    )


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeGroupRepository(), id="fake"),
        pytest.param(
            SqlAlchemyGroupRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_group_repository_async_methods_match(
    implementation: GroupRepository,
    group_repo_async_methods: set[str],
) -> None:
    impl_async = _async_methods(implementation)
    diff = group_repo_async_methods - impl_async
    assert diff == set(), (
        f"{type(implementation).__name__} declared these as sync but the "
        f"Port marks them async: {diff}"
    )


# ---- ServerGroupRepository ----


@pytest.fixture
def server_group_repo_protocol_methods() -> set[str]:
    return _public_methods(ServerGroupRepository)


@pytest.fixture
def server_group_repo_async_methods() -> set[str]:
    return _async_methods(ServerGroupRepository)


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeServerGroupRepository(), id="fake"),
        pytest.param(
            SqlAlchemyServerGroupRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_server_group_repository_covers_protocol(
    implementation: ServerGroupRepository,
    server_group_repo_protocol_methods: set[str],
) -> None:
    missing = server_group_repo_protocol_methods - _public_methods(implementation)
    assert missing == set(), (
        f"{type(implementation).__name__} is missing Port methods: {missing}"
    )


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeServerGroupRepository(), id="fake"),
        pytest.param(
            SqlAlchemyServerGroupRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_server_group_repository_async_methods_match(
    implementation: ServerGroupRepository,
    server_group_repo_async_methods: set[str],
) -> None:
    impl_async = _async_methods(implementation)
    diff = server_group_repo_async_methods - impl_async
    assert diff == set(), (
        f"{type(implementation).__name__} declared these as sync but the "
        f"Port marks them async: {diff}"
    )


def test_protocol_imports_succeed() -> None:
    assert GroupRepository is not None
    assert ServerGroupRepository is not None
    assert GroupsUnitOfWork is not None
    assert SqlAlchemyGroupRepository is not None
    assert SqlAlchemyServerGroupRepository is not None
    assert SqlAlchemyGroupsUnitOfWork is not None
    assert FakeGroupRepository is not None
    assert FakeServerGroupRepository is not None
    assert FakeGroupsUnitOfWork is not None
