"""
New fast version endpoints using database instead of external APIs.

These endpoints replace the slow external API calls with database queries,
reducing response time from 4-5 seconds to 10-50ms.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.servers.models import ServerType
from app.users.models import Role, User
from app.versions.repository import VersionRepository
from app.versions.scheduler import version_update_scheduler
from app.versions.schemas import (
    MinecraftVersionResponse,
    VersionStatsResponse,
    VersionUpdateResult,
)

router = APIRouter(tags=["versions"])


@router.get(
    "/supported",
    response_model=List[MinecraftVersionResponse],
    summary="Get all supported versions (fast database query)",
    description="Returns all active Minecraft versions from database. "
    "This endpoint replaces the slow external API calls with a fast database query.",
)
async def get_supported_versions(
    server_type: Optional[ServerType] = Query(None, description="Filter by server type"),
    db: Session = Depends(get_db),
) -> List[MinecraftVersionResponse]:
    """
    Get all supported Minecraft versions from database.

    Fast replacement for the slow external API endpoint.
    Response time: 10-50ms (vs 4-5 seconds for external APIs).

    Args:
        server_type: Optional filter by server type (vanilla, paper, fabric, forge)
        db: Database session

    Returns:
        List of supported Minecraft versions
    """
    try:
        repo = VersionRepository(db)

        if server_type:
            # Get versions for specific server type
            versions = await repo.get_versions_by_type(server_type)
        else:
            # Get all active versions
            versions = await repo.get_all_active_versions()

        # Convert to response model
        return [
            MinecraftVersionResponse(
                id=version.id,
                server_type=version.server_type,
                version=version.version,
                download_url=version.download_url or "",
                release_date=version.release_date,
                is_stable=version.is_stable,
                build_number=version.build_number,
                is_active=version.is_active,
                last_updated=version.updated_at,
                created_at=version.created_at,
                updated_at=version.updated_at,
            )
            for version in versions
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve versions: {str(e)}",
        )


# Admin-only endpoints for version management (defined first to avoid path conflicts)
@router.post(
    "/update",
    response_model=VersionUpdateResult,
    summary="Trigger manual version update (admin only)",
    description="Manually trigger an update of version data from external APIs. Admin only.",
)
async def trigger_version_update(
    server_types: Optional[List[ServerType]] = Query(
        None, description="Server types to update"
    ),
    force_refresh: bool = Query(
        False, description="Force refresh even if recently updated"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VersionUpdateResult:
    """
    Manually trigger version update from external APIs.

    Admin-only endpoint for forcing version updates outside of the
    automatic schedule.

    Args:
        server_types: Optional list of server types to update
        force_refresh: Force refresh even if recently updated
        current_user: Current authenticated user
        db: Database session

    Returns:
        Update result with statistics
    """
    # Only admins can trigger manual updates
    if current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can trigger version updates",
        )

    try:
        # Use the scheduler's immediate update method
        result = await version_update_scheduler.trigger_immediate_update(
            force_refresh=force_refresh
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger version update: {str(e)}",
        )


@router.get(
    "/scheduler/status",
    summary="Get version update scheduler status (admin only)",
    description="Returns status of the background version update scheduler. Admin only.",
)
async def get_scheduler_status(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get status of the version update scheduler.

    Admin-only endpoint for monitoring the background scheduler.

    Args:
        current_user: Current authenticated user

    Returns:
        Scheduler status information
    """
    # Only admins can view scheduler status
    if current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can view scheduler status",
        )

    try:
        return version_update_scheduler.get_status()

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduler status: {str(e)}",
        )


@router.get(
    "/stats",
    response_model=VersionStatsResponse,
    summary="Get version statistics",
    description="Returns comprehensive statistics about available versions by server type.",
)
async def get_version_stats(
    db: Session = Depends(get_db),
) -> VersionStatsResponse:
    """
    Get comprehensive version statistics from database.

    Returns counts and metadata for all server types.

    Args:
        db: Database session

    Returns:
        Version statistics by server type
    """
    try:
        repo = VersionRepository(db)
        stats = await repo.get_version_stats()

        return VersionStatsResponse(
            total_versions=stats["_total"]["total"],
            active_versions=stats["_total"]["active"],
            by_server_type={
                server_type: {
                    "total": data["total"],
                    "active": data["active"],
                }
                for server_type, data in stats.items()
                if server_type != "_total"
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve version statistics: {str(e)}",
        )


@router.get(
    "/{server_type}",
    response_model=List[MinecraftVersionResponse],
    summary="Get versions for specific server type",
    description="Returns all active versions for a specific server type (vanilla, paper, fabric, forge).",
)
async def get_versions_by_server_type(
    server_type: ServerType,
    db: Session = Depends(get_db),
) -> List[MinecraftVersionResponse]:
    """
    Get all versions for a specific server type.

    Fast database query for server-type-specific versions.

    Args:
        server_type: Server type (vanilla, paper, fabric, forge)
        db: Database session

    Returns:
        List of versions for the specified server type
    """
    try:
        repo = VersionRepository(db)
        versions = await repo.get_versions_by_type(server_type)

        return [
            MinecraftVersionResponse(
                id=version.id,
                server_type=version.server_type,
                version=version.version,
                download_url=version.download_url,
                release_date=version.release_date,
                is_stable=version.is_stable,
                build_number=version.build_number,
                is_active=version.is_active,
                last_updated=version.updated_at,
                created_at=version.created_at,
                updated_at=version.updated_at,
            )
            for version in versions
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve {server_type.value} versions: {str(e)}",
        )


@router.get(
    "/{server_type}/{version}",
    response_model=MinecraftVersionResponse,
    summary="Get specific version details",
    description="Returns details for a specific version of a server type.",
)
async def get_specific_version(
    server_type: ServerType,
    version: str,
    db: Session = Depends(get_db),
) -> MinecraftVersionResponse:
    """
    Get details for a specific version.

    Args:
        server_type: Server type (vanilla, paper, fabric, forge)
        version: Version string (e.g., "1.21.6", "1.21.6-123")
        db: Database session

    Returns:
        Version details
    """
    try:
        repo = VersionRepository(db)
        version_obj = await repo.get_version_by_type_and_version(server_type, version)

        if not version_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version} not found for {server_type.value}",
            )

        return MinecraftVersionResponse(
            id=version_obj.id,
            server_type=version_obj.server_type,
            version=version_obj.version,
            download_url=version_obj.download_url,
            release_date=version_obj.release_date,
            is_stable=version_obj.is_stable,
            build_number=version_obj.build_number,
            is_active=version_obj.is_active,
            last_updated=version_obj.last_updated,
            created_at=version_obj.created_at,
            updated_at=version_obj.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve version details: {str(e)}",
        )
