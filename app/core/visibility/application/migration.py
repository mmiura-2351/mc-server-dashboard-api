"""Visibility migration service (Hexagonal layout).

Reimplements `app.services.visibility_migration_service` against the
`VisibilityRepository` + `VisibilityUnitOfWork` Ports. Every method is
async and never touches SQLAlchemy directly; the cross-domain SELECTs
that detect missing visibility rows live inside the adapter.
"""

import logging
from typing import Any, Dict

from app.core.visibility.domain.entities import SetVisibilityCommand
from app.core.visibility.domain.ports import VisibilityUnitOfWork
from app.core.visibility.models import ResourceType, VisibilityType

logger = logging.getLogger(__name__)


class VisibilityMigrationService:
    """Application service for the Phase 1 -> Phase 2 visibility migration."""

    def __init__(self, uow: VisibilityUnitOfWork):
        self._uow = uow

    async def migrate_all_resources(self) -> Dict[str, int]:
        """Migrate all servers / groups missing a visibility row to `PUBLIC`.

        Mirrors the legacy `migrate_all_resources` return shape:
        ``{"servers": int, "groups": int, "total": int}``.
        """
        logger.info("Starting Phase 1 → Phase 2 visibility migration")

        async with self._uow as uow:
            server_ids = await uow.visibility.list_missing_server_ids()
            group_ids = await uow.visibility.list_missing_group_ids()

            server_count = await uow.visibility.add_many_public(
                ResourceType.SERVER, server_ids
            )
            group_count = await uow.visibility.add_many_public(
                ResourceType.GROUP, group_ids
            )
            total = server_count + group_count
            if total > 0:
                await uow.commit()

        if total > 0:
            logger.info(
                f"Completed visibility migration: {server_count} servers, "
                f"{group_count} groups, {total} total resources"
            )
        else:
            logger.info(
                "No resources needed migration - all resources already have "
                "visibility configuration"
            )

        return {"servers": server_count, "groups": group_count, "total": total}

    async def verify_migration_completeness(self) -> Dict[str, Any]:
        """Verify that every resource has a visibility row."""
        verification: Dict[str, Any] = {
            "complete": True,
            "issues": [],
            "stats": {},
        }
        async with self._uow as uow:
            total_servers = await uow.visibility.count_resources(ResourceType.SERVER)
            servers_with = await uow.visibility.count_visibility(ResourceType.SERVER)
            total_groups = await uow.visibility.count_resources(ResourceType.GROUP)
            groups_with = await uow.visibility.count_visibility(ResourceType.GROUP)

        verification["stats"]["servers"] = {
            "total": total_servers,
            "with_visibility": servers_with,
            "missing": total_servers - servers_with,
        }
        if total_servers != servers_with:
            verification["complete"] = False
            verification["issues"].append(
                f"{total_servers - servers_with} servers missing visibility configuration"
            )

        verification["stats"]["groups"] = {
            "total": total_groups,
            "with_visibility": groups_with,
            "missing": total_groups - groups_with,
        }
        if total_groups != groups_with:
            verification["complete"] = False
            verification["issues"].append(
                f"{total_groups - groups_with} groups missing visibility configuration"
            )

        return verification

    async def set_default_visibility_for_new_resource(
        self,
        resource_type: ResourceType,
        resource_id: int,
        default_visibility: VisibilityType = VisibilityType.PRIVATE,
    ):
        """Set default visibility for a newly created resource.

        Idempotent: if a visibility row already exists it is returned
        unchanged.
        """
        async with self._uow as uow:
            existing = await uow.visibility.get(resource_type, resource_id)
            if existing is not None:
                logger.debug(
                    f"Visibility already exists for {resource_type.value} {resource_id}"
                )
                return existing
            entity = await uow.visibility.set(
                SetVisibilityCommand(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    visibility_type=default_visibility,
                    role_restriction=None,
                )
            )
            await uow.commit()
        logger.info(
            f"Created default {default_visibility.value} visibility for "
            f"{resource_type.value} {resource_id}"
        )
        return entity

    async def get_migration_status(self) -> Dict[str, Any]:
        """Return the full migration status payload (legacy-compatible)."""
        verification = await self.verify_migration_completeness()
        async with self._uow as uow:
            distribution = await uow.visibility.count_by_visibility_type()
        visibility_distribution: Dict[str, Dict[str, int]] = {}
        for resource_type, type_counts in distribution.items():
            inner = {vt.value: count for vt, count in type_counts.items() if count > 0}
            if inner:
                visibility_distribution[resource_type.value] = inner
        return {
            "migration_complete": verification["complete"],
            "issues": verification["issues"],
            "resource_stats": verification["stats"],
            "visibility_distribution": visibility_distribution,
        }


__all__ = ["VisibilityMigrationService"]
