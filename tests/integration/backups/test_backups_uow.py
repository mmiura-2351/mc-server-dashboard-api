"""Integration tests for `SqlAlchemyBackupsUnitOfWork`.

Mirrors the templates/groups UoW tests: re-entry semantics, commit /
rollback, forgot-to-commit warning, and the disclosed atomicity
improvement for `create_schedule` (schedule + log committed together).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork
from app.backups.domain.entities import (
    AppendScheduleLogCommand,
    CreateBackupCommand,
    CreateBackupScheduleCommand,
)
from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction
from app.servers.models import Backup, BackupType, Server, ServerType


def _seed_server(db, owner_id: int, *, name: str = "u", port: int = 25700) -> Server:
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


class TestUoWConstruction:
    def test_requires_db_or_session_factory(self):
        with pytest.raises(ValueError):
            SqlAlchemyBackupsUnitOfWork()

    def test_from_session_factory(self):
        uow = SqlAlchemyBackupsUnitOfWork.from_session_factory(lambda: None)
        assert uow is not None


class TestUoWTransactions:
    @pytest.mark.asyncio
    async def test_commit_persists(self, db, admin_user):
        server = _seed_server(db, admin_user.id, name="c1", port=25701)
        uow = SqlAlchemyBackupsUnitOfWork(db=db)
        async with uow:
            await uow.backups.add(
                CreateBackupCommand(
                    server_id=server.id,
                    name="committed",
                    description=None,
                    backup_type=BackupType.manual,
                )
            )
            await uow.commit()

        row = db.query(Backup).filter(Backup.name == "committed").first()
        assert row is not None

    @pytest.mark.asyncio
    async def test_atomic_schedule_plus_log(self, db, admin_user):
        """Disclosed behaviour change: schedule + log are committed in
        one UoW transaction. If the log insert raises, the schedule
        rollback happens automatically through `__aexit__`.
        """
        server = _seed_server(db, admin_user.id, name="atom", port=25702)
        now = datetime.now(timezone.utc)
        uow = SqlAlchemyBackupsUnitOfWork(db=db)
        async with uow:
            await uow.schedules.add(
                CreateBackupScheduleCommand(
                    server_id=server.id,
                    interval_hours=12,
                    max_backups=5,
                    enabled=True,
                    only_when_running=True,
                    next_backup_at=now + timedelta(hours=12),
                )
            )
            await uow.schedules.append_log(
                AppendScheduleLogCommand(
                    server_id=server.id,
                    action=ScheduleAction.created,
                    reason="initial",
                    executed_by_user_id=admin_user.id,
                )
            )
            await uow.commit()

        sched = (
            db.query(BackupSchedule)
            .filter(BackupSchedule.server_id == server.id)
            .first()
        )
        log = (
            db.query(BackupScheduleLog)
            .filter(BackupScheduleLog.server_id == server.id)
            .first()
        )
        assert sched is not None
        assert log is not None
        assert log.action == ScheduleAction.created

    @pytest.mark.asyncio
    async def test_forgot_to_commit_warns_when_session_dirty(
        self, db, admin_user, caplog
    ):
        """Pending session-level changes without a commit must emit a
        warning. Stage a Backup through `db.add` (no flush) so
        `_has_pending_writes` sees it in `db.new`."""
        server = _seed_server(db, admin_user.id, name="fc", port=25703)
        uow = SqlAlchemyBackupsUnitOfWork(db=db)
        with caplog.at_level("WARNING"):
            async with uow as _bound:
                db.add(
                    Backup(
                        server_id=server.id,
                        name="dirty",
                        description=None,
                        file_path="",
                        file_size=0,
                        backup_type=BackupType.manual,
                    )
                )
                # Intentionally no flush, no commit

        assert any(
            "exited with pending writes" in rec.message for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_exception_calls_rollback(self, db, admin_user, caplog):
        """When the body raises, UoW propagates the exception after rollback."""
        server = _seed_server(db, admin_user.id, name="re", port=25704)
        uow = SqlAlchemyBackupsUnitOfWork(db=db)
        with pytest.raises(RuntimeError, match="boom"):
            async with uow:
                db.add(
                    Backup(
                        server_id=server.id,
                        name="exc",
                        description=None,
                        file_path="",
                        file_size=0,
                        backup_type=BackupType.manual,
                    )
                )
                raise RuntimeError("boom")
        # Pending write must be rolled back, regardless of any prior flush
        assert db.query(Backup).filter(Backup.name == "exc").first() is None

    @pytest.mark.asyncio
    async def test_reentry_share_session(self, db, admin_user):
        """Entering the same UoW twice keeps the same session in db= mode."""
        _seed_server(db, admin_user.id, name="re1", port=25705)
        uow = SqlAlchemyBackupsUnitOfWork(db=db)
        async with uow as a:
            id_a = id(a._db)
        async with uow as b:
            id_b = id(b._db)
        assert id_a == id_b
