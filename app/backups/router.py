import os

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.backups.schemas import (
    BackupCreateRequest,
    BackupListResponse,
    BackupOperationResponse,
    BackupResponse,
    BackupRestoreRequest,
    BackupRestoreWithTemplateRequest,
    BackupRestoreWithTemplateResponse,
    BackupStatisticsResponse,
    BackupUploadResponse,
    ScheduledBackupRequest,
)
from app.core.database import get_db
from app.core.exceptions import (
    BackupNotFoundException,
    DatabaseOperationException,
    FileOperationException,
    ServerNotFoundException,
)
from app.servers.models import BackupStatus, BackupType
from app.services.authorization_service import authorization_service
from app.services.backup_service import backup_service
from app.users.models import Role, User

router = APIRouter(tags=["backups"])


async def validate_upload_size(request: Request) -> None:
    """Validate request size before processing to prevent memory exhaustion"""
    content_length = request.headers.get("content-length")
    max_size = 500 * 1024 * 1024  # 500MB

    if not content_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content-Length header required for file uploads",
        )

    try:
        size = int(content_length)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Content-Length header",
        )

    if size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request size ({size / (1024*1024):.1f}MB) exceeds maximum allowed size (500MB)",
        )

    if size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request size"
        )


# Helper functions moved to authorization_service


