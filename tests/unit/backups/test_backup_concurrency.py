"""Tests that the backup semaphore limits concurrent operations (Issue #351)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.backups.application.service import BackupService
from app.backups.models import BackupType
from app.core.concurrency import ConcurrencySemaphore, SemaphoreRegistry
from tests.unit.backups.fakes import FakeBackupsUnitOfWork, FakeServerReadPort


def _registry_with_limits(
    backup: int = 1, websocket: int = 100, file_io: int = 10
) -> SemaphoreRegistry:
    reg = SemaphoreRegistry()
    reg.backup = ConcurrencySemaphore("backup", backup)
    reg.websocket = ConcurrencySemaphore("websocket", websocket)
    reg.file_io = ConcurrencySemaphore("file_io", file_io)
    return reg


@pytest.fixture
def _patch_semaphores():
    reg = _registry_with_limits(backup=1, file_io=10)
    with (
        patch("app.core.concurrency.semaphores", reg),
        patch("app.core.concurrency.get_semaphores", return_value=reg),
    ):
        yield reg


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort()


@pytest.fixture
def uow() -> FakeBackupsUnitOfWork:
    return FakeBackupsUnitOfWork()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_backup_semaphore_limits_concurrency(
    _patch_semaphores, uow, server_read, tmp_path
):
    """With limit=1 the second create_backup must wait until the first
    finishes."""
    reg = _patch_semaphores
    svc = BackupService(
        uow=uow,
        server_read=server_read,
        backups_directory=tmp_path / "backups",
    )

    started = asyncio.Event()
    proceed = asyncio.Event()

    original_inner = svc._create_backup_inner

    async def slow_inner(*args, **kwargs):
        started.set()
        await proceed.wait()
        return await original_inner(*args, **kwargs)

    svc._create_backup_inner = slow_inner

    task1 = asyncio.create_task(
        svc.create_backup(1, "first", backup_type=BackupType.manual)
    )
    await started.wait()
    assert reg.backup.in_use == 1

    second_started = asyncio.Event()

    async def second_slow_inner(*args, **kwargs):
        second_started.set()
        return await original_inner(*args, **kwargs)

    svc._create_backup_inner = second_slow_inner

    task2 = asyncio.create_task(
        svc.create_backup(1, "second", backup_type=BackupType.manual)
    )
    await asyncio.sleep(0.05)
    assert not second_started.is_set()

    proceed.set()
    # Let both tasks complete (they will both fail because server_read
    # has no servers, but we are testing semaphore behaviour)
    results = await asyncio.gather(task1, task2, return_exceptions=True)
    assert reg.backup.in_use == 0
    # Both should raise (no server configured in FakeServerReadPort)
    assert all(isinstance(r, Exception) for r in results)


@pytest.mark.asyncio
async def test_backup_semaphore_released_on_failure(
    _patch_semaphores, uow, server_read, tmp_path
):
    reg = _patch_semaphores
    svc = BackupService(
        uow=uow,
        server_read=server_read,
        backups_directory=tmp_path / "backups",
    )

    with pytest.raises(Exception):
        await svc.create_backup(999, "fail", backup_type=BackupType.manual)

    assert reg.backup.in_use == 0
