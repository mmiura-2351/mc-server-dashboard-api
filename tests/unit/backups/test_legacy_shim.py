"""Pin the public surface of the legacy shim modules.

These shims live at `app.services.backup_service` and
`app.services.backup_scheduler`. They preserve a minimum API surface
for callers that have not yet migrated to DI (notably
`tests/test_security.py`). The tests below freeze the alias names and
shape so accidental shrinkage is caught at CI time.
"""

import inspect

import pytest

# ---------------------------------------------------------------------------
# backup_service shim
# ---------------------------------------------------------------------------


def test_backup_service_module_all_complete():
    import app.backups.adapters.legacy as mod

    expected = {
        "BackupService",
        "BackupFileService",
        "ResourceMonitor",
        "BackupValidationService",
        "backup_service",
        "BackupNotFoundException",
        "FileOperationException",
        "DatabaseOperationException",
        "ServerNotFoundException",
    }
    assert expected.issubset(set(mod.__all__))


def test_backup_service_alias_is_legacy_facade():
    from app.backups.adapters.legacy import BackupService, backup_service

    # The class alias is the facade; the singleton is an instance of it
    assert isinstance(backup_service, BackupService)


def test_backup_validation_service_still_exposed():
    """`tests/test_security.py:555` patches this — keep it exported."""
    from app.backups.adapters.legacy import BackupValidationService

    assert hasattr(BackupValidationService, "validate_server_for_backup")


def test_facade_methods_are_async():
    """All public facade methods must be `async def` so awaiters keep working."""
    from app.backups.adapters.legacy import _LegacyBackupFacade

    for name in [
        "create_backup",
        "restore_backup",
        "delete_backup",
        "upload_backup",
        "create_scheduled_backup",
    ]:
        method = getattr(_LegacyBackupFacade, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"


# ---------------------------------------------------------------------------
# backup_scheduler shim
# ---------------------------------------------------------------------------


def test_backup_scheduler_module_all():
    import app.backups.application.scheduler as mod

    assert "BackupSchedulerService" in mod.__all__
    assert "backup_scheduler" in mod.__all__


def test_scheduler_proxy_hasattr_before_init():
    """`hasattr(backup_scheduler, "start_scheduler")` must be True even
    before the lifespan callback has populated the instance holder.

    Pinned by `tests/integration/test_main_comprehensive.py:628`.
    """
    from app.backups import backup_scheduler_instance
    from app.backups.application.scheduler import backup_scheduler

    backup_scheduler_instance.clear()
    try:
        assert hasattr(backup_scheduler, "start_scheduler")
        assert hasattr(backup_scheduler, "stop_scheduler")
        assert hasattr(backup_scheduler, "create_schedule")
        assert hasattr(backup_scheduler, "clear_cache")
    finally:
        # Other tests may rely on the holder being clean.
        backup_scheduler_instance.clear()


def test_scheduler_proxy_raises_before_init():
    """Method invocation before init must give a clear RuntimeError."""
    from app.backups import backup_scheduler_instance
    from app.backups.application.scheduler import backup_scheduler

    backup_scheduler_instance.clear()
    with pytest.raises(RuntimeError, match="not initialised"):
        backup_scheduler.clear_cache()


def test_scheduler_proxy_methods_are_async():
    """Every forwarded method must be `async def`."""
    from app.backups.application.scheduler import _SchedulerProxy

    for name in [
        "create_schedule",
        "update_schedule",
        "delete_schedule",
        "get_schedule",
        "list_schedules",
        "get_due_schedules",
        "list_logs_for_server",
        "start_scheduler",
        "stop_scheduler",
        "load_schedules_from_db",
    ]:
        method = getattr(_SchedulerProxy, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"
