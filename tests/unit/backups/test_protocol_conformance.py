"""Both `Fake*` and `SqlAlchemy*` repositories must structurally satisfy
the same Protocols. Smoke-test their public surface symmetrically.
"""

import inspect

from app.backups.adapters.repository import (
    SqlAlchemyBackupRepository,
    SqlAlchemyBackupScheduleRepository,
)
from app.backups.domain.ports import BackupRepository, BackupScheduleRepository
from tests.unit.backups.fakes import (
    FakeBackupRepository,
    FakeBackupScheduleRepository,
)


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


def test_backup_repository_protocol_methods():
    expected = _protocol_methods(BackupRepository)
    assert _public_methods(FakeBackupRepository) >= expected
    assert _public_methods(SqlAlchemyBackupRepository) >= expected


def test_schedule_repository_protocol_methods():
    expected = _protocol_methods(BackupScheduleRepository)
    assert _public_methods(FakeBackupScheduleRepository) >= expected
    assert _public_methods(SqlAlchemyBackupScheduleRepository) >= expected
