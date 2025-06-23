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
from app.users.models import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["servers"])


@router.get("/versions/supported", response_model=SupportedVersionsResponse)
async def get_supported_versions():
    """
    Get list of supported Minecraft versions (FAST DATABASE VERSION)

    Returns all supported Minecraft versions from database cache.
    Response time: 10-50ms (vs 4-5 seconds from external APIs).

    NEW: This endpoint now uses database cache instead of slow external API calls.
    The database is automatically updated by background scheduler every 24 hours.
    """
    try:
        from app.core.database import SessionLocal
        from app.servers.schemas import MinecraftVersionInfo
        from app.versions.repository import VersionRepository

        # Use database instead of external APIs
        with SessionLocal() as db:
            repo = VersionRepository(db)

            # Get all active versions from database (FAST!)
            db_versions = await repo.get_all_active_versions()

            # Convert to expected format
            all_versions = []
            for db_version in db_versions:
                minecraft_version_info = MinecraftVersionInfo(
                    version=db_version.version,
                    server_type=ServerType(db_version.server_type),
                    download_url=db_version.download_url or "",
                    is_supported=True,  # All active versions are supported
                    release_date=db_version.release_date,
                    is_stable=db_version.is_stable,
                    build_number=db_version.build_number,
                )
                all_versions.append(minecraft_version_info)

        return SupportedVersionsResponse(versions=all_versions)

    except Exception as e:
        logger.error(f"Database version lookup failed: {e}")
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
        # Discover all Java installations
        java_installations = (
            await java_compatibility_service.discover_java_installations()
        )

        # Get compatibility matrix
        compatibility_matrix = java_compatibility_service.get_compatibility_matrix()

        response = {
            "java_installations_found": len(java_installations),
            "compatibility_matrix": compatibility_matrix,
            "installations": {},
        }

        for major_version, java_info in java_installations.items():
            response["installations"][str(major_version)] = {
                "major_version": java_info.major_version,
                "version_string": java_info.version_string,
                "vendor": java_info.vendor,
                "executable_path": java_info.executable_path,
                "full_version": java_info.full_version_string,
                "supported_minecraft_versions": java_compatibility_service.get_supported_minecraft_versions(
                    java_info
                ),
            }

        if not java_installations:
            response.update(
                {
                    "error": "No Java installations found",
                    "installation_help": "Install OpenJDK or configure Java paths in .env file",
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

        # Get appropriate Java for Minecraft version
        java_version = await java_compatibility_service.get_java_for_minecraft(
            minecraft_version
        )

        if java_version is None:
            # Get all available installations for detailed error
            installations = await java_compatibility_service.discover_java_installations()
            available_versions = list(installations.keys())
            required_version = java_compatibility_service.get_required_java_version(
                minecraft_version
            )

            return {
                "compatible": False,
                "minecraft_version": minecraft_version,
                "required_java": required_version,
                "available_java_versions": available_versions,
                "error": f"No compatible Java installation found for Minecraft {minecraft_version}",
                "installation_help": f"Install Java {required_version} or configure JAVA_{required_version}_PATH in .env",
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
            "selected_java": {
                "major_version": java_version.major_version,
                "version_string": java_version.version_string,
                "vendor": java_version.vendor,
                "executable_path": java_version.executable_path,
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
