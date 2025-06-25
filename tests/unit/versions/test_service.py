"""
Unit tests for VersionUpdateService
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.servers.models import ServerType
from app.services.version_manager import VersionInfo
from app.versions.models import MinecraftVersion, VersionUpdateLog
from app.versions.service import VersionUpdateService


class TestVersionUpdateService:
    """Test VersionUpdateService class"""

    @pytest.fixture
    def service(self, db):
        """Create service instance"""
        return VersionUpdateService(db)

    @pytest.fixture
    def mock_external_versions(self):
        """Mock external API version data"""
        return [
            VersionInfo(
                version="1.21.6",
                server_type=ServerType.vanilla,
                download_url="https://example.com/vanilla-1.21.6.jar",
                release_date=datetime(2025, 6, 17),
                is_stable=True,
            ),
            VersionInfo(
                version="1.21.5",
                server_type=ServerType.vanilla,
                download_url="https://example.com/vanilla-1.21.5.jar",
                release_date=datetime(2025, 6, 10),
                is_stable=True,
            ),
            VersionInfo(
                version="1.21.6",
                server_type=ServerType.paper,
                download_url="https://example.com/paper-1.21.6.jar",
                release_date=datetime(2025, 6, 17),
                is_stable=True,
                build_number=123,
            ),
        ]

    @pytest.fixture
    def existing_versions(self, db):
        """Create existing versions in database"""
        versions = [
            MinecraftVersion(
                server_type=ServerType.vanilla.value,
                version="1.21.5",
                download_url="https://example.com/old-vanilla-1.21.5.jar",  # Different URL
                is_active=True,
                is_stable=True,
            ),
            MinecraftVersion(
                server_type=ServerType.vanilla.value,
                version="1.21.4",
                download_url="https://example.com/vanilla-1.21.4.jar",
                is_active=True,
                is_stable=True,
            ),
        ]

        db.add_all(versions)
        db.commit()
        return versions

    @pytest.mark.asyncio
    async def test_update_versions_new_installation(
        self, service, mock_external_versions
    ):
        """Test updating versions on fresh installation (no existing versions)"""
        with patch.object(
            service, "_update_server_type_versions", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {
                "added": 2,
                "updated": 0,
                "removed": 0,
                "api_calls": 3,
            }

            result = await service.update_versions(
                server_types=[ServerType.vanilla], user_id=1
            )

            assert result.success is True
            assert result.versions_added == 2
            assert result.versions_updated == 0
            assert result.versions_removed == 0
            assert result.log_id is not None
            assert len(result.errors) == 0
            mock_update.assert_called_once_with(ServerType.vanilla, False)

    @pytest.mark.asyncio
    async def test_update_versions_with_existing_data(
        self, service, existing_versions, mock_external_versions
    ):
        """Test updating versions when database already has data"""
        with patch.object(
            service, "_update_server_type_versions", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {
                "added": 1,
                "updated": 1,
                "removed": 1,
                "api_calls": 4,
            }

            result = await service.update_versions(
                server_types=[ServerType.vanilla], force_refresh=True
            )

            assert result.success is True
            assert result.versions_added == 1
            assert result.versions_updated == 1
            assert result.versions_removed == 1

    @pytest.mark.asyncio
    async def test_update_versions_concurrent_prevention(self, service):
        """Test that concurrent updates are prevented"""
        # Set update as running
        service._update_running = True

        result = await service.update_versions([ServerType.vanilla])

        assert result.success is False
        assert "already in progress" in result.message
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_update_versions_all_types_default(self, service):
        """Test that all server types are updated when none specified"""
        with patch.object(
            service, "_update_server_type_versions", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {
                "added": 1,
                "updated": 0,
                "removed": 0,
                "api_calls": 2,
            }

            result = await service.update_versions()

            # Should be called for all ServerType enum values
            assert mock_update.call_count == len(ServerType)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_update_versions_partial_failure(self, service):
        """Test handling of partial failures during update"""

        def side_effect(server_type, force_refresh):
            if server_type == ServerType.vanilla:
                return {"added": 1, "updated": 0, "removed": 0, "api_calls": 2}
            else:
                raise Exception("API error")

        with patch.object(
            service,
            "_update_server_type_versions",
            new_callable=AsyncMock,
            side_effect=side_effect,
        ):
            result = await service.update_versions([ServerType.vanilla, ServerType.paper])

            assert result.success is True  # Partial success
            assert result.versions_added == 1
            assert len(result.errors) == 1
            assert "Failed to update paper" in result.errors[0]

    @pytest.mark.asyncio
    async def test_update_server_type_versions_new_versions(self, service):
        """Test updating a server type with new versions from API"""
        mock_versions = [
            VersionInfo(
                version="1.21.6",
                server_type=ServerType.vanilla,
                download_url="https://example.com/vanilla-1.21.6.jar",
                is_stable=True,
            )
        ]

        with patch("app.versions.service.minecraft_version_manager") as mock_manager:
            mock_manager.get_supported_versions = AsyncMock(return_value=mock_versions)

            result = await service._update_server_type_versions(ServerType.vanilla)

            assert result["added"] == 1
            assert result["updated"] == 0
            assert result["removed"] == 0
            assert result["api_calls"] == 2  # 1 version + 1 initial call

    @pytest.mark.asyncio
    async def test_update_server_type_versions_existing_unchanged(
        self, service, existing_versions
    ):
        """Test updating when versions exist and haven't changed"""
        # Mock returning the same version as exists in DB
        mock_versions = [
            VersionInfo(
                version="1.21.5",
                server_type=ServerType.vanilla,
                download_url="https://example.com/old-vanilla-1.21.5.jar",  # Same as in DB
                is_stable=True,
            )
        ]

        with patch("app.versions.service.minecraft_version_manager") as mock_manager:
            mock_manager.get_supported_versions = AsyncMock(return_value=mock_versions)

            result = await service._update_server_type_versions(ServerType.vanilla)

            assert result["added"] == 0
            assert result["updated"] == 0  # No changes needed
            assert result["removed"] == 1  # 1.21.4 should be deactivated

    @pytest.mark.asyncio
    async def test_update_server_type_versions_url_changed(
        self, service, existing_versions
    ):
        """Test updating when download URL has changed"""
        # Mock returning version with different URL
        mock_versions = [
            VersionInfo(
                version="1.21.5",
                server_type=ServerType.vanilla,
                download_url="https://example.com/new-vanilla-1.21.5.jar",  # Different URL
                is_stable=True,
            )
        ]

        with patch("app.versions.service.minecraft_version_manager") as mock_manager:
            mock_manager.get_supported_versions = AsyncMock(return_value=mock_versions)

            result = await service._update_server_type_versions(ServerType.vanilla)

            assert result["added"] == 0
            assert result["updated"] == 1  # URL changed
            assert result["removed"] == 1  # 1.21.4 deactivated

    @pytest.mark.asyncio
    async def test_update_server_type_versions_api_failure(self, service):
        """Test handling of external API failure"""
        with patch("app.versions.service.minecraft_version_manager") as mock_manager:
            mock_manager.get_supported_versions = AsyncMock(
                side_effect=Exception("API down")
            )

            with pytest.raises(Exception, match="API down"):
                await service._update_server_type_versions(ServerType.vanilla)

    @pytest.mark.asyncio
    async def test_get_update_status(self, service, db):
        """Test getting update status"""
        # Create some test data
        log = VersionUpdateLog(update_type="manual", status="success", versions_added=5)
        db.add(log)
        db.commit()

        status = await service.get_update_status()

        assert status.last_update is not None
        assert isinstance(status.total_versions, int)
        assert isinstance(status.versions_by_type, dict)
        assert status.is_update_running is False

    @pytest.mark.asyncio
    async def test_cleanup_old_versions(self, service, db):
        """Test cleaning up old versions"""
        # Create old inactive version
        old_date = datetime.utcnow() - timedelta(days=35)
        old_version = MinecraftVersion(
            server_type=ServerType.vanilla.value,
            version="1.20.0",
            download_url="https://example.com/old.jar",
            is_active=False,
            created_at=old_date,
            updated_at=old_date,
        )
        db.add(old_version)
        db.commit()

        removed_count = await service.cleanup_old_versions(days_old=30)

        assert removed_count == 1

    @pytest.mark.asyncio
    async def test_get_supported_versions_fast_lookup(self, service, existing_versions):
        """Test fast database lookup for supported versions"""
        versions = await service.get_supported_versions(ServerType.vanilla)

        assert len(versions) == 2  # From existing_versions fixture
        assert all(v.server_type == "vanilla" for v in versions)
        assert all(v.is_active for v in versions)

    @pytest.mark.asyncio
    async def test_get_all_supported_versions_fast_lookup(
        self, service, existing_versions
    ):
        """Test fast database lookup for all supported versions"""
        versions = await service.get_all_supported_versions()

        assert len(versions) >= 2  # At least from existing_versions fixture
        assert all(v.is_active for v in versions)

    @pytest.mark.asyncio
    async def test_get_download_url_fast_lookup(self, service, existing_versions):
        """Test fast database lookup for download URL"""
        url = await service.get_download_url(ServerType.vanilla, "1.21.5")

        assert url == "https://example.com/old-vanilla-1.21.5.jar"

    @pytest.mark.asyncio
    async def test_get_download_url_not_found(self, service):
        """Test download URL lookup for non-existent version"""
        url = await service.get_download_url(ServerType.vanilla, "999.999.999")

        assert url is None

    def test_is_version_supported_delegation(self, service):
        """Test that version support check delegates to original manager"""
        with patch("app.versions.service.minecraft_version_manager") as mock_manager:
            mock_manager.is_version_supported.return_value = True

            result = service.is_version_supported(ServerType.vanilla, "1.21.6")

            assert result is True
            mock_manager.is_version_supported.assert_called_once_with(
                ServerType.vanilla, "1.21.6"
            )

    def test_update_running_property(self, service):
        """Test update running property"""
        assert service.is_update_running is False

        service._update_running = True
        assert service.is_update_running is True

    def test_last_update_time_property(self, service):
        """Test last update time property"""
        assert service.last_update_time is None

        test_time = datetime.utcnow()
        service._last_update_time = test_time
        assert service.last_update_time == test_time

    @pytest.mark.asyncio
    async def test_update_versions_error_handling_and_logging(self, service):
        """Test comprehensive error handling and logging in update_versions"""
        with patch.object(
            service.repository, "create_update_log", new_callable=AsyncMock
        ) as mock_create_log:
            # Mock log creation
            mock_log = Mock()
            mock_log.id = 123
            mock_create_log.return_value = mock_log

            # Mock the complete_update_log method
            with patch.object(
                service.repository, "complete_update_log", new_callable=AsyncMock
            ) as mock_complete_log:
                # Mock database query operations to avoid AttributeError
                with (
                    patch.object(service.db, "query"),
                    patch.object(service.db, "commit"),
                ):
                    # Mock update method to raise exception
                    with patch.object(
                        service,
                        "_update_server_type_versions",
                        new_callable=AsyncMock,
                        side_effect=Exception("Critical error"),
                    ):
                        result = await service.update_versions([ServerType.vanilla])

                        assert (
                            result.success is True
                        )  # Partial success due to error handling
                        assert "Version update completed" in result.message
                        assert result.log_id == 123
                        assert len(result.errors) == 1
                        assert (
                            "Failed to update vanilla: Critical error" in result.errors[0]
                        )

                        # Verify log was created and completed with error
                        mock_create_log.assert_called_once()
                        mock_complete_log.assert_called_once()

    def test_version_update_service_instantiation(self):
        """Test basic service instantiation"""
        from app.versions.service import VersionUpdateService

        # Mock database session
        mock_db = Mock()
        service = VersionUpdateService(mock_db)

        assert isinstance(service, VersionUpdateService)
        assert service.db == mock_db
        assert not service.is_update_running
        assert service.last_update_time is None
