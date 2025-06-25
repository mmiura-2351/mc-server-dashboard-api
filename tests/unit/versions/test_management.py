"""
Unit tests for VersionManagementService
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.versions.management import VersionManagementService
from app.versions.schemas import VersionUpdateResult


class TestVersionManagementService:
    """Test VersionManagementService class"""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        return Mock()

    @pytest.fixture
    def management_service(self, mock_db_session):
        """Create management service with mock session"""
        return VersionManagementService(mock_db_session)

    @pytest.fixture
    def mock_update_result(self):
        """Mock successful update result"""
        return VersionUpdateResult(
            success=True,
            message="Update completed successfully",
            versions_added=10,
            versions_updated=5,
            versions_removed=2,
            execution_time_ms=2500,
            errors=[]
        )

    @pytest.fixture
    def mock_failed_update_result(self):
        """Mock failed update result"""
        return VersionUpdateResult(
            success=False,
            message="External API error",
            versions_added=0,
            versions_updated=0,
            versions_removed=0,
            execution_time_ms=1000,
            errors=["Failed to connect to Mojang API"]
        )

    # ===================
    # Manual update tests
    # ===================

    @pytest.mark.asyncio
    async def test_trigger_manual_update_success(self, management_service, mock_update_result):
        """Test successful manual update trigger"""
        with patch('app.versions.management.VersionUpdateService') as mock_service_class:
            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_update_result)

            result = await management_service.trigger_manual_update(
                server_types=None,
                force_refresh=True,
                user_id=123
            )

            assert result.success
            assert result.versions_added == 10
            assert result.versions_updated == 5
            assert result.versions_removed == 2

            # Verify service was called correctly
            mock_service.update_versions.assert_called_once_with(
                server_types=None,
                force_refresh=True,
                user_id=123
            )

    @pytest.mark.asyncio
    async def test_trigger_manual_update_failure(self, management_service, mock_failed_update_result):
        """Test failed manual update trigger"""
        with patch('app.versions.management.VersionUpdateService') as mock_service_class:
            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_failed_update_result)

            result = await management_service.trigger_manual_update()

            assert not result.success
            assert result.message == "External API error"
            assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_trigger_manual_update_with_server_types(self, management_service, mock_update_result):
        """Test manual update with specific server types"""
        from app.servers.models import ServerType

        with patch('app.versions.management.VersionUpdateService') as mock_service_class:
            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_update_result)

            server_types = [ServerType.vanilla, ServerType.paper]
            result = await management_service.trigger_manual_update(
                server_types=server_types,
                force_refresh=False,
                user_id=456
            )

            assert result.success

            # Verify correct parameters were passed
            mock_service.update_versions.assert_called_once_with(
                server_types=server_types,
                force_refresh=False,
                user_id=456
            )

    # ===================
    # Statistics tests
    # ===================

    def test_get_version_statistics_success(self, management_service):
        """Test successful version statistics retrieval"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock version data
            mock_versions = {
                'vanilla': [Mock(version='1.21.6', last_updated=datetime.utcnow())],
                'paper': [Mock(version='1.21.6-123', last_updated=datetime.utcnow())],
                'fabric': [],
                'forge': [Mock(version='1.21.6-forge-1.0.0', last_updated=datetime.utcnow())]
            }

            def mock_get_versions_by_server_type(server_type):
                return mock_versions.get(server_type, [])

            mock_repo.get_versions_by_server_type.side_effect = mock_get_versions_by_server_type
            mock_repo.get_all_versions.return_value = [Mock(last_updated=datetime.utcnow())]

            stats = management_service.get_version_statistics()

            assert stats['total_versions'] == 3
            assert stats['by_server_type']['vanilla']['count'] == 1
            assert stats['by_server_type']['paper']['count'] == 1
            assert stats['by_server_type']['fabric']['count'] == 0
            assert stats['by_server_type']['forge']['count'] == 1
            assert stats['database_status'] == 'healthy'
            assert stats['last_update'] is not None

    def test_get_version_statistics_with_errors(self, management_service):
        """Test version statistics with some errors"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock some server types to raise errors
            def mock_get_versions_with_error(server_type):
                if server_type == 'fabric':
                    raise Exception("Database connection error")
                return [Mock(version='1.21.6', last_updated=datetime.utcnow())]

            mock_repo.get_versions_by_server_type.side_effect = mock_get_versions_with_error
            mock_repo.get_all_versions.return_value = [Mock(last_updated=datetime.utcnow())]

            stats = management_service.get_version_statistics()

            assert stats['database_status'] == 'degraded'
            assert 'error' in stats['by_server_type']['fabric']
            assert stats['by_server_type']['vanilla']['count'] == 1

    # ===================
    # Cleanup tests
    # ===================

    def test_cleanup_old_versions_success(self, management_service):
        """Test successful version cleanup"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock version data - simulate having more versions than keep_latest
            mock_versions = [Mock(id=i, version=f'1.21.{i}') for i in range(150)]

            def mock_get_versions_by_server_type(server_type):
                return mock_versions

            mock_repo.get_versions_by_server_type.side_effect = mock_get_versions_by_server_type
            mock_repo.delete_version.return_value = True

            # Mock session for committing
            management_service._db_session.commit = Mock()

            result = management_service.cleanup_old_versions(keep_latest=100)

            assert result['status'] == 'success'
            assert result['total_removed'] == 200  # 50 removed per server type * 4 types

            # Should have called delete_version for each version beyond keep_latest
            assert mock_repo.delete_version.call_count == 200

    def test_cleanup_old_versions_no_cleanup_needed(self, management_service):
        """Test cleanup when no cleanup is needed"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock having fewer versions than keep_latest
            mock_versions = [Mock(id=i, version=f'1.21.{i}') for i in range(50)]
            mock_repo.get_versions_by_server_type.return_value = mock_versions

            # Mock session for committing
            management_service._db_session.commit = Mock()

            result = management_service.cleanup_old_versions(keep_latest=100)

            assert result['status'] == 'success'
            assert result['total_removed'] == 0

            # Should not have called delete_version
            mock_repo.delete_version.assert_not_called()

    def test_cleanup_old_versions_with_errors(self, management_service):
        """Test cleanup with some errors"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock some server types to raise errors
            def mock_get_versions_with_error(server_type):
                if server_type == 'forge':
                    raise Exception("Database error")
                return [Mock(id=i, version=f'1.21.{i}') for i in range(150)]

            mock_repo.get_versions_by_server_type.side_effect = mock_get_versions_with_error
            mock_repo.delete_version.return_value = True

            # Mock session for committing
            management_service._db_session.commit = Mock()

            result = management_service.cleanup_old_versions(keep_latest=100)

            assert result['status'] == 'partial_failure'
            assert 'error' in result['by_server_type']['forge']
            assert result['total_removed'] == 150  # 50 removed for 3 working server types

    # ===================
    # Database validation tests
    # ===================

    def test_validate_database_integrity_healthy(self, management_service):
        """Test database validation when everything is healthy"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock no duplicates
            mock_repo.find_duplicate_versions.return_value = []

            # Mock versions exist for all server types
            mock_repo.get_versions_by_server_type.return_value = [
                Mock(version='1.21.6'),
                Mock(version='1.21.5')
            ]

            # Mock no old versions
            mock_repo.get_versions_older_than.return_value = []

            result = management_service.validate_database_integrity()

            assert result['status'] == 'healthy'
            assert len(result['issues']) == 0
            assert len(result['warnings']) == 0
            assert 'vanilla' in result['statistics']
            assert 'paper' in result['statistics']

    def test_validate_database_integrity_with_issues(self, management_service):
        """Test database validation with issues found"""
        with patch('app.versions.management.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo

            # Mock duplicates found
            mock_repo.find_duplicate_versions.return_value = [
                ('vanilla', '1.21.6', 2),
                ('paper', '1.21.5', 3)
            ]

            # Mock some server types have no versions
            def mock_get_versions_by_server_type(server_type):
                if server_type == 'fabric':
                    return []
                return [Mock(version='1.21.6')]

            mock_repo.get_versions_by_server_type.side_effect = mock_get_versions_by_server_type

            # Mock old versions found
            old_date = datetime.utcnow() - timedelta(days=35)
            mock_repo.get_versions_older_than.return_value = [
                Mock(version='1.20.1', last_updated=old_date)
            ]

            result = management_service.validate_database_integrity()

            assert result['status'] == 'issues_found'
            assert len(result['issues']) == 1
            assert 'duplicate' in result['issues'][0].lower()
            assert len(result['warnings']) == 2  # No fabric versions + old versions

    # ===================
    # Session management tests
    # ===================

    def test_session_management_with_provided_session(self):
        """Test that provided session is used and not closed"""
        mock_session = Mock()
        service = VersionManagementService(mock_session)

        # Test that provided session is used
        assert service._get_db_session() == mock_session
        assert not service._owns_session

        # Test that session is not closed when provided externally
        service._close_session_if_owned(mock_session)
        mock_session.close.assert_not_called()

    def test_session_management_without_provided_session(self):
        """Test that new session is created when none provided"""
        service = VersionManagementService()

        with patch('app.versions.management.SessionLocal') as mock_session_local:
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Test that new session is created
            session = service._get_db_session()
            assert session == mock_session
            assert service._owns_session

            # Test that session is closed when we own it
            service._close_session_if_owned(session)
            mock_session.close.assert_called_once()


# ===================
# Convenience function tests
# ===================

class TestConvenienceFunctions:
    """Test convenience functions"""

    @pytest.mark.asyncio
    async def test_trigger_version_update_convenience_function(self):
        """Test the convenience function for triggering updates"""
        from app.versions.management import trigger_version_update

        with patch('app.versions.management.VersionManagementService') as mock_service_class:
            # Mock management service
            mock_service = Mock()
            mock_service_class.return_value = mock_service

            mock_result = VersionUpdateResult(
                success=True,
                message="Success",
                versions_added=5,
                versions_updated=0,
                versions_removed=0,
                execution_time_ms=1000,
                errors=[]
            )

            mock_service.trigger_manual_update = AsyncMock(return_value=mock_result)

            # Test function call
            result = await trigger_version_update(
                server_types=['vanilla', 'paper'],
                force_refresh=True
            )

            assert result.success
            assert result.versions_added == 5

            # Verify service was called correctly
            mock_service.trigger_manual_update.assert_called_once()
            call_args = mock_service.trigger_manual_update.call_args
            assert call_args[1]['force_refresh'] is True
            assert call_args[1]['user_id'] is None

    @pytest.mark.asyncio
    async def test_trigger_version_update_invalid_server_type(self):
        """Test convenience function with invalid server type"""
        from app.versions.management import trigger_version_update

        with patch('app.versions.management.VersionManagementService') as mock_service_class:
            # Mock management service
            mock_service = Mock()
            mock_service_class.return_value = mock_service

            mock_result = VersionUpdateResult(
                success=True,
                message="Success",
                versions_added=2,
                versions_updated=0,
                versions_removed=0,
                execution_time_ms=800,
                errors=[]
            )

            mock_service.trigger_manual_update = AsyncMock(return_value=mock_result)

            # Test with invalid server type - should be filtered out
            result = await trigger_version_update(
                server_types=['vanilla', 'invalid_type', 'paper'],
                force_refresh=False
            )

            assert result.success

            # Should still call service (invalid types are just logged as warnings)
            mock_service.trigger_manual_update.assert_called_once()
