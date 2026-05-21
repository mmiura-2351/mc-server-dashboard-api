"""Both `FakeServerRepository` and `SqlAlchemyServerRepository` must
structurally satisfy the same Protocol. Smoke-test their public
surface symmetrically.

Mirrors `tests.unit.backups.test_protocol_conformance`.
"""

import inspect

from app.servers.adapters.repository import SqlAlchemyServerRepository
from app.servers.domain.ports import ServerRepository
from tests.unit.servers.fakes import FakeServerRepository


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


def test_server_repository_protocol_methods():
    expected = _protocol_methods(ServerRepository)
    assert _public_methods(FakeServerRepository) >= expected
    assert _public_methods(SqlAlchemyServerRepository) >= expected


def test_server_repository_protocol_excludes_forbidden_methods():
    """D-1 guard: sibling-aggregate accessors must not leak onto the
    servers Repository surface — callers wire `BackupRepository` /
    `TemplateRepository` directly.
    """
    proto_methods = _protocol_methods(ServerRepository)
    assert "get_backup" not in proto_methods
    assert "get_template" not in proto_methods
