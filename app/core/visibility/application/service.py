"""Application service for resource visibility (Hexagonal layout).

Reimplements `app.services.visibility_service.VisibilityService` against
the `VisibilityRepository` + `VisibilityUnitOfWork` Ports. Every method
is async, matches the legacy public surface, and never touches
SQLAlchemy or FastAPI directly — failure modes are reported via the
domain exceptions in `app.core.visibility.domain.exceptions`.

Behavioural-parity notes:

- `set_resource_visibility`: the legacy code cleared `SPECIFIC_USERS`
  grants when changing away from that visibility type. The repository's
  `set` method does the same eagerly inside the adapter, so the service
  no longer needs to coordinate that step.
- `grant_user_access` / `revoke_user_access`: legacy code raised
  `HTTPException` directly from inside the service. The new service
  raises pure-domain exceptions (`VisibilityNotFoundError`,
  `InvalidVisibilityTypeError`, `DuplicateGrantError`) and the API
  router translates them into HTTP responses.
"""

import logging
from typing import List, Optional, Tuple

from app.core.visibility.domain.entities import (
    GrantAccessCommand,
    ResourceUserAccessEntity,
    ResourceVisibilityEntity,
    SetVisibilityCommand,
)
from app.core.visibility.domain.ports import VisibilityUnitOfWork
from app.core.visibility.models import ResourceType, VisibilityType
from app.users.domain.value_objects import Role
from app.users.models import User

logger = logging.getLogger(__name__)


