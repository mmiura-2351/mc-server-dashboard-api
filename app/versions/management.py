"""
Version Management Utilities

Administrative tools for version data management including
manual update triggers and database maintenance operations.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.servers.models import ServerType
from app.versions.repository import VersionRepository
from app.versions.schemas import VersionUpdateResult
from app.versions.service import VersionUpdateService

logger = logging.getLogger(__name__)


class VersionManagementService:
    """
    High-level version management service for administrative operations.

    Provides convenient methods for manual version updates, database
    maintenance, and system administration tasks.
    """

    def __init__(self, db_session: Optional[Session] = None):
        """
        Initialize version management service.

        Args:
            db_session: Optional database session. If not provided,
                       a new session will be created for each operation.
        """
        self._db_session = db_session
        self._owns_session = db_session is None

    def _get_db_session(self) -> Session:
        """Get database session (create if needed)"""
        if self._db_session:
            return self._db_session
        return SessionLocal()

    def _close_session_if_owned(self, session: Session) -> None:
        """Close session if we own it"""
        if self._owns_session:
            try:
                session.close()
            except Exception as e:
                logger.warning(f"Error closing database session: {e}")

    async def trigger_manual_update(
        self,
        server_types: Optional[list[ServerType]] = None,
        force_refresh: bool = True,
        user_id: Optional[int] = None,
    ) -> VersionUpdateResult:
        """
        Trigger a manual version update from external APIs.

        Args:
            server_types: List of server types to update (None for all)
            force_refresh: Force refresh even if recently updated
            user_id: ID of user triggering the update (for audit logging)

        Returns:
            VersionUpdateResult with operation summary
        """
        logger.info(f"Manual version update triggered by user {user_id or 'system'}")

        db_session = self._get_db_session()
        try:
            version_service = VersionUpdateService(db_session)
            result = await version_service.update_versions(
                server_types=server_types, force_refresh=force_refresh, user_id=user_id
            )

            if result.success:
                logger.info(
                    f"Manual update completed: +{result.versions_added} "
                    f"-{result.versions_removed} ~{result.versions_updated}"
                )
            else:
                logger.error(f"Manual update failed: {result.message}")

            return result

        finally:
            self._close_session_if_owned(db_session)

    def get_version_statistics(self) -> dict:
        """
        Get comprehensive version database statistics.

        Returns:
            Dictionary with version counts, last update times, etc.
        """
        db_session = self._get_db_session()
        try:
            repo = VersionRepository(db_session)

            # Get counts by server type
            stats = {
                "total_versions": 0,
                "by_server_type": {},
                "last_update": None,
                "database_status": "healthy",
            }

            for server_type in ["vanilla", "paper", "fabric", "forge"]:
                try:
                    versions = repo.get_versions_by_server_type(server_type)
                    count = len(versions)
                    stats["by_server_type"][server_type] = {
                        "count": count,
                        "latest_version": versions[0].version if versions else None,
                        "last_updated": versions[0].last_updated if versions else None,
                    }
                    stats["total_versions"] += count
                except Exception as e:
                    logger.warning(f"Error getting stats for {server_type}: {e}")
                    stats["by_server_type"][server_type] = {
                        "count": 0,
                        "latest_version": None,
                        "last_updated": None,
                        "error": str(e),
                    }
                    stats["database_status"] = "degraded"

            # Get overall last update time
            try:
                latest_versions = repo.get_all_versions(limit=1)
                if latest_versions:
                    stats["last_update"] = latest_versions[0].last_updated
            except Exception as e:
                logger.warning(f"Error getting last update time: {e}")
                stats["database_status"] = "degraded"

            return stats

        finally:
            self._close_session_if_owned(db_session)

    def cleanup_old_versions(
        self, server_type: Optional[str] = None, keep_latest: int = 100
    ) -> dict:
        """
        Clean up old version records to manage database size.

        Args:
            server_type: Specific server type to clean (None for all)
            keep_latest: Number of latest versions to keep per server type

        Returns:
            Dictionary with cleanup results
        """
        logger.info(f"Starting version cleanup (keep latest {keep_latest})")

        db_session = self._get_db_session()
        try:
            repo = VersionRepository(db_session)

            cleanup_results = {
                "total_removed": 0,
                "by_server_type": {},
                "status": "success",
            }

            server_types = (
                [server_type] if server_type else ["vanilla", "paper", "fabric", "forge"]
            )

            for stype in server_types:
                try:
                    # Get all versions for this server type, sorted by date
                    all_versions = repo.get_versions_by_server_type(stype)

                    if len(all_versions) <= keep_latest:
                        cleanup_results["by_server_type"][stype] = {
                            "removed": 0,
                            "remaining": len(all_versions),
                            "message": f"No cleanup needed ({len(all_versions)} <= {keep_latest})",
                        }
                        continue

                    # Remove old versions (keep the latest ones)
                    versions_to_remove = all_versions[keep_latest:]
                    removed_count = 0

                    for version in versions_to_remove:
                        try:
                            success = repo.delete_version(version.id)
                            if success:
                                removed_count += 1
                        except Exception as e:
                            logger.warning(f"Error removing version {version.id}: {e}")

                    cleanup_results["by_server_type"][stype] = {
                        "removed": removed_count,
                        "remaining": len(all_versions) - removed_count,
                        "message": f"Cleaned up {removed_count} old versions",
                    }
                    cleanup_results["total_removed"] += removed_count

                except Exception as e:
                    logger.error(f"Error cleaning up {stype} versions: {e}")
                    cleanup_results["by_server_type"][stype] = {
                        "removed": 0,
                        "remaining": "unknown",
                        "error": str(e),
                    }
                    cleanup_results["status"] = "partial_failure"

            # Commit changes
            db_session.commit()

            logger.info(
                f"Version cleanup completed: {cleanup_results['total_removed']} versions removed"
            )
            return cleanup_results

        except Exception as e:
            logger.error(f"Version cleanup failed: {e}")
            db_session.rollback()
            return {
                "total_removed": 0,
                "by_server_type": {},
                "status": "failed",
                "error": str(e),
            }
        finally:
            self._close_session_if_owned(db_session)

    def validate_database_integrity(self) -> dict:
        """
        Validate version database integrity and consistency.

        Returns:
            Dictionary with validation results and any issues found
        """
        logger.info("Starting version database integrity validation")

        db_session = self._get_db_session()
        try:
            repo = VersionRepository(db_session)

            validation_results = {
                "status": "healthy",
                "issues": [],
                "warnings": [],
                "statistics": {},
            }

            # Check for duplicate versions
            try:
                duplicates = repo.find_duplicate_versions()
                if duplicates:
                    validation_results["issues"].append(
                        f"Found {len(duplicates)} duplicate version entries"
                    )
                    validation_results["status"] = "issues_found"
            except Exception as e:
                validation_results["warnings"].append(
                    f"Could not check for duplicates: {e}"
                )

            # Check for missing server types
            expected_types = ["vanilla", "paper", "fabric", "forge"]
            for server_type in expected_types:
                try:
                    versions = repo.get_versions_by_server_type(server_type)
                    if not versions:
                        validation_results["warnings"].append(
                            f"No versions found for server type: {server_type}"
                        )
                    else:
                        validation_results["statistics"][server_type] = len(versions)
                except Exception as e:
                    validation_results["issues"].append(
                        f"Error checking {server_type} versions: {e}"
                    )
                    validation_results["status"] = "issues_found"

            # Check for very old data (older than 30 days)
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=30)
                old_versions = repo.get_versions_older_than(cutoff_date)
                if old_versions:
                    validation_results["warnings"].append(
                        f"Found {len(old_versions)} versions older than 30 days"
                    )
            except Exception as e:
                validation_results["warnings"].append(
                    f"Could not check for old versions: {e}"
                )

            logger.info(f"Database validation completed: {validation_results['status']}")
            return validation_results

        finally:
            self._close_session_if_owned(db_session)


# Convenience function for scripts and CLI usage
async def trigger_version_update(
    server_types: Optional[list[str]] = None, force_refresh: bool = True
) -> VersionUpdateResult:
    """
    Convenience function to trigger version updates from scripts.

    Args:
        server_types: List of server type strings to update
        force_refresh: Force refresh even if recently updated

    Returns:
        VersionUpdateResult with operation summary
    """
    management_service = VersionManagementService()

    # Convert string server types to enum values if provided
    server_type_enums = None
    if server_types:
        server_type_enums = []
        for stype in server_types:
            try:
                server_type_enums.append(ServerType(stype))
            except ValueError:
                logger.warning(f"Invalid server type: {stype}")

    return await management_service.trigger_manual_update(
        server_types=server_type_enums, force_refresh=force_refresh, user_id=None
    )
