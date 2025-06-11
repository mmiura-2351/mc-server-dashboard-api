import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.auth.dependencies import get_current_user
from app.servers.models import ServerType
from app.servers.schemas import SupportedVersionsResponse
from app.services.jar_cache_manager import jar_cache_manager
from app.services.version_manager import minecraft_version_manager
from app.users.models import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["servers"])


@router.get("/versions/supported", response_model=SupportedVersionsResponse)
async def get_supported_versions():
    """
    Get list of supported Minecraft versions

    Returns all supported Minecraft versions by server type with download URLs.
    All versions 1.8+ are supported with dynamic API integration.
    """
    try:
        from app.servers.schemas import MinecraftVersionInfo

        all_versions = []

        # Get versions for each server type
        for server_type in ServerType:
            try:
                versions = await minecraft_version_manager.get_supported_versions(
                    server_type
                )
                # Convert VersionInfo objects to MinecraftVersionInfo objects
                for version_info in versions:
                    minecraft_version_info = MinecraftVersionInfo(
                        version=version_info.version,
                        server_type=version_info.server_type,
                        download_url=version_info.download_url,
                        is_supported=True,  # All returned versions are supported
                        release_date=version_info.release_date,
                        is_stable=version_info.is_stable,
                        build_number=version_info.build_number,
                    )
                    all_versions.append(minecraft_version_info)
            except Exception as e:
                logger.warning(f"Failed to get versions for {server_type.value}: {e}")
                continue

        return SupportedVersionsResponse(versions=all_versions)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get supported versions: {str(e)}",
        )


@router.post("/sync")
async def sync_server_states(current_user: User = Depends(get_current_user)):
    """
    Synchronize server states between database and process manager

    Admin-only endpoint to manually trigger synchronization of server states.
    This ensures database status matches actual running processes.
    """
    try:
        # Only admins can trigger sync
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can sync server states",
            )

        from app.services.database_integration import database_integration_service

        database_integration_service.sync_server_states()

        # Get current state summary
        running_servers = database_integration_service.get_all_running_servers()

        return {
            "message": "Server states synchronized",
            "running_servers": running_servers,
            "total_running": len(running_servers),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync server states: {str(e)}",
        )


@router.get("/cache/stats")
async def get_cache_stats(current_user: User = Depends(get_current_user)):
    """
    Get JAR cache statistics

    Returns information about cached JAR files, total size, and cache efficiency.
    """
    try:
        # Only admins can view cache stats
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view cache statistics",
            )

        stats = await jar_cache_manager.get_cache_stats()
        return stats

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cache stats: {str(e)}",
        )


@router.post("/cache/cleanup")
async def cleanup_cache(current_user: User = Depends(get_current_user)):
    """
    Manually trigger cache cleanup

    Removes old and oversized cache files. Admin-only operation.
    """
    try:
        # Only admins can trigger cache cleanup
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can trigger cache cleanup",
            )

        await jar_cache_manager.cleanup_old_cache()
        stats = await jar_cache_manager.get_cache_stats()

        return {"message": "Cache cleanup completed", "cache_stats": stats}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup cache: {str(e)}",
        )