@router.post(
    "/servers/{server_id}/backups",
    response_model=BackupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_backup(
    server_id: int,
    request: BackupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a backup for a server

    Creates a complete backup of the server directory including world data,
    configuration files, and plugin/mod data.

    - **name**: Descriptive name for the backup
    - **description**: Optional description
    - **backup_type**: Type of backup (manual, scheduled, pre_update)
    """
    try:
        # Check server access
        authorization_service.check_server_access(server_id, current_user, db)

        # Phase 1: All users can create backups
        if not authorization_service.can_create_backup(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to create backups",
            )

        backup = await backup_service.create_backup(
            server_id=server_id,
            name=request.name,
            description=request.description,
            backup_type=request.backup_type,
            db=db,
        )

        return BackupResponse.from_orm(backup)

    except HTTPException:
        raise
    except (ServerNotFoundException, BackupNotFoundException) as e:
        raise e  # These already have proper HTTP status codes
    except (FileOperationException, DatabaseOperationException) as e:
        raise e  # These already have proper HTTP status codes
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create backup: {str(e)}",
        )


@router.post(
    "/servers/{server_id}/backups/upload",
    response_model=BackupUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_backup(
    server_id: int,
    file: UploadFile = File(...),
    name: str = Form(None),
    description: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(validate_upload_size),
):
    """
    Upload a backup file for a server

    Upload a .tar.gz backup file and create a backup record.
    The file will be validated and stored securely.

    - **file**: Backup file (.tar.gz or .tgz)
    - **name**: Optional backup name (auto-generated if not provided)
    - **description**: Optional backup description
    """
    try:
        # Check server access
        authorization_service.check_server_access(server_id, current_user, db)

        # Only operators and admins can upload backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can upload backups",
            )

        # Validate file is provided
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided",
            )

        backup = await backup_service.upload_backup(
            server_id=server_id,
            file=file,
            name=name,
            description=description,
            db=db,
        )

        backup_response = BackupResponse.from_orm(backup)

        return BackupUploadResponse(
            success=True,
            message="Backup uploaded successfully",
            backup=backup_response,
            file_size=backup.file_size,
            original_filename=file.filename,
        )

    except HTTPException:
        raise
    except (ServerNotFoundException, BackupNotFoundException) as e:
        raise e  # These already have proper HTTP status codes
    except (FileOperationException, DatabaseOperationException) as e:
        raise e  # These already have proper HTTP status codes
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload backup: {str(e)}",
        )


@router.get("/servers/{server_id}/backups", response_model=BackupListResponse)
async def list_server_backups(
    server_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    backup_type: BackupType = Query(None, description="Filter by backup type"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List backups for a specific server

    Returns a paginated list of backups for the specified server.
    Users can only see backups for servers they own (unless they're admin).
    """
    try:
        # Check server access
        authorization_service.check_server_access(server_id, current_user, db)

        result = backup_service.list_backups(
            server_id=server_id,
            backup_type=backup_type,
            page=page,
            size=size,
            db=db,
        )

        backup_responses = [
            BackupResponse.from_orm(backup) for backup in result["backups"]
        ]

        return BackupListResponse(
            backups=backup_responses,
            total=result["total"],
            page=result["page"],
            size=result["size"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list backups: {str(e)}",
        )


@router.get("/backups", response_model=BackupListResponse)
async def list_all_backups(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    backup_type: BackupType = Query(None, description="Filter by backup type"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all backups (admin only)

    Returns a paginated list of all backups in the system.
    Only admins can access this endpoint.
    """
    try:
        # Only admins can see all backups
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view all backups",
            )

        result = backup_service.list_backups(
            backup_type=backup_type,
            page=page,
            size=size,
            db=db,
        )

        backup_responses = [
            BackupResponse.from_orm(backup) for backup in result["backups"]
        ]

        return BackupListResponse(
            backups=backup_responses,
            total=result["total"],
            page=result["page"],
            size=result["size"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list all backups: {str(e)}",
        )


# Statistics endpoints must come before {backup_id} to avoid path conflicts
@router.get("/backups/statistics", response_model=BackupStatisticsResponse)
async def get_global_backup_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get global backup statistics (admin only)

    Returns statistics about all backups in the system.
    Only admins can access this endpoint.
    """
    try:
        # Only admins can see global statistics
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view global backup statistics",
            )

        stats = backup_service.get_backup_statistics(db=db)

        return BackupStatisticsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get global backup statistics: {str(e)}",
        )


@router.get("/backups/{backup_id}", response_model=BackupResponse)
async def get_backup(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get backup details by ID

    Returns detailed information about a specific backup.
    """
    try:
        # Check backup access
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        return BackupResponse.from_orm(backup)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get backup: {str(e)}",
        )


@router.post("/backups/{backup_id}/restore", response_model=BackupOperationResponse)
async def restore_backup(
    backup_id: int,
    request: BackupRestoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Restore a backup

    Restores a backup to the original server or a specified target server.
    The target server must be stopped before restoration.

    - **target_server_id**: Optional target server (defaults to original)
    - **confirm**: Must be True to proceed with restoration
    """
    try:
        # Check backup access
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        # Only operators and admins can restore backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can restore backups",
            )

        # Check target server access if specified
        target_server_id = request.target_server_id or backup.server_id
        authorization_service.check_server_access(target_server_id, current_user, db)

        success = await backup_service.restore_backup(
            backup_id=backup_id,
            server_id=target_server_id,
            db=db,
        )

        return BackupOperationResponse(
            success=success,
            message=f"Backup {backup_id} restored successfully to server {target_server_id}",
            backup_id=backup_id,
            details={"target_server_id": target_server_id},
        )

    except HTTPException:
        raise
    except (BackupNotFoundException, ServerNotFoundException) as e:
        raise e  # These already have proper HTTP status codes
    except (FileOperationException, DatabaseOperationException) as e:
        raise e  # These already have proper HTTP status codes
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore backup: {str(e)}",
        )


@router.post(
    "/backups/{backup_id}/restore-with-template",
    response_model=BackupRestoreWithTemplateResponse,
)
async def restore_backup_and_create_template(
    backup_id: int,
    request: BackupRestoreWithTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Restore a backup and create a template from it

    Restores a backup to the original server or a specified target server,
    then creates a template from the restored server configuration.
    This is useful for creating reusable templates from backup states.

    - **target_server_id**: Optional target server (defaults to original)
    - **confirm**: Must be True to proceed with restoration
    - **template_name**: Name for the template to create
    - **template_description**: Optional description for the template
    - **is_public**: Whether the template should be public
    """
    try:
        # Check backup access
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        # Only operators and admins can restore backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can restore backups",
            )

        # Check target server access if specified
        target_server_id = request.target_server_id or backup.server_id
        authorization_service.check_server_access(target_server_id, current_user, db)

        result = await backup_service.restore_backup_and_create_template(
            backup_id=backup_id,
            template_name=request.template_name,
            template_description=request.template_description,
            is_public=request.is_public,
            user=current_user,
            server_id=target_server_id,
            db=db,
        )

        message = f"Backup {backup_id} restored successfully to server {target_server_id}"
        if result["template_created"]:
            message += f" and template '{result['template_name']}' created"

        return BackupRestoreWithTemplateResponse(
            backup_restored=result["backup_restored"],
            template_created=result["template_created"],
            message=message,
            backup_id=backup_id,
            template_id=result.get("template_id"),
            template_name=result.get("template_name"),
            details={
                "target_server_id": target_server_id,
                "template_description": request.template_description,
                "is_public": request.is_public,
            },
        )

    except HTTPException:
        raise
    except (BackupNotFoundException, ServerNotFoundException) as e:
        raise e  # These already have proper HTTP status codes
    except (FileOperationException, DatabaseOperationException) as e:
        raise e  # These already have proper HTTP status codes
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore backup and create template: {str(e)}",
        )


@router.get("/backups/{backup_id}/download")
async def download_backup(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Download a backup file

    Downloads the backup file as a binary stream.
    Users can only download backups for servers they have access to.
    """
    try:
        # Check backup access
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        # Verify backup is completed
        if backup.status != BackupStatus.completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Backup is not completed and cannot be downloaded",
            )

        # Check if file exists
        if not os.path.exists(backup.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Backup file not found on disk",
            )

        # Generate filename for download
        backup_filename = f"{backup.server.name}_{backup.name}_{backup.id}.tar.gz"

        # Return file response with proper headers
        return FileResponse(
            path=backup.file_path,
            filename=backup_filename,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{backup_filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download backup: {str(e)}",
        )


@router.delete("/backups/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a backup

    Permanently deletes a backup and its associated file.
    This action cannot be undone.
    """
    try:
        # Check backup access
        authorization_service.check_backup_access(backup_id, current_user, db)

        # Only operators and admins can delete backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can delete backups",
            )

        success = await backup_service.delete_backup(backup_id, db)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete backup: {str(e)}",
        )


@router.get(
    "/servers/{server_id}/backups/statistics", response_model=BackupStatisticsResponse
)
async def get_server_backup_statistics(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get backup statistics for a server

    Returns statistics about backups for the specified server including
    total count, success rate, and storage usage.
    """
    try:
        # Check server access
        authorization_service.check_server_access(server_id, current_user, db)

        stats = backup_service.get_backup_statistics(server_id=server_id, db=db)

        return BackupStatisticsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get backup statistics: {str(e)}",
        )


@router.post("/backups/scheduled", response_model=BackupOperationResponse)
async def create_scheduled_backups(
    request: ScheduledBackupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create scheduled backups for multiple servers (admin only)

    Creates scheduled backups for the specified servers.
    Only admins can trigger scheduled backups.
    """
    try:
        # Only admins can create scheduled backups
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can create scheduled backups",
            )

        created_backups = []
        failed_servers = []

        for server_id in request.server_ids:
            try:
                backup = await backup_service.create_scheduled_backup(server_id, db)
                if backup:
                    created_backups.append(backup.id)
                else:
                    failed_servers.append(server_id)
            except Exception:
                failed_servers.append(server_id)

        success = len(created_backups) > 0
        message = f"Created {len(created_backups)} scheduled backups"
        if failed_servers:
            message += f", failed for servers: {failed_servers}"

        return BackupOperationResponse(
            success=success,
            message=message,
            details={
                "created_backups": created_backups,
                "failed_servers": failed_servers,
                "total_requested": len(request.server_ids),
                "total_created": len(created_backups),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create scheduled backups: {str(e)}",
        )