class VisibilityService:
    """Application service for resource visibility and access control."""

    def __init__(self, uow: VisibilityUnitOfWork):
        self._uow = uow

    # -----------------------------------------------------------------
    # Access checks
    # -----------------------------------------------------------------

    async def check_resource_access(
        self,
        user: User,
        resource_type: ResourceType,
        resource_id: int,
        resource_owner_id: Optional[int] = None,
    ) -> bool:
        """Check whether `user` can access the given resource.

        Access hierarchy (matches legacy):
        1. Admins always have access.
        2. Resource owners always have access.
        3. Otherwise, the visibility row decides.
        """
        if user.role == Role.admin:
            logger.debug(
                f"Admin user {user.id} granted access to "
                f"{resource_type.value} {resource_id}"
            )
            return True
        if resource_owner_id is not None and user.id == resource_owner_id:
            logger.debug(
                f"Owner user {user.id} granted access to "
                f"{resource_type.value} {resource_id}"
            )
            return True

        async with self._uow as uow:
            visibility = await uow.visibility.get(resource_type, resource_id)
        if visibility is None:
            logger.debug(
                f"No visibility config for {resource_type.value} "
                f"{resource_id}, defaulting to private"
            )
            return False

        access_granted = self._check_visibility_access(user, visibility)
        visibility_type_str = getattr(
            visibility.visibility_type, "value", str(visibility.visibility_type)
        )
        logger.debug(
            f"User {user.id} {'granted' if access_granted else 'denied'} access "
            f"to {resource_type.value} {resource_id} "
            f"(visibility: {visibility_type_str})"
        )
        return access_granted

    def _check_visibility_access(
        self, user: User, visibility: ResourceVisibilityEntity
    ) -> bool:
        if visibility.visibility_type == VisibilityType.PUBLIC:
            return True
        if visibility.visibility_type == VisibilityType.PRIVATE:
            return False
        if visibility.visibility_type == VisibilityType.ROLE_BASED:
            return self._check_role_based_access(user, visibility)
        if visibility.visibility_type == VisibilityType.SPECIFIC_USERS:
            return visibility.has_user_access(user.id)
        logger.warning(f"Unknown visibility type: {visibility.visibility_type}")
        return False

    def _check_role_based_access(
        self, user: User, visibility: ResourceVisibilityEntity
    ) -> bool:
        if not visibility.role_restriction:
            return True
        role_hierarchy = {Role.user: 1, Role.operator: 2, Role.admin: 3}
        user_level = role_hierarchy.get(user.role, 0)
        required_level = role_hierarchy.get(visibility.role_restriction, 0)
        return user_level >= required_level

    async def filter_resources_by_visibility(
        self,
        user: User,
        resources: List[Tuple[int, int]],
        resource_type: ResourceType,
    ) -> List[int]:
        """Return the subset of resource ids the user can access."""
        accessible_ids: List[int] = []
        for resource_id, owner_id in resources:
            if await self.check_resource_access(
                user, resource_type, resource_id, owner_id
            ):
                accessible_ids.append(resource_id)
        return accessible_ids

    # -----------------------------------------------------------------
    # Mutations
    # -----------------------------------------------------------------

    async def set_resource_visibility(
        self,
        resource_type: ResourceType,
        resource_id: int,
        visibility_type: VisibilityType,
        role_restriction: Optional[Role] = None,
        requesting_user_id: Optional[int] = None,  # noqa: ARG002 (audit-only)
    ) -> ResourceVisibilityEntity:
        """Set or update visibility configuration for a resource.

        Raises `ValueError` if the role + visibility-type combination is
        invalid, matching the legacy contract.
        """
        self._validate_role_configuration(visibility_type, role_restriction)

        async with self._uow as uow:
            existing = await uow.visibility.get(resource_type, resource_id)
            entity = await uow.visibility.set(
                SetVisibilityCommand(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    visibility_type=visibility_type,
                    role_restriction=role_restriction,
                )
            )
            await uow.commit()

        if existing is not None:
            logger.info(
                f"Updated visibility for {resource_type.value} {resource_id} "
                f"from {existing.visibility_type.value} to "
                f"{visibility_type.value}"
            )
            if (
                existing.visibility_type == VisibilityType.SPECIFIC_USERS
                and visibility_type != VisibilityType.SPECIFIC_USERS
                and existing.granted_users
            ):
                logger.info(
                    f"Cleared specific user access grants for "
                    f"{resource_type.value} {resource_id}"
                )
        else:
            logger.info(
                f"Created visibility config for {resource_type.value} "
                f"{resource_id} with type {visibility_type.value}"
            )
        return entity

    async def grant_user_access(
        self,
        resource_type: ResourceType,
        resource_id: int,
        user_id: int,
        granted_by_user_id: int,
    ) -> ResourceUserAccessEntity:
        """Grant specific user access to a resource.

        Raises `VisibilityNotFoundError`, `InvalidVisibilityTypeError`,
        or `DuplicateGrantError` from the domain layer.
        """
        async with self._uow as uow:
            entity = await uow.visibility.grant_access(
                GrantAccessCommand(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    user_id=user_id,
                    granted_by_user_id=granted_by_user_id,
                )
            )
            await uow.commit()
        logger.info(
            f"Granted user {user_id} access to {resource_type.value} "
            f"{resource_id} by user {granted_by_user_id}"
        )
        return entity

    async def revoke_user_access(
        self, resource_type: ResourceType, resource_id: int, user_id: int
    ) -> bool:
        """Revoke specific user access from a resource."""
        async with self._uow as uow:
            revoked = await uow.visibility.revoke_access(
                resource_type, resource_id, user_id
            )
            if revoked:
                await uow.commit()
        if revoked:
            logger.info(
                f"Revoked user {user_id} access to {resource_type.value} {resource_id}"
            )
        return revoked

    # -----------------------------------------------------------------
    # Read helpers
    # -----------------------------------------------------------------

    async def get_resource_visibility_info(
        self, resource_type: ResourceType, resource_id: int
    ) -> Optional[dict]:
        """Return a dict shaped exactly like the legacy method's output."""
        async with self._uow as uow:
            visibility = await uow.visibility.get(resource_type, resource_id)
        if visibility is None:
            return None
        info: dict = {
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
                for grant in visibility.granted_users
            ]
        return info

    async def migrate_existing_resources_to_public(
        self, resource_type: ResourceType, resource_list: List[int]
    ) -> int:
        """Migrate ids without a visibility config to `PUBLIC`."""
        async with self._uow as uow:
            missing: List[int] = []
            for resource_id in resource_list:
                if await uow.visibility.get(resource_type, resource_id) is None:
                    missing.append(resource_id)
            migrated_count = await uow.visibility.add_many_public(resource_type, missing)
            if migrated_count > 0:
                await uow.commit()
        if migrated_count > 0:
            logger.info(
                f"Migrated {migrated_count} {resource_type.value} "
                f"resources to PUBLIC visibility"
            )
        return migrated_count

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    def _validate_role_configuration(
        self, visibility_type: VisibilityType, role_restriction: Optional[Role]
    ) -> None:
        """Validate role hierarchy + visibility-type consistency.

        Raises `ValueError` for an illegal combination, matching legacy.
        """
        if visibility_type == VisibilityType.ROLE_BASED:
            if role_restriction is None:
                logger.warning(
                    "ROLE_BASED visibility without role_restriction defaults "
                    "to all authenticated users"
                )
                return
            role_hierarchy = {Role.user: 1, Role.operator: 2, Role.admin: 3}
            if role_restriction not in role_hierarchy:
                raise ValueError(f"Invalid role restriction: {role_restriction}")
            logger.info(
                f"Setting ROLE_BASED visibility with "
                f"{role_restriction.value} role restriction"
            )
            return

        if role_restriction is None:
            return
        if visibility_type == VisibilityType.PRIVATE:
            raise ValueError("PRIVATE visibility cannot have role restrictions")
        if visibility_type == VisibilityType.PUBLIC:
            raise ValueError("PUBLIC visibility cannot have role restrictions")
        if visibility_type == VisibilityType.SPECIFIC_USERS:
            raise ValueError("SPECIFIC_USERS visibility cannot have role restrictions")
        raise ValueError(
            f"role_restriction can only be used with ROLE_BASED visibility, "
            f"not with {visibility_type.value}"
        )


__all__ = ["VisibilityService"]
