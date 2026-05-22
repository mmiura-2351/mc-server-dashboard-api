"""Both `Fake*` and `SqlAlchemy*` repositories must structurally satisfy
the same Protocols. Smoke-test their public surface symmetrically.
"""

import inspect

from app.core.visibility.adapters.repository import SqlAlchemyVisibilityRepository
from app.core.visibility.domain.ports import VisibilityRepository
from tests.unit.core.visibility.fakes import FakeVisibilityRepository


def _public_methods(cls) -> set:
    return {
        name
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def _protocol_methods(proto) -> set:
    """Return the method names declared on a Protocol class."""
    return {
        name
        for name, attr in proto.__dict__.items()
        if callable(attr) and not name.startswith("_")
    }


def test_visibility_repository_protocol_methods():
    expected = _protocol_methods(VisibilityRepository)
    assert _public_methods(FakeVisibilityRepository) >= expected
    assert _public_methods(SqlAlchemyVisibilityRepository) >= expected
