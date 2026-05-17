"""Static (mypy) Protocol conformance checks.

A `@runtime_checkable` `isinstance(repo, VersionRepository)` only verifies
that method **names** exist — it does not catch missing methods marked
async, wrong parameter types, or accidental `def` vs `async def`. Instead
we let mypy do the work: assigning each concrete implementation to a
variable typed as the Protocol forces structural-subtype checking at
type-check time. If a method drifts (signature, asyncness, return type)
mypy fails.

Two complementary defenses live here:

1. The `if TYPE_CHECKING:` block below is mypy's anchor. mypy treats it
   as live code; the runtime skips it.
2. A small runtime smoke test (`test_method_inventory_matches`) compares
   the public async/sync method names on each adapter against the
   Protocol so that obvious gaps are caught by `pytest` alone, before
   anyone runs mypy. This addresses PR #229 review item G.
"""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.adapters.uow import SqlAlchemyUnitOfWork
from app.versions.domain.ports import UnitOfWork, VersionRepository
from tests.unit.versions.fakes import FakeUnitOfWork, FakeVersionRepository

if TYPE_CHECKING:
    # These reveal_type-style annotations exist purely so mypy structurally
    # checks the bindings. Skipped at runtime to avoid constructing real
    # adapters with stub sessions.
    _real_repo: VersionRepository = SqlAlchemyVersionRepository(db=MagicMock(spec=Session))
    _fake_repo: VersionRepository = FakeVersionRepository()
    _real_uow: UnitOfWork = SqlAlchemyUnitOfWork(db=MagicMock(spec=Session))
    _fake_uow: UnitOfWork = FakeUnitOfWork()


def _public_methods(obj: object) -> set[str]:
    """Return the public method names of *obj* / its class."""
    return {
        name
        for name, value in inspect.getmembers(obj, predicate=callable)
        if not name.startswith("_")
    }


def _async_methods(obj: object) -> set[str]:
    """Return the names of the *async* public methods of *obj*."""
    return {
        name
        for name in _public_methods(obj)
        if inspect.iscoroutinefunction(getattr(obj, name))
    }


@pytest.fixture
def protocol_methods() -> set[str]:
    """Public method names declared on the `VersionRepository` Protocol."""
    return _public_methods(VersionRepository)


@pytest.fixture
def protocol_async_methods() -> set[str]:
    return _async_methods(VersionRepository)


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeVersionRepository(), id="fake"),
        pytest.param(
            SqlAlchemyVersionRepository(db=MagicMock(spec=Session)), id="sqlalchemy"
        ),
    ],
)
def test_implementation_covers_protocol_methods(
    implementation: VersionRepository, protocol_methods: set[str]
) -> None:
    """Every method on the Port must exist on every implementation."""
    missing = protocol_methods - _public_methods(implementation)
    assert missing == set(), (
        f"{type(implementation).__name__} is missing Port methods: {missing}"
    )


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeVersionRepository(), id="fake"),
        pytest.param(
            SqlAlchemyVersionRepository(db=MagicMock(spec=Session)), id="sqlalchemy"
        ),
    ],
)
def test_async_methods_match_protocol(
    implementation: VersionRepository, protocol_async_methods: set[str]
) -> None:
    """`async def` on the Port must remain `async def` on the implementation.

    This catches the most common Protocol drift bug — implementing
    `async def get_x(...)` from the Port as a plain `def get_x(...)`,
    which silently returns a coroutine-less value and breaks the first
    `await`.
    """
    impl_async = _async_methods(implementation)
    diff = protocol_async_methods - impl_async
    assert diff == set(), (
        f"{type(implementation).__name__} declared these as sync but the "
        f"Port marks them async: {diff}"
    )


def test_protocol_imports_succeed() -> None:
    """Importing the Protocols and adapters must not raise."""
    assert VersionRepository is not None
    assert UnitOfWork is not None
    assert SqlAlchemyVersionRepository is not None
    assert FakeVersionRepository is not None
