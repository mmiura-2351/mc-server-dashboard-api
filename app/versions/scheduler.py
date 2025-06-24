"""
Version Update Scheduler Service

Background task scheduler for automatic version updates from external APIs.
Integrates with existing asyncio-based task system.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.core.database import SessionLocal
from app.versions.schemas import VersionUpdateResult
from app.versions.service import VersionUpdateService

logger = logging.getLogger(__name__)


class VersionUpdateSchedulerService:
    """
    Background scheduler for automatic version updates.

    Features:
    - Configurable update intervals (default: daily)
    - Automatic retry on failure with exponential backoff
    - Health monitoring and error reporting
    - Integration with existing FastAPI lifecycle
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._update_interval_hours = 24  # Default: daily updates
        self._max_retry_attempts = 3
        self._retry_delay_base = 300  # 5 minutes base delay
        self._startup_delay_minutes = 30  # Wait 30 minutes after startup
        self._last_successful_update: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._startup_time = datetime.utcnow()  # Track when scheduler started

    # ===================
    # Scheduler control
    # ===================

    async def start_scheduler(self) -> None:
        """Start the version update scheduler"""
        if self._running:
            logger.info("Version update scheduler is already running")
            return

        self._running = True
        logger.info("Starting version update scheduler")

        # Start scheduler task
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            f"Version update scheduler started with {self._update_interval_hours}h interval"
        )

    async def stop_scheduler(self) -> None:
        """Stop the version update scheduler"""
        if not self._running:
            return

        logger.info("Stopping version update scheduler")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("Version update scheduler task cancelled")
            except Exception as e:
                logger.warning(f"Error during scheduler shutdown: {e}")
            finally:
                self._task = None

        logger.info("Version update scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop.

        Checks for due updates and executes them with proper error handling.
        """
        logger.info("Version update scheduler loop started")

        # Extended initial delay to allow application to fully start and avoid immediate updates
        logger.info(
            f"Waiting {self._startup_delay_minutes} minutes before first version update check"
        )
        await asyncio.sleep(
            self._startup_delay_minutes * 60
        )  # Wait 30 minutes after startup

        while self._running:
            try:
                # Check if update is due
                if self._is_update_due():
                    logger.info("Version update is due, starting update process")
                    await self._execute_scheduled_update()
                else:
                    # Log next update time for monitoring
                    next_update = self._get_next_update_time()
                    logger.debug(f"Next version update scheduled for: {next_update}")

                # Wait for the next check (2 hour intervals for checking to reduce load)
                await asyncio.sleep(7200)  # Check every 2 hours

            except asyncio.CancelledError:
                logger.info("Version update scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in version update scheduler loop: {e}")
                self._last_error = str(e)
                # Continue after a shorter delay on error
                await asyncio.sleep(300)  # Wait 5 minutes on error

    def _is_update_due(self) -> bool:
        """Check if a version update is due with startup grace period"""
        now = datetime.utcnow()

        # Don't update immediately after startup - give grace period
        time_since_startup = now - self._startup_time
        if time_since_startup < timedelta(minutes=self._startup_delay_minutes):
            logger.debug("Still in startup grace period, skipping update check")
            return False

        if self._last_successful_update is None:
            # No previous update, but respect startup delay
            return True

        time_since_last_update = now - self._last_successful_update
        return time_since_last_update >= timedelta(hours=self._update_interval_hours)

    def _get_next_update_time(self) -> datetime:
        """Calculate the next scheduled update time with startup grace period"""
        now = datetime.utcnow()

        if self._last_successful_update is None:
            # If no previous update, schedule after startup delay
            startup_deadline = self._startup_time + timedelta(
                minutes=self._startup_delay_minutes
            )
            return max(now, startup_deadline)

        return self._last_successful_update + timedelta(hours=self._update_interval_hours)

    async def _execute_scheduled_update(self) -> None:
        """Execute a scheduled version update with retry logic"""
        retry_count = 0

        while retry_count < self._max_retry_attempts:
            try:
                # Create database session for the update operation
                db_session = SessionLocal()

                try:
                    # Create version update service
                    update_service = VersionUpdateService(db_session)

                    # Execute update for all server types
                    logger.info(
                        f"Starting automatic version update (attempt {retry_count + 1})"
                    )
                    result = await update_service.update_versions(
                        server_types=None,  # Update all types
                        force_refresh=False,
                        user_id=None,  # Automatic/system update
                    )

                    if result.success:
                        # Update successful
                        self._last_successful_update = datetime.utcnow()
                        self._last_error = None

                        logger.info(
                            f"Automatic version update completed successfully: "
                            f"+{result.versions_added} -{result.versions_removed} "
                            f"~{result.versions_updated} ({result.execution_time_ms}ms)"
                        )

                        if result.errors:
                            logger.warning(
                                f"Update completed with warnings: {result.errors}"
                            )

                        return  # Success, exit retry loop

                    else:
                        # Update failed
                        error_msg = f"Version update failed: {result.message}"
                        logger.error(error_msg)
                        self._last_error = error_msg
                        raise Exception(error_msg)

                finally:
                    try:
                        db_session.close()
                    except Exception as e:
                        logger.warning(f"Error closing database session: {e}")

            except Exception as e:
                retry_count += 1
                error_msg = f"Version update attempt {retry_count} failed: {e}"
                logger.error(error_msg)
                self._last_error = error_msg

                if retry_count < self._max_retry_attempts:
                    # Calculate exponential backoff delay
                    delay = self._retry_delay_base * (2 ** (retry_count - 1))
                    logger.info(
                        f"Retrying in {delay} seconds (attempt {retry_count + 1}/{self._max_retry_attempts})"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Version update failed after {self._max_retry_attempts} attempts"
                    )
                    break

    # ===================
    # Manual operations
    # ===================

    async def trigger_immediate_update(
        self, force_refresh: bool = False
    ) -> VersionUpdateResult:
        """
        Trigger an immediate version update (manual operation).

        Args:
            force_refresh: Force refresh even if recently updated

        Returns:
            VersionUpdateResult with operation summary
        """
        logger.info("Manual version update triggered")

        db_session = SessionLocal()
        try:
            update_service = VersionUpdateService(db_session)
            result = await update_service.update_versions(
                server_types=None,
                force_refresh=force_refresh,
                user_id=None,  # Manual trigger but system-initiated
            )

            if result.success:
                self._last_successful_update = datetime.utcnow()
                self._last_error = None
                logger.info("Manual version update completed successfully")
            else:
                self._last_error = result.message
                logger.error(f"Manual version update failed: {result.message}")

            return result

        finally:
            try:
                db_session.close()
            except Exception as e:
                logger.warning(
                    f"Error closing database session during manual update: {e}"
                )

    # ===================
    # Configuration
    # ===================

    def set_update_interval(self, hours: int) -> None:
        """
        Set the update interval in hours.

        Args:
            hours: Update interval (minimum 1 hour, maximum 168 hours/1 week)
        """
        if not 1 <= hours <= 168:
            raise ValueError("Update interval must be between 1 and 168 hours")

        old_interval = self._update_interval_hours
        self._update_interval_hours = hours

        logger.info(f"Version update interval changed from {old_interval}h to {hours}h")

    def set_startup_delay(self, minutes: int) -> None:
        """
        Set the startup delay in minutes.

        Args:
            minutes: Startup delay (minimum 5 minutes, maximum 120 minutes/2 hours)
        """
        if not 5 <= minutes <= 120:
            raise ValueError("Startup delay must be between 5 and 120 minutes")

        old_delay = self._startup_delay_minutes
        self._startup_delay_minutes = minutes

        logger.info(
            f"Version update startup delay changed from {old_delay}m to {minutes}m"
        )

    def set_retry_config(self, max_attempts: int, base_delay_seconds: int) -> None:
        """
        Configure retry behavior.

        Args:
            max_attempts: Maximum retry attempts (1-10)
            base_delay_seconds: Base delay for exponential backoff (60-3600 seconds)
        """
        if not 1 <= max_attempts <= 10:
            raise ValueError("Max retry attempts must be between 1 and 10")
        if not 60 <= base_delay_seconds <= 3600:
            raise ValueError("Base delay must be between 60 and 3600 seconds")

        self._max_retry_attempts = max_attempts
        self._retry_delay_base = base_delay_seconds

        logger.info(
            f"Retry config updated: {max_attempts} attempts, {base_delay_seconds}s base delay"
        )

    # ===================
    # Status and monitoring
    # ===================

    @property
    def is_running(self) -> bool:
        """Whether the scheduler is running"""
        return self._running

    @property
    def last_successful_update(self) -> Optional[datetime]:
        """Timestamp of last successful update"""
        return self._last_successful_update

    @property
    def last_error(self) -> Optional[str]:
        """Last error message, if any"""
        return self._last_error

    @property
    def update_interval_hours(self) -> int:
        """Current update interval in hours"""
        return self._update_interval_hours

    @property
    def next_update_time(self) -> Optional[datetime]:
        """Next scheduled update time"""
        if not self._running:
            return None
        return self._get_next_update_time()

    def get_status(self) -> dict:
        """Get comprehensive scheduler status"""
        now = datetime.utcnow()
        time_since_startup = now - self._startup_time
        in_startup_grace = time_since_startup < timedelta(
            minutes=self._startup_delay_minutes
        )

        return {
            "running": self._running,
            "update_interval_hours": self._update_interval_hours,
            "startup_delay_minutes": self._startup_delay_minutes,
            "startup_time": self._startup_time.isoformat(),
            "in_startup_grace_period": in_startup_grace,
            "last_successful_update": self._last_successful_update.isoformat()
            if self._last_successful_update
            else None,
            "next_update_time": self.next_update_time.isoformat()
            if self.next_update_time
            else None,
            "last_error": self._last_error,
            "retry_config": {
                "max_attempts": self._max_retry_attempts,
                "base_delay_seconds": self._retry_delay_base,
            },
        }


# Singleton instance
version_update_scheduler = VersionUpdateSchedulerService()
