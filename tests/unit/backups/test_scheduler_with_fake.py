"""Unit tests for `BackupSchedulerService` using in-memory fakes.

Covers schedule CRUD, cache invalidation (D-8), `list_due` with
deterministic clock injection (D-12), and the atomic
schedule+log behaviour (D-5.4 disclosed fix).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.backups.application.scheduler import BackupSchedulerService
from app.backups.domain.exceptions import (
    BackupScheduleAlreadyExistsError,
    BackupScheduleNotFoundError,
)
from app.backups.models import ScheduleAction
from tests.unit.backups.fakes import (
    FakeBackupsUnitOfWork,
    FakeServerReadPort,
    make_schedule_entity,
)

FROZEN_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_scheduler(
    uow: FakeBackupsUnitOfWork,
    server_read: FakeServerReadPort,
    *,
    clock=lambda: FROZEN_NOW,
) -> BackupSchedulerService:
    return BackupSchedulerService(
        uow_factory=lambda: uow,
        server_read_factory=lambda: server_read,
        clock=clock,
    )


@pytest.fixture
def uow() -> FakeBackupsUnitOfWork:
    return FakeBackupsUnitOfWork()


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort()


# ---------------------------------------------------------------------------
# create_schedule
# ---------------------------------------------------------------------------


class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_creates_and_logs(self, uow, server_read):
        server_read.seed(id=1, owner_id=2)
        scheduler = _make_scheduler(uow, server_read)
        entity = await scheduler.create_schedule(
            server_id=1, interval_hours=6, max_backups=10, executed_by_user_id=2
        )
        assert entity.server_id == 1
        assert entity.next_backup_at == FROZEN_NOW + timedelta(hours=6)
        # log appended
        logs = await uow.schedules.list_logs_for_server(1, 1, 10)
        assert len(logs) == 1
        assert logs[0].action == ScheduleAction.created
        # commit happened
        assert uow.committed == 1

    @pytest.mark.asyncio
    async def test_duplicate_raises(self, uow, server_read):
        server_read.seed(id=1)
        uow.schedules.seed_schedule(make_schedule_entity(id=1, server_id=1))
        scheduler = _make_scheduler(uow, server_read)
        with pytest.raises(BackupScheduleAlreadyExistsError):
            await scheduler.create_schedule(
                server_id=1, interval_hours=6, max_backups=5
            )

    @pytest.mark.asyncio
    async def test_unknown_server_raises(self, uow, server_read):
        scheduler = _make_scheduler(uow, server_read)
        with pytest.raises(BackupScheduleNotFoundError):
            await scheduler.create_schedule(
                server_id=99, interval_hours=6, max_backups=5
            )

    @pytest.mark.asyncio
    async def test_log_failure_rolls_back_atomically(self, uow, server_read):
        """D-5.4: schedule + log are committed in one UoW. A log
        failure means commit was not reached, so the rollback path
        runs (FakeBackupsUnitOfWork tracks rolled_back)."""
        server_read.seed(id=1)
        uow.schedules.fail_next_log(RuntimeError("forced log failure"))
        scheduler = _make_scheduler(uow, server_read)

        with pytest.raises(RuntimeError, match="forced log failure"):
            await scheduler.create_schedule(
                server_id=1, interval_hours=6, max_backups=5
            )

        # No commit fired (atomic-or-nothing)
        assert uow.committed == 0
        assert uow.rolled_back == 1


# ---------------------------------------------------------------------------
# update / delete + cache invalidation
# ---------------------------------------------------------------------------


class TestUpdateAndCache:
    @pytest.mark.asyncio
    async def test_update_writes_log_and_invalidates_cache(self, uow, server_read):
        uow.schedules.seed_schedule(
            make_schedule_entity(
                id=1, server_id=1, interval_hours=6, max_backups=5
            )
        )
        scheduler = _make_scheduler(uow, server_read)

        # Prime cache with stale view
        await scheduler.get_schedule(1)
        cached = scheduler._schedule_cache[1]
        assert cached.max_backups == 5

        await scheduler.update_schedule(server_id=1, max_backups=20)
        # Cache must reflect new state
        assert scheduler._schedule_cache[1].max_backups == 20
        logs = await uow.schedules.list_logs_for_server(1, 1, 10)
        assert any(log.action == ScheduleAction.updated for log in logs)

    @pytest.mark.asyncio
    async def test_update_unknown_raises(self, uow, server_read):
        scheduler = _make_scheduler(uow, server_read)
        with pytest.raises(BackupScheduleNotFoundError):
            await scheduler.update_schedule(server_id=99, max_backups=10)

    @pytest.mark.asyncio
    async def test_delete_logs_and_drops_cache(self, uow, server_read):
        uow.schedules.seed_schedule(make_schedule_entity(id=1, server_id=1))
        scheduler = _make_scheduler(uow, server_read)
        # Prime cache
        await scheduler.get_schedule(1)
        assert 1 in scheduler._schedule_cache

        deleted = await scheduler.delete_schedule(1, executed_by_user_id=42)
        assert deleted is True
        assert 1 not in scheduler._schedule_cache
        logs = await uow.schedules.list_logs_for_server(1, 1, 10)
        assert any(log.action == ScheduleAction.deleted for log in logs)

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, uow, server_read):
        scheduler = _make_scheduler(uow, server_read)
        assert await scheduler.delete_schedule(99) is False


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    @pytest.mark.asyncio
    async def test_get_cache_hit(self, uow, server_read):
        uow.schedules.seed_schedule(make_schedule_entity(id=1, server_id=1))
        scheduler = _make_scheduler(uow, server_read)
        first = await scheduler.get_schedule(1)
        # remove from underlying store; cached value should still come back
        del uow.schedules._schedules[1]
        again = await scheduler.get_schedule(1)
        assert first == again

    @pytest.mark.asyncio
    async def test_list_due_uses_injected_clock(self, uow, server_read):
        past = FROZEN_NOW - timedelta(hours=1)
        future = FROZEN_NOW + timedelta(hours=1)
        uow.schedules.seed_schedule(
            make_schedule_entity(
                id=1, server_id=1, enabled=True, next_backup_at=past
            )
        )
        uow.schedules.seed_schedule(
            make_schedule_entity(
                id=2, server_id=2, enabled=True, next_backup_at=future
            )
        )
        scheduler = _make_scheduler(uow, server_read)
        due = await scheduler.get_due_schedules()
        assert {s.server_id for s in due} == {1}

    @pytest.mark.asyncio
    async def test_list_schedules_warms_cache(self, uow, server_read):
        uow.schedules.seed_schedule(make_schedule_entity(id=1, server_id=10))
        scheduler = _make_scheduler(uow, server_read)
        await scheduler.list_schedules()
        assert 10 in scheduler._schedule_cache


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_initial_state(self, uow, server_read):
        scheduler = _make_scheduler(uow, server_read)
        assert scheduler.is_running is False
        assert scheduler.cache_size == 0

    def test_clear_cache(self, uow, server_read):
        scheduler = _make_scheduler(uow, server_read)
        scheduler._schedule_cache[5] = make_schedule_entity(id=5, server_id=5)
        scheduler.clear_cache()
        assert scheduler.cache_size == 0
