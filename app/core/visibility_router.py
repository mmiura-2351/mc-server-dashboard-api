"""
Resource Visibility Management API Router

Phase 2 API endpoints for managing resource visibility and access control.
Provides comprehensive visibility management functionality.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_active_user
from app.core.database import get_db
from app.core.visibility import ResourceType, VisibilityType
from app.core.visibility_schemas import (
    MigrationExecuteResponse,
    MigrationStatusResponse,
    UserAccessGrantRequest,
    VisibilityInfoResponse,
    VisibilityUpdateRequest,
)
from app.groups.models import Group
from app.servers.models import Server
from app.services.visibility_migration_service import VisibilityMigrationService
from app.services.visibility_service import VisibilityService
from app.users.models import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visibility", tags=["visibility"])


def _check_resource_ownership_or_admin(
    user: User, resource_type: ResourceType, resource_id: int, db: Session
) -> bool:
    """
    Check if user owns the resource or is an admin

    Args:
        user: User making the request
        resource_type: Type of resource
        resource_id: ID of the resource
        db: Database session

    Returns:
        bool: True if user has permission to modify visibility

    Raises:
        HTTPException: If resource not found or user lacks permission
    """
    if user.role == Role.admin:
        return True

    # Check ownership based on resource type
    if resource_type == ResourceType.SERVER:
        server = db.query(Server).filter(Server.id == resource_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )
        return server.owner_id == user.id

    elif resource_type == ResourceType.GROUP:
        group = db.query(Group).filter(Group.id == resource_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
            )
        return group.owner_id == user.id

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported resource type: {resource_type.value}",
        )


@router.get(
    "/{resource_type}/{resource_id}",
    response_model=VisibilityInfoResponse,
    summary="Get Resource Visibility",
    description="Get detailed visibility information for a specific resource",
)
async def get_resource_visibility(
    resource_type: ResourceType,
    resource_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get visibility configuration for a resource

    - **resource_type**: Type of resource (server, group)
    - **resource_id**: ID of the resource

    Returns detailed visibility information including granted users for specific_users visibility.
    """
    try:
        # Check if user has permission to view visibility settings
        # (owners and admins can view, others get filtered results through regular access)
        can_view_settings = _check_resource_ownership_or_admin(
            current_user, resource_type, resource_id, db
        )

        if not can_view_settings:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only resource owners and admins can view visibility settings",
            )

        visibility_service = VisibilityService(db)
        visibility_info = visibility_service.get_resource_visibility_info(
            resource_type, resource_id
        )

        if not visibility_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visibility configuration not found",
            )

        # Convert to response model
        response_data = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            **visibility_info,
        }

        return VisibilityInfoResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting visibility for {resource_type.value} {resource_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get resource visibility",
        )


@router.put(
    "/{resource_type}/{resource_id}",
    response_model=VisibilityInfoResponse,
    summary="Update Resource Visibility",
    description="Update visibility settings for a resource (owners and admins only)",
)
async def update_resource_visibility(
    resource_type: ResourceType,
    resource_id: int,
    request: VisibilityUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update visibility configuration for a resource

    - **resource_type**: Type of resource (server, group)
    - **resource_id**: ID of the resource
    - **visibility_type**: New visibility type
    - **role_restriction**: Role restriction (required for role_based visibility)

    Only resource owners and admins can modify visibility settings.
    """
    try:
        # Check ownership or admin status
        can_modify = _check_resource_ownership_or_admin(
            current_user, resource_type, resource_id, db
        )

        if not can_modify:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only resource owners and admins can modify visibility settings",
            )

        # Validate role_restriction for role_based visibility
        if (
            request.visibility_type == VisibilityType.ROLE_BASED
            and not request.role_restriction
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="role_restriction is required for role_based visibility",
            )

        if (
            request.visibility_type != VisibilityType.ROLE_BASED
            and request.role_restriction
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="role_restriction should only be specified for role_based visibility",
            )

        # Update visibility
        visibility_service = VisibilityService(db)
        visibility_service.set_resource_visibility(
            resource_type=resource_type,
            resource_id=resource_id,
            visibility_type=request.visibility_type,
            role_restriction=request.role_restriction,
            requesting_user_id=current_user.id,
        )

        # Get updated visibility info
        visibility_info = visibility_service.get_resource_visibility_info(
            resource_type, resource_id
        )

        response_data = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            **visibility_info,
        }

        logger.info(
            f"User {current_user.id} updated visibility for {resource_type.value} {resource_id} "
            f"to {request.visibility_type.value}"
        )

        return VisibilityInfoResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error updating visibility for {resource_type.value} {resource_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update resource visibility",
        )


@router.post(
    "/{resource_type}/{resource_id}/grant-access",
    summary="Grant User Access",
    description="Grant specific user access to a resource (for specific_users visibility)",
)
async def grant_user_access(
    resource_type: ResourceType,
    resource_id: int,
    request: UserAccessGrantRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Grant specific user access to a resource

    - **resource_type**: Type of resource (server, group)
    - **resource_id**: ID of the resource
    - **user_id**: ID of user to grant access to

    Only works for resources with SPECIFIC_USERS visibility.
    Only resource owners and admins can grant access.
    """
    try:
        # Check ownership or admin status
        can_modify = _check_resource_ownership_or_admin(
            current_user, resource_type, resource_id, db
        )

        if not can_modify:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only resource owners and admins can grant access",
            )

        # Verify target user exists
        target_user = db.query(User).filter(User.id == request.user_id).first()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found"
            )

        # Grant access
        visibility_service = VisibilityService(db)
        visibility_service.grant_user_access(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=request.user_id,
            granted_by_user_id=current_user.id,
        )

        logger.info(
            f"User {current_user.id} granted access to {resource_type.value} {resource_id} "
            f"for user {request.user_id}"
        )

        return {
            "success": True,
            "message": f"Access granted to user {request.user_id}",
            "user_id": request.user_id,
            "granted_by_user_id": current_user.id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error granting access to {resource_type.value} {resource_id} "
            f"for user {request.user_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to grant user access",
        )


