"""
Unit tests for version repository
"""

from datetime import datetime, timedelta

import pytest

from app.servers.models import ServerType
from app.versions.models import MinecraftVersion, VersionUpdateLog
from app.versions.repository import VersionRepository
from app.versions.schemas import (
    MinecraftVersionCreate,
    MinecraftVersionUpdate,
    VersionUpdateLogCreate,
)


class TestVersionRepository:
    """Test VersionRepository class"""

    @pytest.fixture
    def repository(self, db):
        """Create repository instance"""
        return VersionRepository(db)

    @pytest.fixture
    def sample_versions(self, db):
        """Create sample versions for testing"""
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
                is_active=False,  # Inactive version
                is_stable=True,
                build_number=100,
            ),
        ]

        db.add_all(versions)
        db.commit()
        return versions

    @pytest.mark.asyncio
    async def test_get_all_active_versions(self, repository, sample_versions):
        """Test getting all active versions"""
        versions = await repository.get_all_active_versions()

        # Should return 3 active versions (excluding the inactive paper 1.21.5)
        assert len(versions) == 3

        # All returned versions should be active
        for version in versions:
            assert version.is_active is True

        # Should be ordered by server_type, then version desc
        server_types = [v.server_type for v in versions]
        assert server_types == ["paper", "vanilla", "vanilla"]

    @pytest.mark.asyncio
    async def test_get_versions_by_type(self, repository, sample_versions):
        """Test getting versions by server type"""
        vanilla_versions = await repository.get_versions_by_type(ServerType.vanilla)
        paper_versions = await repository.get_versions_by_type(ServerType.paper)

        # Vanilla should have 2 active versions
        assert len(vanilla_versions) == 2
        assert all(v.server_type == "vanilla" for v in vanilla_versions)
        assert all(v.is_active for v in vanilla_versions)

        # Paper should have 1 active version (1.21.5 is inactive)
        assert len(paper_versions) == 1
        assert paper_versions[0].server_type == "paper"
        assert paper_versions[0].version == "1.21.6"
        assert paper_versions[0].is_active is True

    @pytest.mark.asyncio
    async def test_get_version_by_type_and_version(self, repository, sample_versions):
        """Test getting specific version by type and version"""
        version = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.6"
        )

        assert version is not None
        assert version.server_type == "vanilla"
        assert version.version == "1.21.6"

        # Test non-existent version
        version = await repository.get_version_by_type_and_version(
            ServerType.forge, "1.21.6"
        )
        assert version is None

    @pytest.mark.asyncio
    async def test_create_version(self, repository):
        """Test creating a new version"""
        version_data = MinecraftVersionCreate(
            server_type=ServerType.forge,
            version="1.21.6",
            download_url="https://example.com/forge-1.21.6.jar",
            release_date=datetime(2025, 6, 17),
            is_stable=True,
            build_number=456,
        )

        created_version = await repository.create_version(version_data)

        assert created_version.id is not None
        assert created_version.server_type == "forge"
        assert created_version.version == "1.21.6"
        assert created_version.download_url == "https://example.com/forge-1.21.6.jar"
        assert created_version.build_number == 456
        assert created_version.is_active is True

    @pytest.mark.asyncio
    async def test_upsert_version_new(self, repository):
        """Test upserting a new version"""
        version_data = MinecraftVersionCreate(
            server_type=ServerType.forge,
            version="1.21.6",
            download_url="https://example.com/forge-1.21.6.jar",
            is_stable=True,
        )

        upserted_version = await repository.upsert_version(version_data)

        assert upserted_version.id is not None
        assert upserted_version.server_type == "forge"
        assert upserted_version.version == "1.21.6"

    @pytest.mark.asyncio
    async def test_upsert_version_existing(self, repository, sample_versions):
        """Test upserting an existing version"""
        new_url = "https://example.com/updated-vanilla-1.21.6.jar"
        version_data = MinecraftVersionCreate(
            server_type=ServerType.vanilla,
            version="1.21.6",
            download_url=new_url,
            is_stable=False,  # Changed from True
        )

        upserted_version = await repository.upsert_version(version_data)

        # Should update the existing version
        assert upserted_version.download_url == new_url
        assert upserted_version.is_stable is False
        assert upserted_version.is_active is True  # Should be reactivated

    @pytest.mark.asyncio
    async def test_update_version(self, repository, sample_versions):
        """Test updating an existing version"""
        # Get an existing version
        existing = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.6"
        )

        update_data = MinecraftVersionUpdate(
            download_url="https://example.com/updated.jar",
            is_stable=False,
            is_active=False,
        )

        updated_version = await repository.update_version(existing.id, update_data)

        assert updated_version is not None
        assert updated_version.download_url == "https://example.com/updated.jar"
        assert updated_version.is_stable is False
        assert updated_version.is_active is False

    @pytest.mark.asyncio
    async def test_update_version_nonexistent(self, repository):
        """Test updating a non-existent version"""
        update_data = MinecraftVersionUpdate(
            download_url="https://example.com/updated.jar"
        )

        result = await repository.update_version(99999, update_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate_versions(self, repository, sample_versions):
        """Test deactivating versions not in keep list"""
        # Keep only 1.21.6, should deactivate 1.21.5
        count = await repository.deactivate_versions(ServerType.vanilla, ["1.21.6"])

        assert count == 1  # One version deactivated

        # Verify 1.21.5 is now inactive
        version_1_21_5 = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.5"
        )
        assert version_1_21_5.is_active is False

        # Verify 1.21.6 is still active
        version_1_21_6 = await repository.get_version_by_type_and_version(
            ServerType.vanilla, "1.21.6"
        )
        assert version_1_21_6.is_active is True

    @pytest.mark.asyncio
    async def test_cleanup_old_versions(self, repository, db):
        """Test cleaning up old inactive versions"""
        # Create an old inactive version
        old_date = datetime.utcnow() - timedelta(days=35)
        old_version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.20.0",
            download_url="https://example.com/old.jar",
            is_active=False,
            created_at=old_date,
            updated_at=old_date,
        )

        # Create a recent inactive version
        recent_version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.20.1",
            download_url="https://example.com/recent.jar",
            is_active=False,
        )

        db.add_all([old_version, recent_version])
        db.commit()

        # Cleanup versions older than 30 days
        count = await repository.cleanup_old_versions(days_old=30)

        assert count == 1  # Only the old version should be deleted

        # Verify old version is deleted
        remaining = db.query(MinecraftVersion).filter_by(version="1.20.0").first()
        assert remaining is None

        # Verify recent version still exists
        remaining = db.query(MinecraftVersion).filter_by(version="1.20.1").first()
        assert remaining is not None

    @pytest.mark.asyncio
    async def test_get_version_stats(self, repository, sample_versions):
        """Test getting version statistics"""
        stats = await repository.get_version_stats()

        assert "vanilla" in stats
        assert "paper" in stats
        assert "_total" in stats

        # Vanilla: 2 total, 2 active
        assert stats["vanilla"]["total"] == 2
        assert stats["vanilla"]["active"] == 2

        # Paper: 2 total, 1 active (one is inactive)
        assert stats["paper"]["total"] == 2
        assert stats["paper"]["active"] == 1

        # Total: 4 total, 3 active
        assert stats["_total"]["total"] == 4
        assert stats["_total"]["active"] == 3

    @pytest.mark.asyncio
    async def test_create_update_log(self, repository):
        """Test creating an update log"""
        log_data = VersionUpdateLogCreate(
            update_type="manual",
            server_type="vanilla",
            versions_added=5,
            status="success",
            executed_by_user_id=1,
        )

        created_log = await repository.create_update_log(log_data)

        assert created_log.id is not None
        assert created_log.update_type == "manual"
        assert created_log.server_type == "vanilla"
        assert created_log.versions_added == 5
        assert created_log.status == "success"
        assert created_log.executed_by_user_id == 1

    @pytest.mark.asyncio
    async def test_complete_update_log(self, repository, db):
        """Test completing an update log"""
        # Create initial log
        log = VersionUpdateLog(update_type="scheduled", status="running")
        db.add(log)
        db.commit()
        db.refresh(log)

        # Complete the log
        completed_log = await repository.complete_update_log(
            log.id, status="success", execution_time_ms=2500, error_message=None
        )

        assert completed_log is not None
        assert completed_log.status == "success"
        assert completed_log.execution_time_ms == 2500
        assert completed_log.completed_at is not None

    @pytest.mark.asyncio
    async def test_complete_update_log_nonexistent(self, repository):
        """Test completing a non-existent update log"""
        result = await repository.complete_update_log(99999, "success")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_update_log(self, repository, db):
        """Test getting the latest update log"""
        # Create multiple logs with different timestamps
        old_log = VersionUpdateLog(
            update_type="scheduled",
            status="success",
            started_at=datetime.utcnow() - timedelta(hours=2),
        )

        latest_log = VersionUpdateLog(
            update_type="manual",
            status="success",
            started_at=datetime.utcnow() - timedelta(minutes=30),
        )

        db.add_all([old_log, latest_log])
        db.commit()

        result = await repository.get_latest_update_log()

        assert result is not None
        assert result.update_type == "manual"  # Should be the latest one

    @pytest.mark.asyncio
    async def test_get_update_logs_with_filter(self, repository, db):
        """Test getting update logs with filtering"""
        # Create logs of different types
        manual_logs = [
            VersionUpdateLog(
                update_type="manual",
                status="success",
                started_at=datetime.utcnow() - timedelta(hours=i),
            )
            for i in range(3)
        ]

        scheduled_log = VersionUpdateLog(
            update_type="scheduled",
            status="success",
            started_at=datetime.utcnow() - timedelta(hours=1),
        )

        db.add_all(manual_logs + [scheduled_log])
        db.commit()

        # Get manual logs only
        manual_results = await repository.get_update_logs(limit=10, update_type="manual")

        assert len(manual_results) == 3
        assert all(log.update_type == "manual" for log in manual_results)

        # Get all logs
        all_results = await repository.get_update_logs(limit=10)

        assert len(all_results) == 4  # 3 manual + 1 scheduled

    @pytest.mark.asyncio
    async def test_get_update_logs_limit(self, repository, db):
        """Test update logs limit functionality"""
        # Create more logs than the limit
        logs = [
            VersionUpdateLog(
                update_type="scheduled",
                status="success",
                started_at=datetime.utcnow() - timedelta(hours=i),
            )
            for i in range(5)
        ]

        db.add_all(logs)
        db.commit()

        # Request only 3 logs
        results = await repository.get_update_logs(limit=3)

        assert len(results) == 3

        # Should be ordered by most recent first
        timestamps = [log.started_at for log in results]
        assert timestamps == sorted(timestamps, reverse=True)
