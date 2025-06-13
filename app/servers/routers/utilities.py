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
from app.services.java_compatibility import java_compatibility_service
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


@router.get("/java/compatibility")
async def get_java_compatibility_info():
    """
    Get Java compatibility information

    Returns current Java version, compatibility matrix, and supported Minecraft versions.
    Useful for troubleshooting server creation issues and understanding Java requirements.
    """
    try:
        # Detect current Java version
        java_version = await java_compatibility_service.detect_java_version()

        # Get compatibility matrix
        compatibility_matrix = java_compatibility_service.get_compatibility_matrix()

        response = {
            "java_detected": java_version is not None,
            "compatibility_matrix": compatibility_matrix,
        }

        if java_version:
            response.update(
                {
                    "current_java": {
                        "major_version": java_version.major_version,
                        "version_string": java_version.version_string,
                        "vendor": java_version.vendor,
                        "full_version": java_version.full_version_string,
                    },
                    "supported_minecraft_versions": java_compatibility_service.get_supported_minecraft_versions(
                        java_version
                    ),
                }
            )
        else:
            response.update(
                {
                    "error": "Java is not installed or not accessible",
                    "installation_help": "Visit https://adoptium.net/temurin/releases/ for Java installation",
                }
            )

        return response

    except Exception as e:
        logger.error(f"Failed to get Java compatibility info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Java compatibility information: {str(e)}",
        )


@router.get("/java/validate/{minecraft_version}")
async def validate_java_for_minecraft_version(minecraft_version: str):
    """
    Validate Java compatibility for a specific Minecraft version

    Args:
        minecraft_version: Minecraft version to validate (e.g., "1.20.1")

    Returns validation result with detailed compatibility information.
    """
    try:
        # Basic version format validation
        import re

        if not re.match(r"^\d+\.\d+(\.\d+)?$", minecraft_version):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Minecraft version format. Use format like 1.20.1",
            )

        # Detect Java version
        java_version = await java_compatibility_service.detect_java_version()

        if java_version is None:
            return {
                "compatible": False,
                "minecraft_version": minecraft_version,
                "required_java": java_compatibility_service.get_required_java_version(
                    minecraft_version
                ),
                "error": "Java is not installed or not accessible",
                "installation_help": "Visit https://adoptium.net/temurin/releases/ for Java installation",
            }

        # Validate compatibility
        is_compatible, message = java_compatibility_service.validate_java_compatibility(
            minecraft_version, java_version
        )

        return {
            "compatible": is_compatible,
            "minecraft_version": minecraft_version,
            "required_java": java_compatibility_service.get_required_java_version(
                minecraft_version
            ),
            "current_java": {
                "major_version": java_version.major_version,
                "version_string": java_version.version_string,
                "vendor": java_version.vendor,
            },
            "message": message,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate Java for Minecraft {minecraft_version}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate Java compatibility: {str(e)}",
        )
