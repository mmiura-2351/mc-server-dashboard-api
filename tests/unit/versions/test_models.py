"""
Unit tests for version models
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.servers.models import ServerType
from app.versions.models import MinecraftVersion, VersionUpdateLog


class TestMinecraftVersion:
    """Test MinecraftVersion model"""

    def test_create_version(self, db):
        """Test creating a minecraft version"""
        version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.21.6",
            download_url="https://example.com/server.jar",
            release_date=datetime(2025, 6, 17),
            is_stable=True,
            build_number=None,
        )

        db.add(version)
        db.commit()
        db.refresh(version)

        assert version.id is not None
        assert version.server_type == "vanilla"
        assert version.version == "1.21.6"
        assert version.download_url == "https://example.com/server.jar"
        assert version.is_active is True
        assert version.is_stable is True
        assert version.created_at is not None
        assert version.updated_at is not None

    def test_version_tuple_property(self, db):
        """Test version_tuple property for sorting"""
        version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.21.6",
            download_url="https://example.com/server.jar",
        )

        assert version.version_tuple == (1, 21, 6)

        # Test with different version formats
        version.version = "1.20"
        assert version.version_tuple == (1, 20)

        version.version = "1.21.6-pre1"
        assert version.version_tuple == (1, 21, 6)

        version.version = "invalid"
        assert version.version_tuple == (0, 0, 0)

    def test_unique_constraint(self, db):
        """Test unique constraint on server_type + version"""
        version1 = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.21.6",
            download_url="https://example.com/server.jar",
        )

        version2 = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.21.6",
            download_url="https://example.com/server2.jar",
        )

        db.add(version1)
        db.commit()

        db.add(version2)

        with pytest.raises(IntegrityError):
            db.commit()

    def test_different_server_types_same_version(self, db):
        """Test same version can exist for different server types"""
        vanilla_version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.21.6",
            download_url="https://example.com/vanilla.jar",
        )

        paper_version = MinecraftVersion(
            server_type=ServerType.paper.value,
            version="1.21.6",
            download_url="https://example.com/paper.jar",
            build_number=123,
        )

        db.add_all([vanilla_version, paper_version])
        db.commit()

        # Should not raise IntegrityError
        assert vanilla_version.id != paper_version.id
        assert vanilla_version.build_number is None
        assert paper_version.build_number == 123

    def test_repr(self, db):
        """Test string representation"""
        version = MinecraftVersion(
            server_type=ServerType.paper.value,
            version="1.21.6",
            download_url="https://example.com/server.jar",
            is_active=True,
        )

        repr_str = repr(version)
        assert "MinecraftVersion(paper 1.21.6, active=True)" in repr_str


class TestVersionUpdateLog:
    """Test VersionUpdateLog model"""

    def test_create_update_log(self, db):
        """Test creating an update log"""
        log = VersionUpdateLog(
            update_type="manual",
            server_type="vanilla",
            versions_added=5,
            versions_updated=2,
            versions_removed=1,
            execution_time_ms=1500,
            external_api_calls=10,
            status="success",
            executed_by_user_id=1,
        )

        db.add(log)
        db.commit()
        db.refresh(log)

        assert log.id is not None
        assert log.update_type == "manual"
        assert log.server_type == "vanilla"
        assert log.versions_added == 5
        assert log.versions_updated == 2
        assert log.versions_removed == 1
        assert log.execution_time_ms == 1500
        assert log.external_api_calls == 10
        assert log.status == "success"
        assert log.executed_by_user_id == 1
        assert log.started_at is not None
        assert log.completed_at is None

    def test_duration_seconds_from_execution_time(self, db):
        """Test duration_seconds property from execution_time_ms"""
        log = VersionUpdateLog(
            update_type="scheduled", status="success", execution_time_ms=2500
        )

        assert log.duration_seconds == 2.5

    def test_duration_seconds_from_timestamps(self, db):
        """Test duration_seconds property from timestamps"""
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(seconds=3.5)

        log = VersionUpdateLog(
            update_type="scheduled",
            status="success",
            started_at=start_time,
            completed_at=end_time,
        )

        assert (
            abs(log.duration_seconds - 3.5) < 0.01
        )  # Allow small float precision errors

    def test_duration_seconds_none(self, db):
        """Test duration_seconds property when no data available"""
        log = VersionUpdateLog(update_type="scheduled", status="running")

        assert log.duration_seconds is None

    def test_total_changes_property(self, db):
        """Test total_changes property"""
        log = VersionUpdateLog(
            update_type="manual",
            status="success",
            versions_added=10,
            versions_updated=5,
            versions_removed=2,
        )

        assert log.total_changes == 17

    def test_total_changes_with_none_values(self, db):
        """Test total_changes property with None values"""
        log = VersionUpdateLog(update_type="manual", status="success")

        # Default values should be 0
        assert log.total_changes == 0

    def test_repr(self, db):
        """Test string representation"""
        start_time = datetime(2025, 6, 23, 12, 0, 0)
        log = VersionUpdateLog(
            update_type="scheduled", status="success", started_at=start_time
        )

        repr_str = repr(log)
        assert "VersionUpdateLog(scheduled, success," in repr_str
        assert "2025-06-23" in repr_str

    def test_nullable_server_type(self, db):
        """Test that server_type can be null (for all-types updates)"""
        log = VersionUpdateLog(
            update_type="startup",
            server_type=None,  # Update all server types
            status="success",
            versions_added=20,
        )

        db.add(log)
        db.commit()
        db.refresh(log)

        assert log.server_type is None
        assert log.versions_added == 20