@router.delete(
    "/{resource_type}/{resource_id}/revoke-access/{user_id}",
    summary="Revoke User Access",
    description="Revoke specific user access from a resource",
)
async def revoke_user_access(
    resource_type: ResourceType,
    resource_id: int,
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Revoke specific user access from a resource

    - **resource_type**: Type of resource (server, group)
    - **resource_id**: ID of the resource
    - **user_id**: ID of user to revoke access from

    Only resource owners and admins can revoke access.
    """
    try:
        # Check ownership or admin status
        can_modify = _check_resource_ownership_or_admin(
            current_user, resource_type, resource_id, db
        )

        if not can_modify:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only resource owners and admins can revoke access",
            )

        # Revoke access
        visibility_service = VisibilityService(db)
        revoked = visibility_service.revoke_user_access(
            resource_type=resource_type, resource_id=resource_id, user_id=user_id
        )

        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User access not found"
            )

        logger.info(
            f"User {current_user.id} revoked access to {resource_type.value} {resource_id} "
            f"from user {user_id}"
        )

        return {
            "success": True,
            "message": f"Access revoked from user {user_id}",
            "user_id": user_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error revoking access to {resource_type.value} {resource_id} "
            f"from user {user_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke user access",
        )


@router.get(
    "/migration/status",
    response_model=MigrationStatusResponse,
    summary="Get Migration Status",
    description="Get status of Phase 1 → Phase 2 visibility migration (admin only)",
)
async def get_migration_status(
    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
):
    """
    Get migration status information

    Shows:
    - Whether migration is complete
    - Resource statistics
    - Visibility type distribution
    - Any issues found

    Admin access required.
    """
    if current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view migration status",
        )

    try:
        migration_service = VisibilityMigrationService(db)
        status_info = migration_service.get_migration_status()

        return MigrationStatusResponse(**status_info)

    except Exception as e:
        logger.error(f"Error getting migration status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get migration status",
        )


@router.post(
    "/migration/execute",
    response_model=MigrationExecuteResponse,
    summary="Execute Migration",
    description="Execute Phase 1 → Phase 2 visibility migration (admin only)",
)
async def execute_migration(
    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)
):
    """
    Execute the visibility migration

    Migrates all existing resources to use the Phase 2 visibility system.
    Sets existing resources to PUBLIC visibility to maintain Phase 1 behavior.

    Admin access required.
    """
    if current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can execute migration",
        )

    try:
        migration_service = VisibilityMigrationService(db)
        migration_counts = migration_service.migrate_all_resources()

        logger.info(
            f"Admin {current_user.id} executed visibility migration: "
            f"{migration_counts['total']} resources migrated"
        )

        return MigrationExecuteResponse(
            success=True,
            message="Migration completed successfully",
            migration_counts=migration_counts,
        )

    except Exception as e:
        logger.error(f"Error executing migration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute migration",
        )


# Export router
__all__ = ["router"]
