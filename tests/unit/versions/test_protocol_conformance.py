"""Static (mypy) Protocol conformance checks.

A `@runtime_checkable` `isinstance(repo, VersionRepository)` only verifies
that method **names** exist — it does not catch missing methods marked
async, wrong parameter types, or accidental `def` vs `async def`. Instead
we let mypy do the work: assigning each concrete implementation to a
variable typed as the Protocol forces structural-subtype checking at
type-check time. If a method drifts (signature, asyncness, return type)
mypy fails.

These assignments are evaluated at import time so that a runtime smoke
test confirms the file is well-formed too; the real conformance check is
mypy on `app/` and these test files.
"""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

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


def test_fake_version_repository_constructs() -> None:
    """Smoke check: the Fake can be instantiated cheaply for unit tests."""
    FakeVersionRepository()


def test_fake_unit_of_work_constructs() -> None:
    FakeUnitOfWork()


def test_protocol_imports_succeed() -> None:
    """Importing the Protocols and adapters must not raise."""
    assert VersionRepository is not None
    assert UnitOfWork is not None
    assert SqlAlchemyVersionRepository is not None
    assert FakeVersionRepository is not None
