"""Version Update Service (application layer).

Orchestrates version updates from external APIs into persistence via the
`VersionRepository` Port and `UnitOfWork` Port. This module depends only
on `domain/` and `app.services.version_manager` (the external API
fetcher). It must not import from `adapters/` or `api/`.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from app.core.datetime_utils import utcnow
from app.servers.models import ServerType
from app.services.version_manager import minecraft_version_manager
from app.versions.application.results import UpdateStatus, VersionUpdateResult
from app.versions.domain.entities import (
    CreateUpdateLogCommand,
    CreateVersionCommand,
    MinecraftVersionEntity,
    VersionStatsEntity,
)
from app.versions.domain.ports import UnitOfWork

logger = logging.getLogger(__name__)


class VersionUpdateService:
    """Use cases over the version catalogue.

    Receives a `UnitOfWork` factory via constructor injection. Each public
    method opens a fresh UoW (one transaction) and persists atomically.
    The concrete UoW adapter is wired in `app.versions.api.dependencies`.
    """

    def __init__(self, uow: UnitOfWork):
        self._uow: UnitOfWork = uow
        self._update_running = False
        self._last_update_time: Optional[datetime] = None

    # ----- Update orchestration -----

    async def update_versions(
        self,
        server_types: Optional[List[ServerType]] = None,
        force_refresh: bool = False,
        user_id: Optional[int] = None,
    ) -> VersionUpdateResult:
        """Update version information from external APIs."""
        if self._update_running and not force_refresh:
            return VersionUpdateResult(
                success=False,
                message="Version update already in progress",
                errors=["Another update operation is currently running"],
            )

        if server_types is None:
            server_types = list(ServerType)

        self._update_running = True
        start_time = time.time()

        # Open the update log entry in its own transaction so other
        # readers can observe that work has started.
        async with self._uow as uow:
            update_log = await uow.versions.create_update_log(
                CreateUpdateLogCommand(
                    update_type="manual" if user_id else "automatic",
                    status="running",
                    executed_by_user_id=user_id,
                )
            )
            await uow.commit()

        total_added = 0
        total_updated = 0
        total_removed = 0
        total_api_calls = 0
        errors: List[str] = []

        try:
            logger.info(
                f"Starting version update for types: {[t.value for t in server_types]}"
            )

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

            execution_time_ms = int((time.time() - start_time) * 1000)

            status = (
                "success"
                if not errors
                else "partial_success"
                if total_added + total_updated > 0
                else "failed"
            )

            # Finalise the log: status + counts in one transaction so no
            # observer sees status="success" with counts still at 0.
            async with self._uow as uow:
                await uow.versions.complete_update_log(
                    update_log.id,
                    status=status,
                    execution_time_ms=execution_time_ms,
                    error_message="; ".join(errors) if errors else None,
                    versions_added=total_added,
                    versions_updated=total_updated,
                    versions_removed=total_removed,
                    external_api_calls=total_api_calls,
                )
                await uow.commit()

            self._last_update_time = utcnow()

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

            async with self._uow as uow:
                await uow.versions.complete_update_log(
                    update_log.id,
                    status="failed",
                    execution_time_ms=execution_time_ms,
                    error_message=error_msg,
                    versions_added=total_added,
                    versions_updated=total_updated,
                    versions_removed=total_removed,
                    external_api_calls=total_api_calls,
                )
                await uow.commit()

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
        """Update versions for a specific server type (one transaction)."""
        api_calls_count = 0

        try:
            logger.debug(f"Fetching {server_type.value} versions from external API...")
            external_versions = await minecraft_version_manager.get_supported_versions(
                server_type
            )
            api_calls_count = len(external_versions) + 1

            if not external_versions:
                logger.warning(f"No versions received for {server_type.value}")
                return {
                    "added": 0,
                    "updated": 0,
                    "removed": 0,
                    "api_calls": api_calls_count,
                }

            async with self._uow as uow:
                current_versions = await uow.versions.get_versions_by_type(server_type)
                current_version_map = {v.version: v for v in current_versions}

                added_count = 0
                updated_count = 0

                external_version_ids: set[str] = set()
                for ext_version in external_versions:
                    external_version_ids.add(ext_version.version)

                    command = CreateVersionCommand(
                        server_type=ext_version.server_type,
                        version=ext_version.version,
                        download_url=ext_version.download_url,
                        release_date=ext_version.release_date,
                        is_stable=ext_version.is_stable,
                        build_number=ext_version.build_number,
                    )

                    if ext_version.version in current_version_map:
                        current = current_version_map[ext_version.version]
                        needs_update = (
                            current.download_url != ext_version.download_url
                            or current.is_stable != ext_version.is_stable
                            or current.build_number != ext_version.build_number
                            or not current.is_active
                        )

                        if needs_update:
                            await uow.versions.upsert_version(command)
                            updated_count += 1
                            logger.debug(
                                f"Updated {server_type.value} {ext_version.version}"
                            )
                    else:
                        await uow.versions.upsert_version(command)
                        added_count += 1
                        logger.debug(f"Added {server_type.value} {ext_version.version}")

                all_current = [v.version for v in current_versions if v.is_active]
                to_deactivate = [
                    v_id for v_id in all_current if v_id not in external_version_ids
                ]

                removed_count = 0
                if to_deactivate:
                    removed_count = await uow.versions.deactivate_versions(
                        server_type, list(external_version_ids)
                    )
                    logger.debug(
                        f"Deactivated {removed_count} {server_type.value} versions: "
                        f"{to_deactivate}"
                    )

                await uow.commit()

            return {
                "added": added_count,
                "updated": updated_count,
                "removed": removed_count,
                "api_calls": api_calls_count,
            }

        except Exception as e:
            logger.error(f"Error updating {server_type.value} versions: {e}")
            raise

    # ----- Query use cases -----

    async def get_update_status(self) -> UpdateStatus:
        async with self._uow as uow:
            latest_log = await uow.versions.get_latest_update_log()
            stats = await uow.versions.get_version_stats()
        return UpdateStatus(
            last_update=latest_log,
            total_versions=stats.active_versions,
            versions_by_type={k: v["active"] for k, v in stats.by_server_type.items()},
            next_scheduled_update=None,
            is_update_running=self._update_running,
        )

    async def cleanup_old_versions(self, days_old: int = 30) -> int:
        async with self._uow as uow:
            removed = await uow.versions.cleanup_old_versions(days_old)
            await uow.commit()
        if removed > 0:
            logger.info(f"Cleaned up {removed} old inactive versions (>{days_old} days)")
        return removed

    async def get_supported_versions(
        self, server_type: ServerType
    ) -> List[MinecraftVersionEntity]:
        async with self._uow as uow:
            return await uow.versions.get_versions_by_type(server_type)

    async def get_all_supported_versions(self) -> List[MinecraftVersionEntity]:
        async with self._uow as uow:
            return await uow.versions.get_all_active_versions()

    async def get_version(
        self, server_type: ServerType, version: str
    ) -> Optional[MinecraftVersionEntity]:
        async with self._uow as uow:
            return await uow.versions.get_version_by_type_and_version(
                server_type, version
            )

    async def get_download_url(
        self, server_type: ServerType, version: str
    ) -> Optional[str]:
        entity = await self.get_version(server_type, version)
        return entity.download_url if entity else None

    async def get_version_stats(self) -> VersionStatsEntity:
        async with self._uow as uow:
            return await uow.versions.get_version_stats()

    def is_version_supported(self, server_type: ServerType, version: str) -> bool:
        return minecraft_version_manager.is_version_supported(server_type, version)

    @property
    def is_update_running(self) -> bool:
        return self._update_running

    @property
    def last_update_time(self) -> Optional[datetime]:
        return self._last_update_time
