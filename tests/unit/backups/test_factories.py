"""Smoke tests for the factory helpers."""

from app.backups.application.factories import (
    make_backup_scheduler,
    make_backup_service,
)
from app.backups.application.scheduler import BackupSchedulerService
from app.backups.application.service import BackupService


class TestFactories:
    def test_make_backup_service_shape(self, db):
        service = make_backup_service(db)
        assert isinstance(service, BackupService)
        # Internals are private; assert by attribute presence
        assert service._uow is not None
        assert service._server_read is not None
        assert service.backups_directory.exists()

    def test_make_backup_scheduler_shape(self):
        scheduler = make_backup_scheduler()
        assert isinstance(scheduler, BackupSchedulerService)
        # Callables, not pre-bound instances
        assert callable(scheduler._uow_factory)
        assert callable(scheduler._server_read_factory)
