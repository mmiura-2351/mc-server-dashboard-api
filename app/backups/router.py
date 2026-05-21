"""Backup REST API router.

Endpoints depend on `BackupService` via `Depends(get_backup_service)`,
and on `authorization_service` for cross-domain access checks (Server,
Backup ownership). The DB session is still passed through to
`authorization_service` (legacy `db.query` calls inside that helper
are tracked under #228 punch-list).
"""

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
from app.backups.api._mappers import (
    backup_entity_to_response,
    backup_statistics_to_response,
)
from app.backups.api.dependencies import get_backup_service
from app.backups.application.service import BackupService
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
from app.templates.api.dependencies import get_template_service
from app.templates.application.service import TemplateService
from app.users.domain.value_objects import Role
from app.users.models import User

router = APIRouter(tags=["backups"])


async def validate_upload_size(request: Request) -> None:
    """Validate request size before processing to prevent memory exhaustion."""
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
            detail=f"Request size ({size / (1024 * 1024):.1f}MB) "
            f"exceeds maximum allowed size (500MB)",
        )

    if size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request size"
        )


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
    backup_service: BackupService = Depends(get_backup_service),
):
    """Create a backup for a server."""
    try:
        authorization_service.check_server_access(server_id, current_user, db)

        if not authorization_service.can_create_backup(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to create backups",
            )

        entity = await backup_service.create_backup(
            server_id=server_id,
            name=request.name,
            description=request.description,
            backup_type=request.backup_type,
        )

        return backup_entity_to_response(entity)

    except HTTPException:
        raise
    except (ServerNotFoundException, BackupNotFoundException):
        raise
    except (FileOperationException, DatabaseOperationException):
        raise
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
    backup_service: BackupService = Depends(get_backup_service),
    _: None = Depends(validate_upload_size),
):
    """Upload a backup file for a server."""
    try:
        authorization_service.check_server_access(server_id, current_user, db)

        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided",
            )

        entity = await backup_service.upload_backup(
            server_id=server_id,
            file=file,
            name=name,
            description=description,
        )

        backup_response = backup_entity_to_response(entity)

        return BackupUploadResponse(
            success=True,
            message="Backup uploaded successfully",
            backup=backup_response,
            file_size=entity.file_size,
            original_filename=file.filename,
        )

    except HTTPException:
        raise
    except (ServerNotFoundException, BackupNotFoundException):
        raise
    except (FileOperationException, DatabaseOperationException):
        raise
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
    backup_service: BackupService = Depends(get_backup_service),
):
    """List backups for a specific server."""
    try:
        authorization_service.check_server_access(server_id, current_user, db)

        page_result = await backup_service.list_backups(
            server_id=server_id,
            backup_type=backup_type,
            page=page,
            size=size,
        )

        return BackupListResponse(
            backups=[backup_entity_to_response(e) for e in page_result.entities],
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
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
    backup_service: BackupService = Depends(get_backup_service),
):
    """List all backups (admin only)."""
    try:
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view all backups",
            )

        page_result = await backup_service.list_backups(
            backup_type=backup_type,
            page=page,
            size=size,
        )

        return BackupListResponse(
            backups=[backup_entity_to_response(e) for e in page_result.entities],
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list all backups: {str(e)}",
        )


@router.get("/backups/statistics", response_model=BackupStatisticsResponse)
async def get_global_backup_statistics(
    current_user: User = Depends(get_current_user),
    backup_service: BackupService = Depends(get_backup_service),
):
    """Get global backup statistics (admin only)."""
    try:
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view global backup statistics",
            )

        stats = await backup_service.get_backup_statistics()
        return backup_statistics_to_response(stats)

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
    """Get backup details by ID."""
    try:
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
    backup_service: BackupService = Depends(get_backup_service),
):
    """Restore a backup."""
    try:
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        target_server_id = request.target_server_id or backup.server_id
        authorization_service.check_server_access(target_server_id, current_user, db)

        success = await backup_service.restore_backup(
            backup_id=backup_id,
            server_id=target_server_id,
        )

        return BackupOperationResponse(
            success=success,
            message=f"Backup {backup_id} restored successfully to server {target_server_id}",
            backup_id=backup_id,
            details={"target_server_id": target_server_id},
        )

    except HTTPException:
        raise
    except (BackupNotFoundException, ServerNotFoundException):
        raise
    except (FileOperationException, DatabaseOperationException):
        raise
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
    backup_service: BackupService = Depends(get_backup_service),
    template_service: TemplateService = Depends(get_template_service),
):
    """Restore a backup and create a template from it.

    Composes `BackupService.restore_backup` and
    `TemplateService.create_template_from_server` directly here
    (per D-9) so neither service has cross-domain knowledge of the
    other.
    """
    try:
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        target_server_id = request.target_server_id or backup.server_id
        authorization_service.check_server_access(target_server_id, current_user, db)

        restored = await backup_service.restore_backup(
            backup_id=backup_id,
            server_id=target_server_id,
        )
        if not restored:
            raise FileOperationException(
                "restore", f"backup {backup_id}", "Failed to restore backup"
            )

        result_template_created = False
        result_template_id = None
        result_template_name = None

        if request.template_name:
            template = await template_service.create_template_from_server(
                server_id=target_server_id,
                name=request.template_name,
                creator_id=current_user.id,
                description=request.template_description
                or f"Template created from backup {backup.name}",
                is_public=request.is_public,
            )
            result_template_created = True
            result_template_id = template.id
            result_template_name = template.name

        message = f"Backup {backup_id} restored successfully to server {target_server_id}"
        if result_template_created:
            message += f" and template '{result_template_name}' created"

        return BackupRestoreWithTemplateResponse(
            backup_restored=True,
            template_created=result_template_created,
            message=message,
            backup_id=backup_id,
            template_id=result_template_id,
            template_name=result_template_name,
            details={
                "target_server_id": target_server_id,
                "template_description": request.template_description,
                "is_public": request.is_public,
            },
        )

    except HTTPException:
        raise
    except (BackupNotFoundException, ServerNotFoundException):
        raise
    except (FileOperationException, DatabaseOperationException):
        raise
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
    """Download a backup file."""
    try:
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        if backup.status != BackupStatus.completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Backup is not completed and cannot be downloaded",
            )

        if not os.path.exists(backup.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Backup file not found on disk",
            )

        backup_filename = f"{backup.server.name}_{backup.name}_{backup.id}.tar.gz"

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
    backup_service: BackupService = Depends(get_backup_service),
):
    """Delete a backup."""
    try:
        backup = authorization_service.check_backup_access(backup_id, current_user, db)

        if not authorization_service.can_delete_backup(backup, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and server owners can delete backups",
            )

        success = await backup_service.delete_backup(backup_id)
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
    backup_service: BackupService = Depends(get_backup_service),
):
    """Get backup statistics for a server."""
    try:
        authorization_service.check_server_access(server_id, current_user, db)
        stats = await backup_service.get_backup_statistics(server_id=server_id)
        return backup_statistics_to_response(stats)

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
    backup_service: BackupService = Depends(get_backup_service),
):
    """Create scheduled backups for multiple servers (admin only)."""
    try:
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can create scheduled backups",
            )

        created_backups = []
        failed_servers = []

        for server_id in request.server_ids:
            try:
                backup = await backup_service.create_scheduled_backup(server_id)
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
