"""
Version Update Service

This service manages version updates from external APIs to database storage.
Replaces real-time API calls with database-based version management.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.servers.models import ServerType
from app.services.version_manager import minecraft_version_manager
from app.versions.models import MinecraftVersion
from app.versions.repository import VersionRepository
from app.versions.schemas import (
    MinecraftVersionCreate,
    UpdateStatusResponse,
    VersionUpdateLogCreate,
    VersionUpdateResult,
)

logger = logging.getLogger(__name__)


class VersionUpdateService:
    """
    Service for updating version information from external APIs to database.

    This service provides:
    - Manual and automatic version updates
    - Background synchronization with external APIs
    - Version statistics and monitoring
    - Update logging and error handling
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = VersionRepository(db)
        self._update_running = False
        self._last_update_time: Optional[datetime] = None

    async def update_versions(
        self,
        server_types: Optional[List[ServerType]] = None,
        force_refresh: bool = False,
        user_id: Optional[int] = None,
    ) -> VersionUpdateResult:
        """
        Update version information from external APIs.

        Args:
            server_types: List of server types to update (None = all types)
            force_refresh: Force refresh even if recently updated
            user_id: User ID triggering the update (for audit trail)

        Returns:
            VersionUpdateResult with operation summary
        """
        if self._update_running and not force_refresh:
            return VersionUpdateResult(
                success=False,
                message="Version update already in progress",
                errors=["Another update operation is currently running"],
            )

        # Determine which server types to update
        if server_types is None:
            server_types = list(ServerType)

        self._update_running = True
        start_time = time.time()

        # Create update log
        log_data = VersionUpdateLogCreate(
            update_type="manual" if user_id else "automatic",
            status="running",
            executed_by_user_id=user_id,
        )
        update_log = await self.repository.create_update_log(log_data)

        total_added = 0
        total_updated = 0
        total_removed = 0
        total_api_calls = 0
        errors = []

        try:
            logger.info(
                f"Starting version update for types: {[t.value for t in server_types]}"
            )

            # Process each server type
            for server_type in server_types:
                try:
                    result = await self._update_server_type_versions(
                        server_type, force_refresh
                    )
                    total_added += result["added"]
                    total_updated += result["updated"]
                    total_removed += result["removed"]
                    total_api_calls += result["api_calls"]

                    logger.info(
                        f"Updated {server_type.value}: "
                        f"+{result['added']} -{result['removed']} ~{result['updated']}"
                    )

                except Exception as e:
                    error_msg = f"Failed to update {server_type.value}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Complete update log
            status = (
                "success"
                if not errors
                else "partial_success"
                if total_added + total_updated > 0
                else "failed"
            )
            await self.repository.complete_update_log(
                update_log.id,
                status=status,
                execution_time_ms=execution_time_ms,
                error_message="; ".join(errors) if errors else None,
            )

            # Update the log with final counts
            self.db.query(type(update_log)).filter_by(id=update_log.id).update(
                {
                    "versions_added": total_added,
                    "versions_updated": total_updated,
                    "versions_removed": total_removed,
                    "external_api_calls": total_api_calls,
                }
            )
            self.db.commit()

            self._last_update_time = datetime.utcnow()

            success_msg = (
                f"Version update completed: +{total_added} -{total_removed} ~{total_updated} "
                f"({execution_time_ms}ms, {total_api_calls} API calls)"
            )

            logger.info(success_msg)

            return VersionUpdateResult(
                success=True,
                message=success_msg,
                log_id=update_log.id,
                versions_added=total_added,
                versions_updated=total_updated,
                versions_removed=total_removed,
                execution_time_ms=execution_time_ms,
                errors=errors,
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Version update failed: {str(e)}"
            logger.error(error_msg)

            # Complete log with error
            await self.repository.complete_update_log(
                update_log.id,
                status="failed",
                execution_time_ms=execution_time_ms,
                error_message=error_msg,
            )

            return VersionUpdateResult(
                success=False,
                message=error_msg,
                log_id=update_log.id,
                execution_time_ms=execution_time_ms,
                errors=[error_msg],
            )

        finally:
            self._update_running = False

    async def _update_server_type_versions(
        self, server_type: ServerType, force_refresh: bool = False
    ) -> Dict[str, int]:
        """
        Update versions for a specific server type.

        Returns:
            Dictionary with counts: {"added": int, "updated": int, "removed": int, "api_calls": int}
        """
        api_calls_count = 0

        try:
            # Fetch latest versions from external API
            logger.debug(f"Fetching {server_type.value} versions from external API...")
            external_versions = await minecraft_version_manager.get_supported_versions(
                server_type
            )
            api_calls_count = len(external_versions) + 1  # +1 for initial API call

            if not external_versions:
                logger.warning(f"No versions received for {server_type.value}")
                return {
                    "added": 0,
                    "updated": 0,
                    "removed": 0,
                    "api_calls": api_calls_count,
                }

            # Get current database versions
            current_versions = await self.repository.get_versions_by_type(server_type)
            current_version_map = {v.version: v for v in current_versions}

            # Track changes
            added_count = 0
            updated_count = 0

            # Create or update versions from external API
            external_version_ids = set()
            for ext_version in external_versions:
                external_version_ids.add(ext_version.version)

                version_data = MinecraftVersionCreate(
                    server_type=ext_version.server_type,
                    version=ext_version.version,
                    download_url=ext_version.download_url,
                    release_date=ext_version.release_date,
                    is_stable=ext_version.is_stable,
                    build_number=ext_version.build_number,
                )

                if ext_version.version in current_version_map:
                    # Check if update is needed
                    current = current_version_map[ext_version.version]
                    needs_update = (
                        current.download_url != ext_version.download_url
                        or current.is_stable != ext_version.is_stable
                        or current.build_number != ext_version.build_number
                        or not current.is_active
                    )

                    if needs_update:
                        await self.repository.upsert_version(version_data)
                        updated_count += 1
                        logger.debug(f"Updated {server_type.value} {ext_version.version}")
                else:
                    # New version
                    await self.repository.upsert_version(version_data)
                    added_count += 1
                    logger.debug(f"Added {server_type.value} {ext_version.version}")

            # Deactivate versions not in external API (but keep them for history)
            all_current_version_ids = [v.version for v in current_versions if v.is_active]
            versions_to_deactivate = [
                v_id
                for v_id in all_current_version_ids
                if v_id not in external_version_ids
            ]

            removed_count = 0
            if versions_to_deactivate:
                removed_count = await self.repository.deactivate_versions(
                    server_type, list(external_version_ids)
                )
                logger.debug(
                    f"Deactivated {removed_count} {server_type.value} versions: {versions_to_deactivate}"
                )

            return {
                "added": added_count,
                "updated": updated_count,
                "removed": removed_count,
                "api_calls": api_calls_count,
            }

        except Exception as e:
            logger.error(f"Error updating {server_type.value} versions: {e}")
            raise

    async def get_update_status(self) -> UpdateStatusResponse:
        """Get current update status and statistics."""
        # Get latest update log
        latest_log = await self.repository.get_latest_update_log()

        # Get version statistics
        stats = await self.repository.get_version_stats()
        total_versions = stats.get("_total", {}).get("active", 0)
        versions_by_type = {
            k: v.get("active", 0) for k, v in stats.items() if k != "_total"
        }

        return UpdateStatusResponse(
            last_update=latest_log,
            total_versions=total_versions,
            versions_by_type=versions_by_type,
            next_scheduled_update=None,  # Will be set by scheduler
            is_update_running=self._update_running,
        )

    async def cleanup_old_versions(self, days_old: int = 30) -> int:
        """
        Clean up old inactive versions to keep database size manageable.

        Args:
            days_old: Remove inactive versions older than this many days

        Returns:
            Number of versions removed
        """
        try:
            removed_count = await self.repository.cleanup_old_versions(days_old)
            if removed_count > 0:
                logger.info(
                    f"Cleaned up {removed_count} old inactive versions (>{days_old} days)"
                )
            return removed_count
        except Exception as e:
            logger.error(f"Error during version cleanup: {e}")
            raise

    async def get_supported_versions(
        self, server_type: ServerType
    ) -> List[MinecraftVersion]:
        """
        Get supported versions from database (fast database lookup).

        This replaces the slow external API calls from the original version manager.
        """
        return await self.repository.get_versions_by_type(server_type)

    async def get_all_supported_versions(self) -> List[MinecraftVersion]:
        """Get all supported versions from database (fast database lookup)."""
        return await self.repository.get_all_active_versions()

    async def get_download_url(
        self, server_type: ServerType, version: str
    ) -> Optional[str]:
        """
        Get download URL for a specific version from database.

        This replaces the slow external API lookup from the original version manager.
        """
        version_obj = await self.repository.get_version_by_type_and_version(
            server_type, version
        )
        return version_obj.download_url if version_obj else None

    def is_version_supported(self, server_type: ServerType, version: str) -> bool:
        """
        Check if a version is supported (synchronous check).

        For now, delegates to the original version manager for validation logic.
        In the future, this could be enhanced with database-based validation.
        """
        return minecraft_version_manager.is_version_supported(server_type, version)

    @property
    def is_update_running(self) -> bool:
        """Check if an update operation is currently running."""
        return self._update_running

    @property
    def last_update_time(self) -> Optional[datetime]:
        """Get the timestamp of the last successful update."""
        return self._last_update_time


# Dependency injection helper
def get_version_update_service() -> VersionUpdateService:
    """Get VersionUpdateService instance with database dependency."""
    db = next(get_db())
    return VersionUpdateService(db)
