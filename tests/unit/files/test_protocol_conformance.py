"""Static (mypy) Protocol conformance checks for the files domain.

Mirrors `tests.unit.versions.test_protocol_conformance`: lets mypy
verify structural subtyping at type-check time and provides a small
runtime smoke test that catches obvious gaps (missing methods, sync
vs async drift) without needing mypy to be in the loop.
"""

import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.files.adapters.repository import SqlAlchemyFileHistoryRepository
from app.files.adapters.uow import SqlAlchemyFilesUnitOfWork
from app.files.domain.ports import FileHistoryRepository, FilesUnitOfWork
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.domain.ports import ServerReadPort
from tests.unit.files.fakes import (
    FakeFileHistoryRepository,
    FakeFilesUnitOfWork,
    FakeServerReadPort,
)

if TYPE_CHECKING:
    _real_repo: FileHistoryRepository = SqlAlchemyFileHistoryRepository(
        db=MagicMock(spec=Session)
    )
    _fake_repo: FileHistoryRepository = FakeFileHistoryRepository()
    _real_uow: FilesUnitOfWork = SqlAlchemyFilesUnitOfWork(db=MagicMock(spec=Session))
    _fake_uow: FilesUnitOfWork = FakeFilesUnitOfWork()
    _real_read: ServerReadPort = SqlAlchemyServerReadPort(db=MagicMock(spec=Session))
    _fake_read: ServerReadPort = FakeServerReadPort()


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
    return _public_methods(FileHistoryRepository)


@pytest.fixture
def protocol_async_methods() -> set[str]:
    return _async_methods(FileHistoryRepository)


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeFileHistoryRepository(), id="fake"),
        pytest.param(
            SqlAlchemyFileHistoryRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_implementation_covers_protocol_methods(
    implementation: FileHistoryRepository, protocol_methods: set[str]
) -> None:
    missing = protocol_methods - _public_methods(implementation)
    assert missing == set(), (
        f"{type(implementation).__name__} is missing Port methods: {missing}"
    )


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeFileHistoryRepository(), id="fake"),
        pytest.param(
            SqlAlchemyFileHistoryRepository(db=MagicMock(spec=Session)),
            id="sqlalchemy",
        ),
    ],
)
def test_async_methods_match_protocol(
    implementation: FileHistoryRepository, protocol_async_methods: set[str]
) -> None:
    impl_async = _async_methods(implementation)
    diff = protocol_async_methods - impl_async
    assert diff == set(), (
        f"{type(implementation).__name__} declared these as sync but the "
        f"Port marks them async: {diff}"
    )


@pytest.mark.parametrize(
    "implementation",
    [
        pytest.param(FakeServerReadPort(), id="fake"),
        pytest.param(
            SqlAlchemyServerReadPort(db=MagicMock(spec=Session)), id="sqlalchemy"
        ),
    ],
)
def test_server_read_port_implementations(
    implementation: ServerReadPort,
) -> None:
    """`ServerReadPort` has a single async method; pin its shape."""
    expected = _public_methods(ServerReadPort)
    missing = expected - _public_methods(implementation)
    assert missing == set()
    assert inspect.iscoroutinefunction(getattr(implementation, "get_directory_path"))


def test_protocol_imports_succeed() -> None:
    assert FileHistoryRepository is not None
    assert FilesUnitOfWork is not None
    assert ServerReadPort is not None
    assert SqlAlchemyFileHistoryRepository is not None
    assert FakeFileHistoryRepository is not None
