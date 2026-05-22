"""Integration tests for `SqlAlchemyBackupScheduleRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not** commit
on its own; tests call `db.commit()` after staging.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.backups.adapters.repository import SqlAlchemyBackupScheduleRepository
from app.backups.domain.entities import (
    AppendScheduleLogCommand,
    CreateBackupScheduleCommand,
    UpdateBackupScheduleCommand,
)
from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction
from app.servers.models import Server, ServerType


@pytest.fixture
def repository(db) -> SqlAlchemyBackupScheduleRepository:
    return SqlAlchemyBackupScheduleRepository(db)


def _seed_server(db, owner_id: int, *, name: str = "s", port: int = 25600) -> Server:
    row = Server(
        name=name,
        description=None,
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=port,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
        directory_path=f"/servers/{name}",
        is_deleted=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_schedule(
    db,
    server_id: int,
    *,
    interval_hours: int = 24,
    max_backups: int = 5,
    enabled: bool = True,
    only_when_running: bool = True,
    next_backup_at=None,
) -> BackupSchedule:
    row = BackupSchedule(
        server_id=server_id,
        interval_hours=interval_hours,
        max_backups=max_backups,
        enabled=enabled,
        only_when_running=only_when_running,
        next_backup_at=next_backup_at
        or (datetime.now(timezone.utc) + timedelta(hours=interval_hours)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestBackupScheduleReads:
    @pytest.mark.asyncio
    async def test_find_by_server(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, port=25601)
        _seed_schedule(db, server.id, interval_hours=6, max_backups=10)

        entity = await repository.find_by_server(server.id)
        assert entity is not None
        assert entity.interval_hours == 6
        assert entity.max_backups == 10
        assert entity.server_id == server.id

    @pytest.mark.asyncio
    async def test_find_by_server_missing(self, repository):
        assert await repository.find_by_server(99999) is None

    @pytest.mark.asyncio
    async def test_list_all(self, repository, db, admin_user):
        s1 = _seed_server(db, admin_user.id, name="ls1", port=25602)
        s2 = _seed_server(db, admin_user.id, name="ls2", port=25603)
        _seed_schedule(db, s1.id, enabled=True)
        _seed_schedule(db, s2.id, enabled=False)

        all_schedules = await repository.list(enabled_only=False)
        assert {e.server_id for e in all_schedules} >= {s1.id, s2.id}

        enabled = await repository.list(enabled_only=True)
        assert any(e.server_id == s1.id for e in enabled)
        assert not any(e.server_id == s2.id for e in enabled)

    @pytest.mark.asyncio
    async def test_list_due(self, repository, db, admin_user):
        s1 = _seed_server(db, admin_user.id, name="ld1", port=25604)
        s2 = _seed_server(db, admin_user.id, name="ld2", port=25605)
        s3 = _seed_server(db, admin_user.id, name="ld3", port=25606)
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)

        _seed_schedule(db, s1.id, next_backup_at=past, enabled=True)
        _seed_schedule(db, s2.id, next_backup_at=future, enabled=True)
        _seed_schedule(db, s3.id, next_backup_at=past, enabled=False)

        due = await repository.list_due(now)
        due_ids = {e.server_id for e in due}
        assert s1.id in due_ids
        assert s2.id not in due_ids  # future
        assert s3.id not in due_ids  # disabled

    @pytest.mark.asyncio
    async def test_list_logs_eager_loads_username(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, port=25607)
        log = BackupScheduleLog(
            server_id=server.id,
            action=ScheduleAction.created,
            reason="seed",
            executed_by_user_id=admin_user.id,
        )
        db.add(log)
        db.commit()

        logs = await repository.list_logs_for_server(server.id, page=1, size=10)
        assert len(logs) == 1
        assert logs[0].action == ScheduleAction.created
        # joinedload should populate username
        assert logs[0].executed_by_username == admin_user.username


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


class TestBackupScheduleWrites:
    @pytest.mark.asyncio
    async def test_add(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, port=25608)
        next_at = datetime.now(timezone.utc) + timedelta(hours=24)

        entity = await repository.add(
            CreateBackupScheduleCommand(
                server_id=server.id,
                interval_hours=24,
                max_backups=7,
                enabled=True,
                only_when_running=False,
                next_backup_at=next_at,
            )
        )
        db.commit()
        assert entity.id is not None
        assert entity.server_id == server.id
        assert entity.only_when_running is False

    @pytest.mark.asyncio
    async def test_update_sparse(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, port=25609)
        _seed_schedule(db, server.id, interval_hours=6, max_backups=5)

        updated = await repository.update(
            server.id,
            UpdateBackupScheduleCommand(max_backups=20),
        )
        db.commit()
        assert updated is not None
        assert updated.max_backups == 20
        assert updated.interval_hours == 6  # untouched

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self, repository):
        result = await repository.update(
            99999, UpdateBackupScheduleCommand(max_backups=10)
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_by_server(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, port=25610)
        _seed_schedule(db, server.id)
        assert await repository.delete_by_server(server.id) is True
        db.commit()
        assert await repository.find_by_server(server.id) is None

    @pytest.mark.asyncio
    async def test_delete_by_server_missing(self, repository):
        assert await repository.delete_by_server(99999) is False

    @pytest.mark.asyncio
    async def test_append_log(self, repository, db, admin_user):
        server = _seed_server(db, admin_user.id, port=25611)

        await repository.append_log(
            AppendScheduleLogCommand(
                server_id=server.id,
                action=ScheduleAction.updated,
                reason="ping",
                new_config={"interval_hours": 12},
                executed_by_user_id=admin_user.id,
            )
        )
        db.commit()

        logs = await repository.list_logs_for_server(server.id, page=1, size=10)
        assert len(logs) == 1
        assert logs[0].action == ScheduleAction.updated
        assert logs[0].reason == "ping"
        assert logs[0].new_config == {"interval_hours": 12}
        assert logs[0].executed_by_username == admin_user.username
