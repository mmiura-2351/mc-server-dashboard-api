"""
Resource Visibility Service

Phase 2 implementation service for managing resource visibility and access control.
Provides comprehensive visibility management with multiple access patterns.
"""

import logging
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.visibility import (
    ResourceType,
    ResourceUserAccess,
    ResourceVisibility,
    VisibilityType,
)
from app.users.models import Role, User

logger = logging.getLogger(__name__)


class VisibilityService:
    """
    Service for managing resource visibility and access control

    Provides methods to:
    - Check resource access based on visibility settings
    - Manage visibility configurations
    - Grant/revoke specific user access
    - Handle visibility migrations
    """

    def __init__(self, db: Session):
        self.db = db

    def check_resource_access(
        self,
        user: User,
        resource_type: ResourceType,
        resource_id: int,
        resource_owner_id: Optional[int] = None,
    ) -> bool:
        """
        Check if a user has access to a specific resource based on visibility settings

        Access hierarchy:
        1. Admins always have access
        2. Resource owners always have access
        3. Visibility-based access (private, public, role_based, specific_users)

        Args:
            user: The user requesting access
            resource_type: Type of resource (server, group, etc.)
            resource_id: ID of the specific resource
            resource_owner_id: ID of the resource owner (for owner check)

        Returns:
            bool: True if user has access, False otherwise
        """
        # Admin override - admins can always access everything
        if user.role == Role.admin:
            logger.debug(
                f"Admin user {user.id} granted access to {resource_type.value} {resource_id}"
            )
            return True

        # Owner override - owners can always access their resources
        if resource_owner_id and user.id == resource_owner_id:
            logger.debug(
                f"Owner user {user.id} granted access to {resource_type.value} {resource_id}"
            )
            return True

        # Get visibility configuration
        visibility = self._get_resource_visibility(resource_type, resource_id)
        if not visibility:
            # No visibility config found - default to private (secure default)
            logger.debug(
                f"No visibility config for {resource_type.value} {resource_id}, defaulting to private"
            )
            return False

        # Check access based on visibility type
        access_granted = self._check_visibility_access(user, visibility)

        visibility_type_str = getattr(
            visibility.visibility_type, "value", str(visibility.visibility_type)
        )
        logger.debug(
            f"User {user.id} {'granted' if access_granted else 'denied'} access to "
            f"{resource_type.value} {resource_id} (visibility: {visibility_type_str})"
        )

        return access_granted

    def _get_resource_visibility(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[ResourceVisibility]:
        """Get visibility configuration for a resource"""
        return (
            self.db.query(ResourceVisibility)
            .filter(
                ResourceVisibility.resource_type == resource_type,
                ResourceVisibility.resource_id == resource_id,
            )
            .first()
        )

    def _check_visibility_access(
        self, user: User, visibility: ResourceVisibility
    ) -> bool:
        """Check access based on visibility configuration"""
        if visibility.visibility_type == VisibilityType.PUBLIC:
            return True

        elif visibility.visibility_type == VisibilityType.PRIVATE:
            return False  # Only admins and owners have access (already checked)

        elif visibility.visibility_type == VisibilityType.ROLE_BASED:
            return self._check_role_based_access(user, visibility)

        elif visibility.visibility_type == VisibilityType.SPECIFIC_USERS:
            return visibility.has_user_access(user.id)

        else:
            logger.warning(f"Unknown visibility type: {visibility.visibility_type}")
            return False

    def _check_role_based_access(
        self, user: User, visibility: ResourceVisibility
    ) -> bool:
        """Check role-based access"""
        if not visibility.role_restriction:
            # No role restriction specified - allow all authenticated users
            return True

        # Check if user's role meets the requirement
        role_hierarchy = {Role.user: 1, Role.operator: 2, Role.admin: 3}

        user_level = role_hierarchy.get(user.role, 0)
        required_level = role_hierarchy.get(visibility.role_restriction, 0)

        return user_level >= required_level

    def filter_resources_by_visibility(
        self,
        user: User,
        resources: List[Tuple[int, int]],  # List of (resource_id, owner_id) tuples
        resource_type: ResourceType,
    ) -> List[int]:
        """
        Filter a list of resources based on user's access permissions

        Args:
            user: The user requesting access
            resources: List of (resource_id, owner_id) tuples
            resource_type: Type of resources being filtered

        Returns:
            List of resource IDs the user can access
        """
        accessible_ids = []

        for resource_id, owner_id in resources:
            if self.check_resource_access(user, resource_type, resource_id, owner_id):
                accessible_ids.append(resource_id)

        return accessible_ids

    def set_resource_visibility(
        self,
        resource_type: ResourceType,
        resource_id: int,
        visibility_type: VisibilityType,
        role_restriction: Optional[Role] = None,
        requesting_user_id: Optional[int] = None,
    ) -> ResourceVisibility:
        """
        Set or update visibility configuration for a resource

        Args:
            resource_type: Type of resource
            resource_id: ID of the resource
            visibility_type: New visibility type
            role_restriction: Role restriction for role_based visibility
            requesting_user_id: ID of user making the change (for audit)

        Returns:
            Updated ResourceVisibility instance

        Raises:
            ValueError: If role configuration is invalid
        """
        # Validate role hierarchy and visibility type consistency
        self._validate_role_configuration(visibility_type, role_restriction)

        # Get or create visibility configuration
        visibility = self._get_resource_visibility(resource_type, resource_id)

        if visibility:
            # Update existing configuration
            old_type = visibility.visibility_type
            visibility.visibility_type = visibility_type
            visibility.role_restriction = role_restriction

            logger.info(
                f"Updated visibility for {resource_type.value} {resource_id} "
                f"from {old_type.value} to {visibility_type.value}"
            )
        else:
            # Create new configuration
            visibility = ResourceVisibility(
                resource_type=resource_type,
                resource_id=resource_id,
                visibility_type=visibility_type,
                role_restriction=role_restriction,
            )
            self.db.add(visibility)

            logger.info(
                f"Created visibility config for {resource_type.value} {resource_id} "
                f"with type {visibility_type.value}"
            )

        # Clear specific user access if changing away from SPECIFIC_USERS
        if (
            visibility_type != VisibilityType.SPECIFIC_USERS
            and visibility.user_access_grants
        ):
            for grant in visibility.user_access_grants[
                :
            ]:  # Copy list to avoid mutation issues
                self.db.delete(grant)
            logger.info(
                f"Cleared specific user access grants for {resource_type.value} {resource_id}"
            )

        self.db.commit()
        self.db.refresh(visibility)

        return visibility

    def grant_user_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
        granted_by_user_id: int,
    ) -> ResourceUserAccess:
        """
        Grant specific user access to a resource (for SPECIFIC_USERS visibility)

        Args:
            resource_type: Type of resource
            resource_id: ID of the resource
            user_id: ID of user to grant access to
            granted_by_user_id: ID of user granting access

        Returns:
            ResourceUserAccess instance

        Raises:
            HTTPException: If resource doesn't have SPECIFIC_USERS visibility
        """
        visibility = self._get_resource_visibility(resource_type, resource_id)
        if not visibility:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource visibility configuration not found",
            )

        if visibility.visibility_type != VisibilityType.SPECIFIC_USERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Resource must have SPECIFIC_USERS visibility type",
            )

        # Check if access already granted
        existing_grant = (
            self.db.query(ResourceUserAccess)
            .filter(
                ResourceUserAccess.resource_visibility_id == visibility.id,
                ResourceUserAccess.user_id == user_id,
            )
            .first()
        )

        if existing_grant:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already has access to this resource",
            )

        # Create access grant
        access_grant = ResourceUserAccess(
            resource_visibility_id=visibility.id,
            user_id=user_id,
            granted_by_user_id=granted_by_user_id,
        )

        self.db.add(access_grant)
        self.db.commit()
        self.db.refresh(access_grant)

        logger.info(
            f"Granted user {user_id} access to {resource_type.value} {resource_id} "
            f"by user {granted_by_user_id}"
        )

        return access_grant

    def revoke_user_access(
        self, resource_type: ResourceType, resource_id: int, user_id: int
    ) -> bool:
        """
        Revoke specific user access to a resource

        Args:
            resource_type: Type of resource
            resource_id: ID of the resource
            user_id: ID of user to revoke access from

        Returns:
            bool: True if access was revoked, False if no access found
        """
        visibility = self._get_resource_visibility(resource_type, resource_id)
        if not visibility:
            return False

        access_grant = (
            self.db.query(ResourceUserAccess)
            .filter(
                ResourceUserAccess.resource_visibility_id == visibility.id,
                ResourceUserAccess.user_id == user_id,
            )
            .first()
        )

        if access_grant:
            self.db.delete(access_grant)
            self.db.commit()

            logger.info(
                f"Revoked user {user_id} access to {resource_type.value} {resource_id}"
            )
            return True

        return False

    def get_resource_visibility_info(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[dict]:
        """
        Get comprehensive visibility information for a resource

        Returns:
            dict with visibility details or None if not found
        """
        visibility = self._get_resource_visibility(resource_type, resource_id)
        if not visibility:
            return None

        info = {
            "visibility_type": visibility.visibility_type.value,
            "role_restriction": (
                visibility.role_restriction.value if visibility.role_restriction else None
            ),
            "created_at": visibility.created_at.isoformat(),
            "updated_at": visibility.updated_at.isoformat(),
        }

        if visibility.visibility_type == VisibilityType.SPECIFIC_USERS:
            info["granted_users"] = [
                {
                    "user_id": grant.user_id,
                    "granted_by_user_id": grant.granted_by_user_id,
                    "granted_at": grant.created_at.isoformat(),
                }
                for grant in visibility.user_access_grants
            ]

        return info

    def migrate_existing_resources_to_public(
        self, resource_type: ResourceType, resource_list: List[int]
    ):
        """
        Migrate existing resources to PUBLIC visibility (Phase 1 → Phase 2 transition)

        Args:
            resource_type: Type of resources to migrate
            resource_list: List of resource IDs to migrate
        """
        migrated_count = 0

        for resource_id in resource_list:
            existing_visibility = self._get_resource_visibility(
                resource_type, resource_id
            )

            if not existing_visibility:
                # Create PUBLIC visibility for resources without configuration
                visibility = ResourceVisibility(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    visibility_type=VisibilityType.PUBLIC,
                )
                self.db.add(visibility)
                migrated_count += 1

        if migrated_count > 0:
            self.db.commit()
            logger.info(
                f"Migrated {migrated_count} {resource_type.value} resources to PUBLIC visibility"
            )

        return migrated_count

    def _validate_role_configuration(
        self, visibility_type: VisibilityType, role_restriction: Optional[Role]
    ) -> None:
        """
        Validate role hierarchy and visibility type consistency

        Args:
            visibility_type: The visibility type being set
            role_restriction: The role restriction being applied

        Raises:
            ValueError: If the role configuration is invalid or illogical
        """
        # Validate role_restriction is only used with ROLE_BASED visibility
        if visibility_type == VisibilityType.ROLE_BASED:
            if role_restriction is None:
                logger.warning(
                    "ROLE_BASED visibility without role_restriction defaults to all authenticated users"
                )
            else:
                # Validate the role makes logical sense in hierarchy
                role_hierarchy = {Role.user: 1, Role.operator: 2, Role.admin: 3}

                if role_restriction not in role_hierarchy:
                    raise ValueError(f"Invalid role restriction: {role_restriction}")

                # Log the configuration for audit purposes
                logger.info(
                    f"Setting ROLE_BASED visibility with {role_restriction.value} role restriction"
                )
        else:
            # role_restriction should not be set for other visibility types
            if role_restriction is not None:
                # Provide specific error messages for each visibility type
                if visibility_type == VisibilityType.PRIVATE:
                    raise ValueError("PRIVATE visibility cannot have role restrictions")
                elif visibility_type == VisibilityType.PUBLIC:
                    raise ValueError("PUBLIC visibility cannot have role restrictions")
                elif visibility_type == VisibilityType.SPECIFIC_USERS:
                    raise ValueError(
                        "SPECIFIC_USERS visibility cannot have role restrictions"
                    )
                else:
                    # Generic fallback for any new visibility types
                    raise ValueError(
                        f"role_restriction can only be used with ROLE_BASED visibility, "
                        f"not with {visibility_type.value}"
                    )


# Export service class
__all__ = ["VisibilityService"]
