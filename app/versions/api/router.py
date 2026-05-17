"""FastAPI router for the versions domain.

All endpoints depend on `VersionUpdateService` via DI — they never see
SQLAlchemy or `VersionRepository` directly. This is the canonical wiring
shape for the entire codebase per `docs/ARCHITECTURE.md` §4.4.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.servers.models import ServerType
from app.users.models import Role, User
from app.versions.api.dependencies import get_version_service
from app.versions.application.service import VersionUpdateService
from app.versions.domain.entities import MinecraftVersionEntity
from app.versions.scheduler import version_update_scheduler
from app.versions.schemas import (
    MinecraftVersionResponse,
    VersionStatsResponse,
)
from app.versions.schemas import (
    VersionUpdateResult as VersionUpdateResultSchema,
)

router = APIRouter(tags=["versions"])


def _to_response(entity: MinecraftVersionEntity) -> MinecraftVersionResponse:
    """Convert a domain entity to the API DTO."""
    return MinecraftVersionResponse(
        id=entity.id,
        server_type=entity.server_type.value,
        version=entity.version,
        download_url=entity.download_url or "",
        release_date=entity.release_date,
        is_stable=entity.is_stable,
        build_number=entity.build_number,
        is_active=entity.is_active,
        last_updated=entity.updated_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


@router.get(
    "/supported",
    response_model=List[MinecraftVersionResponse],
    summary="Get all supported versions (fast database query)",
)
async def get_supported_versions(
    server_type: Optional[ServerType] = Query(None, description="Filter by server type"),
    service: VersionUpdateService = Depends(get_version_service),
) -> List[MinecraftVersionResponse]:
    try:
        if server_type:
            entities = await service.get_supported_versions(server_type)
        else:
            entities = await service.get_all_supported_versions()
        return [_to_response(e) for e in entities]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve versions: {str(e)}",
        )


@router.post(
    "/update",
    response_model=VersionUpdateResultSchema,
    summary="Trigger manual version update (admin only)",
)
async def trigger_version_update(
    server_types: Optional[List[ServerType]] = Query(
        None, description="Server types to update"
    ),
    force_refresh: bool = Query(
        False, description="Force refresh even if recently updated"
    ),
    current_user: User = Depends(get_current_user),
) -> VersionUpdateResultSchema:
    if current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can trigger version updates",
        )
    try:
        result = await version_update_scheduler.trigger_immediate_update(
            force_refresh=force_refresh
        )
        return VersionUpdateResultSchema(
            success=result.success,
            message=result.message,
            log_id=result.log_id,
            versions_added=result.versions_added,
            versions_updated=result.versions_updated,
            versions_removed=result.versions_removed,
            execution_time_ms=result.execution_time_ms,
            errors=result.errors,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger version update: {str(e)}",
        )


@router.get(
    "/scheduler/status",
    summary="Get version update scheduler status (admin only)",
)
async def get_scheduler_status(
    current_user: User = Depends(get_current_user),
) -> dict:
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
)
async def get_version_stats(
    service: VersionUpdateService = Depends(get_version_service),
) -> VersionStatsResponse:
    try:
        stats = await service.get_version_stats()
        return VersionStatsResponse(
            total_versions=stats.total_versions,
            active_versions=stats.active_versions,
            by_server_type=stats.by_server_type,
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
)
async def get_versions_by_server_type(
    server_type: ServerType,
    service: VersionUpdateService = Depends(get_version_service),
) -> List[MinecraftVersionResponse]:
    try:
        entities = await service.get_supported_versions(server_type)
        return [_to_response(e) for e in entities]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve {server_type.value} versions: {str(e)}",
        )


@router.get(
    "/{server_type}/{version}",
    response_model=MinecraftVersionResponse,
    summary="Get specific version details",
)
async def get_specific_version(
    server_type: ServerType,
    version: str,
    service: VersionUpdateService = Depends(get_version_service),
) -> MinecraftVersionResponse:
    try:
        entity = await service.get_version(server_type, version)
        if entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version} not found for {server_type.value}",
            )
        return _to_response(entity)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve version details: {str(e)}",
        )
