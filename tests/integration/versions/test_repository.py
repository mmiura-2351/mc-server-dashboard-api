"""Integration tests for `SqlAlchemyVersionRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not** commit
on its own (the UoW owns transactions in production), so each write-path
test calls `db.commit()` explicitly after staging changes.
"""

from datetime import datetime, timedelta

import pytest

from app.core.datetime_utils import utcnow
from app.servers.models import ServerType
from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.domain.entities import (
    CreateUpdateLogCommand,
    CreateVersionCommand,
    UpdateVersionCommand,
)
from app.versions.models import MinecraftVersion, VersionUpdateLog


class TestVersionRepository:
    @pytest.fixture
    def repository(self, db):
        return SqlAlchemyVersionRepository(db)

    @pytest.fixture
    def sample_versions(self, db):
        versions = [
            MinecraftVersion(
                server_type=ServerType.vanilla.value,
                version="1.21.6",
                download_url="https://example.com/vanilla-1.21.6.jar",
                is_active=True,
                is_stable=True,
            ),
            MinecraftVersion(
                server_type=ServerType.vanilla.value,
                version="1.21.5",
                download_url="https://example.com/vanilla-1.21.5.jar",
                is_active=True,
                is_stable=True,
            ),
            MinecraftVersion(
                server_type=ServerType.paper.value,
                version="1.21.6",
                download_url="https://example.com/paper-1.21.6.jar",
                is_active=True,
                is_stable=True,
                build_number=123,
            ),
            MinecraftVersion(
                server_type=ServerType.paper.value,
                version="1.21.5",
                download_url="https://example.com/paper-1.21.5.jar",
                is_active=False,
                is_stable=True,
                build_number=100,
            ),
        ]
        db.add_all(versions)
        db.commit()
        return versions

    # ----- Reads -----

    @pytest.mark.asyncio
    async def test_get_all_active_versions(self, repository, sample_versions):
        versions = await repository.get_all_active_versions()
        assert len(versions) == 3
        for v in versions:
            assert v.is_active is True
        server_types = [v.server_type for v in versions]
        assert server_types == [ServerType.paper, ServerType.vanilla, ServerType.vanilla]

    @pytest.mark.asyncio
    async def test_get_versions_by_type(self, repository, sample_versions):
        vanilla = await repository.get_versions_by_type(ServerType.vanilla)
        paper = await repository.get_versions_by_type(ServerType.paper)

        assert len(vanilla) == 2
        assert all(v.server_type == ServerType.vanilla for v in vanilla)
        assert all(v.is_active for v in vanilla)

        assert len(paper) == 1
        assert paper[0].server_type == ServerType.paper
        assert paper[0].version == "1.21.6"
        assert paper[0].is_active is True

    @pytest.mark.asyncio
    async def test_get_version_by_type_and_version(self, repository, sample_versions):
        version = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.6"
        )
        assert version is not None
        assert version.server_type == ServerType.vanilla
        assert version.version == "1.21.6"

        missing = await repository.get_version_by_type_and_version(
            ServerType.forge, "1.21.6"
        )
        assert missing is None

    # ----- Writes (commit explicitly to exercise persistence) -----

    @pytest.mark.asyncio
    async def test_create_version(self, repository, db):
        command = CreateVersionCommand(
            server_type=ServerType.forge,
            version="1.21.6",
            download_url="https://example.com/forge-1.21.6.jar",
            release_date=datetime(2025, 6, 17),
            is_stable=True,
            build_number=456,
        )
        created = await repository.create_version(command)
        db.commit()

        assert created.id is not None
        assert created.server_type == ServerType.forge
        assert created.version == "1.21.6"
        assert created.download_url == "https://example.com/forge-1.21.6.jar"
        assert created.build_number == 456
        assert created.is_active is True

    @pytest.mark.asyncio
    async def test_upsert_version_new(self, repository, db):
        command = CreateVersionCommand(
            server_type=ServerType.forge,
            version="1.21.6",
            download_url="https://example.com/forge-1.21.6.jar",
            is_stable=True,
        )
        upserted = await repository.upsert_version(command)
        db.commit()

        assert upserted.id is not None
        assert upserted.server_type == ServerType.forge
        assert upserted.version == "1.21.6"

    @pytest.mark.asyncio
    async def test_upsert_version_existing(self, repository, sample_versions, db):
        new_url = "https://example.com/updated-vanilla-1.21.6.jar"
        command = CreateVersionCommand(
            server_type=ServerType.vanilla,
            version="1.21.6",
            download_url=new_url,
            is_stable=False,
        )
        upserted = await repository.upsert_version(command)
        db.commit()

        assert upserted.download_url == new_url
        assert upserted.is_stable is False
        assert upserted.is_active is True

    @pytest.mark.asyncio
    async def test_update_version(self, repository, sample_versions, db):
        existing = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.6"
        )
        assert existing is not None
        command = UpdateVersionCommand(
            download_url="https://example.com/updated.jar",
            is_stable=False,
            is_active=False,
        )
        updated = await repository.update_version(existing.id, command)
        db.commit()

        assert updated is not None
        assert updated.download_url == "https://example.com/updated.jar"
        assert updated.is_stable is False
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_update_version_nonexistent(self, repository):
        command = UpdateVersionCommand(download_url="x")
        assert await repository.update_version(99999, command) is None

    @pytest.mark.asyncio
    async def test_deactivate_versions(self, repository, sample_versions, db):
        count = await repository.deactivate_versions(ServerType.vanilla, ["1.21.6"])
        db.commit()
        assert count == 1

        v5 = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.5"
        )
        assert v5 is not None and v5.is_active is False
        v6 = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.6"
        )
        assert v6 is not None and v6.is_active is True

    @pytest.mark.asyncio
    async def test_cleanup_old_versions(self, repository, db):
        old_date = utcnow() - timedelta(days=35)
        old_version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.20.0",
            download_url="https://example.com/old.jar",
            is_active=False,
            created_at=old_date,
            updated_at=old_date,
        )
        recent_version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.20.1",
            download_url="https://example.com/recent.jar",
            is_active=False,
        )
        db.add_all([old_version, recent_version])
        db.commit()

        count = await repository.cleanup_old_versions(days_old=30)
        db.commit()
        assert count == 1
        assert (
            db.query(MinecraftVersion).filter_by(version="1.20.0").first() is None
        )
        assert (
            db.query(MinecraftVersion).filter_by(version="1.20.1").first() is not None
        )

    # ----- Stats -----

    @pytest.mark.asyncio
    async def test_get_version_stats(self, repository, sample_versions):
        stats = await repository.get_version_stats()
        assert stats.by_server_type["vanilla"] == {"total": 2, "active": 2}
        assert stats.by_server_type["paper"] == {"total": 2, "active": 1}
        assert stats.total_versions == 4
        assert stats.active_versions == 3

    # ----- Update log -----

    @pytest.mark.asyncio
    async def test_create_update_log(self, repository, db):
        command = CreateUpdateLogCommand(
            update_type="manual",
            status="success",
            server_type="vanilla",
            executed_by_user_id=1,
        )
        created = await repository.create_update_log(command)
        db.commit()

        assert created.id is not None
        assert created.update_type == "manual"
        assert created.server_type == "vanilla"
        assert created.status == "success"
        assert created.executed_by_user_id == 1

    @pytest.mark.asyncio
    async def test_complete_update_log(self, repository, db):
        log = VersionUpdateLog(update_type="scheduled", status="running")
        db.add(log)
        db.commit()
        db.refresh(log)

        completed = await repository.complete_update_log(
            log.id,
            status="success",
            execution_time_ms=2500,
            error_message=None,
            versions_added=2,
            versions_updated=1,
            versions_removed=0,
            external_api_calls=3,
        )
        db.commit()
        assert completed is not None
        assert completed.status == "success"
        assert completed.execution_time_ms == 2500
        assert completed.completed_at is not None
        assert completed.versions_added == 2

    @pytest.mark.asyncio
    async def test_complete_update_log_nonexistent(self, repository):
        result = await repository.complete_update_log(99999, "success")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_update_log(self, repository, db):
        old_log = VersionUpdateLog(
            update_type="scheduled",
            status="success",
            started_at=utcnow() - timedelta(hours=2),
        )
        latest = VersionUpdateLog(
            update_type="manual",
            status="success",
            started_at=utcnow() - timedelta(minutes=30),
        )
        db.add_all([old_log, latest])
        db.commit()

        result = await repository.get_latest_update_log()
        assert result is not None
        assert result.update_type == "manual"

    @pytest.mark.asyncio
    async def test_get_update_logs_filter_and_limit(self, repository, db):
        manuals = [
            VersionUpdateLog(
                update_type="manual",
                status="success",
                started_at=utcnow() - timedelta(hours=i),
            )
            for i in range(3)
        ]
        scheduled = VersionUpdateLog(
            update_type="scheduled",
            status="success",
            started_at=utcnow() - timedelta(hours=1),
        )
        db.add_all(manuals + [scheduled])
        db.commit()

        manual_results = await repository.get_update_logs(limit=10, update_type="manual")
        assert len(manual_results) == 3
        assert all(log.update_type == "manual" for log in manual_results)

        all_results = await repository.get_update_logs(limit=10)
        assert len(all_results) == 4

        limited = await repository.get_update_logs(limit=3)
        assert len(limited) == 3
        ts = [log.started_at for log in limited]
        assert ts == sorted(ts, reverse=True)
