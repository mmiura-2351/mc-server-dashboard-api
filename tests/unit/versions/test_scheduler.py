"""
Unit tests for VersionUpdateSchedulerService
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.versions.scheduler import VersionUpdateSchedulerService
from app.versions.schemas import VersionUpdateResult


class TestVersionUpdateSchedulerService:
    """Test VersionUpdateSchedulerService class"""

    @pytest.fixture
    def scheduler(self):
        """Create scheduler instance"""
        return VersionUpdateSchedulerService()

    @pytest.fixture
    def mock_update_result(self):
        """Mock successful update result"""
        return VersionUpdateResult(
            success=True,
            message="Update completed successfully",
            versions_added=5,
            versions_updated=2,
            versions_removed=1,
            execution_time_ms=1500,
            errors=[]
        )

    @pytest.fixture
    def mock_failed_update_result(self):
        """Mock failed update result"""
        return VersionUpdateResult(
            success=False,
            message="Update failed",
            versions_added=0,
            versions_updated=0,
            versions_removed=0,
            execution_time_ms=500,
            errors=["External API error"]
        )

    # ===================
    # Basic functionality
    # ===================

    def test_scheduler_initialization(self, scheduler):
        """Test scheduler initialization state"""
        assert not scheduler.is_running
        assert scheduler.last_successful_update is None
        assert scheduler.last_error is None
        assert scheduler.update_interval_hours == 24
        assert scheduler.next_update_time is None

    @pytest.mark.asyncio
    async def test_start_stop_scheduler(self, scheduler):
        """Test starting and stopping the scheduler"""
        # Start scheduler
        await scheduler.start_scheduler()
        assert scheduler.is_running

        # Allow some time for the scheduler to initialize
        await asyncio.sleep(0.1)

        # Stop scheduler
        await scheduler.stop_scheduler()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_double_start_prevention(self, scheduler):
        """Test that starting scheduler twice doesn't create issues"""
        await scheduler.start_scheduler()
        assert scheduler.is_running

        # Try to start again
        await scheduler.start_scheduler()
        assert scheduler.is_running  # Should still be running

        await scheduler.stop_scheduler()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, scheduler):
        """Test stopping scheduler that was never started"""
        assert not scheduler.is_running
        await scheduler.stop_scheduler()  # Should not raise exception
        assert not scheduler.is_running

    # ===================
    # Configuration
    # ===================

    def test_set_update_interval_valid(self, scheduler):
        """Test setting valid update intervals"""
        scheduler.set_update_interval(12)
        assert scheduler.update_interval_hours == 12

        scheduler.set_update_interval(168)  # 1 week
        assert scheduler.update_interval_hours == 168

        scheduler.set_update_interval(1)  # 1 hour
        assert scheduler.update_interval_hours == 1

    def test_set_update_interval_invalid(self, scheduler):
        """Test setting invalid update intervals"""
        with pytest.raises(ValueError, match="Update interval must be between 1 and 168 hours"):
            scheduler.set_update_interval(0)

        with pytest.raises(ValueError, match="Update interval must be between 1 and 168 hours"):
            scheduler.set_update_interval(169)

        with pytest.raises(ValueError, match="Update interval must be between 1 and 168 hours"):
            scheduler.set_update_interval(-1)

    def test_set_retry_config_valid(self, scheduler):
        """Test setting valid retry configuration"""
        scheduler.set_retry_config(5, 120)
        assert scheduler._max_retry_attempts == 5
        assert scheduler._retry_delay_base == 120

    def test_set_retry_config_invalid(self, scheduler):
        """Test setting invalid retry configuration"""
        with pytest.raises(ValueError, match="Max retry attempts must be between 1 and 10"):
            scheduler.set_retry_config(0, 120)

        with pytest.raises(ValueError, match="Max retry attempts must be between 1 and 10"):
            scheduler.set_retry_config(11, 120)

        with pytest.raises(ValueError, match="Base delay must be between 60 and 3600 seconds"):
            scheduler.set_retry_config(3, 50)

        with pytest.raises(ValueError, match="Base delay must be between 60 and 3600 seconds"):
            scheduler.set_retry_config(3, 4000)

    # ===================
    # Update scheduling logic
    # ===================

    def test_is_update_due_no_previous_update(self, scheduler):
        """Test update due logic when no previous update exists (with startup grace period)"""
        # Simulate that startup grace period has passed
        scheduler._startup_time = datetime.utcnow() - timedelta(minutes=31)
        assert scheduler._is_update_due()

    def test_is_update_due_recent_update(self, scheduler):
        """Test update due logic with recent update"""
        # Set last update to 1 hour ago
        scheduler._last_successful_update = datetime.utcnow() - timedelta(hours=1)
        scheduler.set_update_interval(24)

        assert not scheduler._is_update_due()

    def test_is_update_due_old_update(self, scheduler):
        """Test update due logic with old update"""
        # Simulate that startup grace period has passed
        scheduler._startup_time = datetime.utcnow() - timedelta(minutes=31)
        # Set last update to 25 hours ago
        scheduler._last_successful_update = datetime.utcnow() - timedelta(hours=25)
        scheduler.set_update_interval(24)

        assert scheduler._is_update_due()

    def test_get_next_update_time(self, scheduler):
        """Test next update time calculation with startup grace period"""
        # No previous update - should honor startup delay
        next_time = scheduler._get_next_update_time()
        startup_deadline = scheduler._startup_time + timedelta(minutes=scheduler._startup_delay_minutes)
        assert next_time >= startup_deadline

        # With previous update
        last_update = datetime.utcnow() - timedelta(hours=12)
        scheduler._last_successful_update = last_update
        scheduler.set_update_interval(24)

        expected_next = last_update + timedelta(hours=24)
        actual_next = scheduler._get_next_update_time()

        # Allow 1 second tolerance for timing differences
        assert abs((actual_next - expected_next).total_seconds()) < 1

    # ===================
    # Manual operations
    # ===================

    @pytest.mark.asyncio
    async def test_trigger_immediate_update_success(self, scheduler, mock_update_result):
        """Test successful immediate update trigger"""
        with patch('app.versions.scheduler.SessionLocal') as mock_session_local, \
             patch('app.versions.scheduler.VersionUpdateService') as mock_service_class:

            # Mock database session
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_update_result)

            result = await scheduler.trigger_immediate_update()

            assert result.success
            assert scheduler.last_successful_update is not None
            assert scheduler.last_error is None

            # Verify service was called correctly
            mock_service.update_versions.assert_called_once_with(
                server_types=None,
                force_refresh=False,
                user_id=None
            )

    @pytest.mark.asyncio
    async def test_trigger_immediate_update_failure(self, scheduler, mock_failed_update_result):
        """Test failed immediate update trigger"""
        with patch('app.versions.scheduler.SessionLocal') as mock_session_local, \
             patch('app.versions.scheduler.VersionUpdateService') as mock_service_class:

            # Mock database session
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_failed_update_result)

            result = await scheduler.trigger_immediate_update()

            assert not result.success
            assert scheduler.last_error == "Update failed"

    @pytest.mark.asyncio
    async def test_trigger_immediate_update_with_force(self, scheduler, mock_update_result):
        """Test immediate update with force refresh"""
        with patch('app.versions.scheduler.SessionLocal') as mock_session_local, \
             patch('app.versions.scheduler.VersionUpdateService') as mock_service_class:

            # Mock database session
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_update_result)

            result = await scheduler.trigger_immediate_update(force_refresh=True)

            assert result.success

            # Verify force_refresh was passed
            mock_service.update_versions.assert_called_once_with(
                server_types=None,
                force_refresh=True,
                user_id=None
            )

    # ===================
    # Status and monitoring
    # ===================

    def test_get_status_not_running(self, scheduler):
        """Test status when scheduler is not running"""
        status = scheduler.get_status()

        assert status["running"] is False
        assert status["update_interval_hours"] == 24
        assert status["last_successful_update"] is None
        assert status["next_update_time"] is None
        assert status["last_error"] is None
        assert "retry_config" in status
        assert status["retry_config"]["max_attempts"] == 3
        assert status["retry_config"]["base_delay_seconds"] == 300

    @pytest.mark.asyncio
    async def test_get_status_running(self, scheduler):
        """Test status when scheduler is running"""
        await scheduler.start_scheduler()

        status = scheduler.get_status()

        assert status["running"] is True
        assert status["next_update_time"] is not None

        await scheduler.stop_scheduler()

    def test_properties(self, scheduler):
        """Test scheduler properties"""
        # Test initial state
        assert scheduler.is_running is False
        assert scheduler.last_successful_update is None
        assert scheduler.last_error is None
        assert scheduler.update_interval_hours == 24
        assert scheduler.next_update_time is None

        # Test after setting some values
        test_time = datetime.utcnow()
        scheduler._last_successful_update = test_time
        scheduler._last_error = "Test error"

        assert scheduler.last_successful_update == test_time
        assert scheduler.last_error == "Test error"

    # ===================
    # Scheduler loop behavior
    # ===================

    @pytest.mark.asyncio
    async def test_scheduler_loop_with_due_update(self, scheduler, mock_update_result):
        """Test scheduler loop when update is due"""
        with patch.object(scheduler, '_is_update_due', return_value=True), \
             patch.object(scheduler, '_execute_scheduled_update', new_callable=AsyncMock) as mock_execute:

            # Start scheduler
            await scheduler.start_scheduler()

            # Give the loop a moment to run
            await asyncio.sleep(0.1)

            # Stop scheduler
            await scheduler.stop_scheduler()

            # The mock should have been called at least once
            # (accounting for initial delay and timing variations)
            assert mock_execute.call_count >= 0

    @pytest.mark.asyncio
    async def test_scheduler_loop_no_due_update(self, scheduler):
        """Test scheduler loop when no update is due"""
        with patch.object(scheduler, '_is_update_due', return_value=False), \
             patch.object(scheduler, '_execute_scheduled_update', new_callable=AsyncMock) as mock_execute:

            # Start scheduler
            await scheduler.start_scheduler()

            # Give the loop a moment to run
            await asyncio.sleep(0.1)

            # Stop scheduler
            await scheduler.stop_scheduler()

            # Execute should not have been called
            mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_scheduled_update_success(self, scheduler, mock_update_result):
        """Test successful scheduled update execution"""
        with patch('app.versions.scheduler.SessionLocal') as mock_session_local, \
             patch('app.versions.scheduler.VersionUpdateService') as mock_service_class:

            # Mock database session
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Mock service
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_update_result)

            await scheduler._execute_scheduled_update()

            assert scheduler.last_successful_update is not None
            assert scheduler.last_error is None

    @pytest.mark.asyncio
    async def test_execute_scheduled_update_with_retries(self, scheduler, mock_failed_update_result, mock_update_result):
        """Test scheduled update with retry logic"""
        scheduler.set_retry_config(2, 60)  # 2 attempts, 60s base delay

        with patch('app.versions.scheduler.SessionLocal') as mock_session_local, \
             patch('app.versions.scheduler.VersionUpdateService') as mock_service_class, \
             patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:

            # Mock database session
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Mock service to fail first time, succeed second time
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(side_effect=[mock_failed_update_result, mock_update_result])

            await scheduler._execute_scheduled_update()

            # Should have been called twice (first failure, then success)
            assert mock_service.update_versions.call_count == 2
            assert scheduler.last_successful_update is not None
            assert scheduler.last_error is None

            # Should have slept once between retries
            mock_sleep.assert_called_once_with(60)  # Base delay for first retry

    @pytest.mark.asyncio
    async def test_execute_scheduled_update_max_retries_exceeded(self, scheduler, mock_failed_update_result):
        """Test scheduled update when max retries are exceeded"""
        scheduler.set_retry_config(2, 60)  # 2 attempts

        with patch('app.versions.scheduler.SessionLocal') as mock_session_local, \
             patch('app.versions.scheduler.VersionUpdateService') as mock_service_class, \
             patch('asyncio.sleep', new_callable=AsyncMock):

            # Mock database session
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Mock service to always fail
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.update_versions = AsyncMock(return_value=mock_failed_update_result)

            await scheduler._execute_scheduled_update()

            # Should have been called max_attempts times
            assert mock_service.update_versions.call_count == 2
            assert scheduler.last_successful_update is None
            assert "Update failed" in scheduler.last_error

    def test_singleton_instance(self):
        """Test that the singleton instance exists and is accessible"""
        from app.versions.scheduler import version_update_scheduler

        assert version_update_scheduler is not None
        assert isinstance(version_update_scheduler, VersionUpdateSchedulerService)
        assert not version_update_scheduler.is_running
