"""
Visibility Migration Service

Handles migration from Phase 1 (shared access) to Phase 2 (visibility-based access control).
Ensures backward compatibility by setting appropriate default visibility for existing resources.
"""

import logging
from typing import Dict

from sqlalchemy.orm import Session

from app.core.visibility import ResourceType, ResourceVisibility, VisibilityType
from app.groups.models import Group
from app.servers.models import Server

logger = logging.getLogger(__name__)


class VisibilityMigrationService:
    """
    Service for migrating existing resources to use the Phase 2 visibility system

    Handles:
    - Setting default visibility for existing servers and groups
    - Ensuring no resources are left without visibility configuration
    - Maintaining backward compatibility with Phase 1 behavior
    """

    def __init__(self, db: Session):
        self.db = db

    def migrate_all_resources(self) -> Dict[str, int]:
        """
        Migrate all existing resources to use visibility system

        Sets existing resources to PUBLIC visibility to maintain Phase 1 behavior
        where all users could see all resources.

        Returns:
            Dict with migration counts for each resource type
        """
        logger.info("Starting Phase 1 → Phase 2 visibility migration")

        migration_counts = {"servers": 0, "groups": 0, "total": 0}

        # Migrate servers
        server_count = self._migrate_servers()
        migration_counts["servers"] = server_count

        # Migrate groups
        group_count = self._migrate_groups()
        migration_counts["groups"] = group_count

        migration_counts["total"] = server_count + group_count

        if migration_counts["total"] > 0:
            self.db.commit()
            logger.info(
                f"Completed visibility migration: {migration_counts['servers']} servers, "
                f"{migration_counts['groups']} groups, {migration_counts['total']} total resources"
            )
        else:
            logger.info(
                "No resources needed migration - all resources already have visibility configuration"
            )

        return migration_counts

    def _migrate_servers(self) -> int:
        """
        Migrate servers to visibility system

        Returns:
            Number of servers migrated
        """
        # Get all servers that don't have visibility configuration
        existing_server_visibility_ids = (
            self.db.query(ResourceVisibility.resource_id)
            .filter(ResourceVisibility.resource_type == ResourceType.SERVER)
            .subquery()
        )

        servers_without_visibility = (
            self.db.query(Server)
            .filter(~Server.id.in_(existing_server_visibility_ids))
            .all()
        )

        if not servers_without_visibility:
            logger.debug("All servers already have visibility configuration")
            return 0

        # Create PUBLIC visibility for all servers (maintains Phase 1 behavior)
        visibility_configs = []
        for server in servers_without_visibility:
            visibility = ResourceVisibility(
                resource_type=ResourceType.SERVER,
                resource_id=server.id,
                visibility_type=VisibilityType.PUBLIC,
                role_restriction=None,
            )
            visibility_configs.append(visibility)

        self.db.add_all(visibility_configs)

        logger.info(
            f"Migrating {len(servers_without_visibility)} servers to PUBLIC visibility"
        )
        return len(servers_without_visibility)

    def _migrate_groups(self) -> int:
        """
        Migrate groups to visibility system

        Returns:
            Number of groups migrated
        """
        # Get all groups that don't have visibility configuration
        existing_group_visibility_ids = (
            self.db.query(ResourceVisibility.resource_id)
            .filter(ResourceVisibility.resource_type == ResourceType.GROUP)
            .subquery()
        )

        groups_without_visibility = (
            self.db.query(Group)
            .filter(~Group.id.in_(existing_group_visibility_ids))
            .all()
        )

        if not groups_without_visibility:
            logger.debug("All groups already have visibility configuration")
            return 0

        # Create PUBLIC visibility for all groups (maintains Phase 1 behavior)
        visibility_configs = []
        for group in groups_without_visibility:
            visibility = ResourceVisibility(
                resource_type=ResourceType.GROUP,
                resource_id=group.id,
                visibility_type=VisibilityType.PUBLIC,
                role_restriction=None,
            )
            visibility_configs.append(visibility)

        self.db.add_all(visibility_configs)

        logger.info(
            f"Migrating {len(groups_without_visibility)} groups to PUBLIC visibility"
        )
        return len(groups_without_visibility)

    def verify_migration_completeness(self) -> Dict[str, any]:
        """
        Verify that all resources have visibility configuration

        Returns:
            Dict with verification results
        """
        verification = {"complete": True, "issues": [], "stats": {}}

        # Check servers
        total_servers = self.db.query(Server).count()
        servers_with_visibility = (
            self.db.query(ResourceVisibility)
            .filter(ResourceVisibility.resource_type == ResourceType.SERVER)
            .count()
        )

        verification["stats"]["servers"] = {
            "total": total_servers,
            "with_visibility": servers_with_visibility,
            "missing": total_servers - servers_with_visibility,
        }

        if total_servers != servers_with_visibility:
            verification["complete"] = False
            verification["issues"].append(
                f"{total_servers - servers_with_visibility} servers missing visibility configuration"
            )

        # Check groups
        total_groups = self.db.query(Group).count()
        groups_with_visibility = (
            self.db.query(ResourceVisibility)
            .filter(ResourceVisibility.resource_type == ResourceType.GROUP)
            .count()
        )

        verification["stats"]["groups"] = {
            "total": total_groups,
            "with_visibility": groups_with_visibility,
            "missing": total_groups - groups_with_visibility,
        }

        if total_groups != groups_with_visibility:
            verification["complete"] = False
            verification["issues"].append(
                f"{total_groups - groups_with_visibility} groups missing visibility configuration"
            )

        return verification

    def set_default_visibility_for_new_resource(
        self,
        resource_type: ResourceType,
        resource_id: int,
        default_visibility: VisibilityType = VisibilityType.PRIVATE,
    ) -> ResourceVisibility:
        """
        Set default visibility for a newly created resource

        Args:
            resource_type: Type of resource
            resource_id: ID of the resource
            default_visibility: Default visibility type (PRIVATE for security)

        Returns:
            Created ResourceVisibility instance
        """
        # Check if visibility already exists
        existing = (
            self.db.query(ResourceVisibility)
            .filter(
                ResourceVisibility.resource_type == resource_type,
                ResourceVisibility.resource_id == resource_id,
            )
            .first()
        )

        if existing:
            logger.debug(
                f"Visibility already exists for {resource_type.value} {resource_id}"
            )
            return existing

        # Create default visibility
        visibility = ResourceVisibility(
            resource_type=resource_type,
            resource_id=resource_id,
            visibility_type=default_visibility,
            role_restriction=None,
        )

        self.db.add(visibility)
        self.db.commit()
        self.db.refresh(visibility)

        logger.info(
            f"Created default {default_visibility.value} visibility for "
            f"{resource_type.value} {resource_id}"
        )

        return visibility

    def get_migration_status(self) -> Dict[str, any]:
        """
        Get current migration status and statistics

        Returns:
            Dict with migration status information
        """
        verification = self.verify_migration_completeness()

        # Get visibility type distribution
        visibility_distribution = {}
        for resource_type in ResourceType:
            type_distribution = {}
            for visibility_type in VisibilityType:
                count = (
                    self.db.query(ResourceVisibility)
                    .filter(
                        ResourceVisibility.resource_type == resource_type,
                        ResourceVisibility.visibility_type == visibility_type,
                    )
                    .count()
                )
                if count > 0:
                    type_distribution[visibility_type.value] = count

            if type_distribution:
                visibility_distribution[resource_type.value] = type_distribution

        return {
            "migration_complete": verification["complete"],
            "issues": verification["issues"],
            "resource_stats": verification["stats"],
            "visibility_distribution": visibility_distribution,
        }


# Export service class
__all__ = ["VisibilityMigrationService"]
