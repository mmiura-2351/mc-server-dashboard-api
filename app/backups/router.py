"""Backup REST API router.

Endpoints depend on `BackupService` via `Depends(get_backup_service)`,
and on `AuthorizationService` (instance-injected via
`Depends(get_authorization_service)`) for cross-domain access checks
(Server, Backup ownership). Post-#228 PR 2b the access checks are
async and resolve resources through Repository Ports rather than
direct `db.query` calls.
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
from app.backups.domain.exceptions import (
    BackupNotFoundError,
    BackupParentServerMissingError,
)
from app.backups.models import BackupStatus, BackupType
from app.backups.schemas import (
    BackupCreateRequest,
    BackupListResponse,
    BackupOperationResponse,
    BackupResponse,
    BackupRestoreRequest,
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
from app.servers.api.dependencies import get_authorization_service
from app.servers.application.authorization import AuthorizationService
from app.servers.domain.exceptions import ServerAccessError, ServerNotFoundError
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
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Create a backup for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

        if not AuthorizationService.can_create_backup(current_user):
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

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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
    auth: AuthorizationService = Depends(get_authorization_service),
    _: None = Depends(validate_upload_size),
):
    """Upload a backup file for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

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

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """List backups for a specific server."""
    try:
        await auth.check_server_access(server_id, current_user)

        page_result = await backup_service.list_backups(
            server_id=server_id,
            backup_type=backup_type,
            page=page,
            size=size,
        )

        # Issue #76 (Phase 1): retain legacy keys + add ``pagination``.
        from app.core.pagination import build_pagination_meta

        pagination = build_pagination_meta(
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
        )
        return BackupListResponse(
            backups=[backup_entity_to_response(e) for e in page_result.entities],
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
            pagination=pagination,
        )

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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

        # Issue #76 (Phase 1): retain legacy keys + add ``pagination``.
        from app.core.pagination import build_pagination_meta

        pagination = build_pagination_meta(
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
        )
        return BackupListResponse(
            backups=[backup_entity_to_response(e) for e in page_result.entities],
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
            pagination=pagination,
        )

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Get backup details by ID."""
    try:
        backup = await auth.check_backup_access(backup_id, current_user)
        return backup_entity_to_response(backup)

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Restore a backup."""
    try:
        backup = await auth.check_backup_access(backup_id, current_user)

        target_server_id = request.target_server_id or backup.server_id
        await auth.check_server_access(target_server_id, current_user)

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

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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


@router.get("/backups/{backup_id}/download")
async def download_backup(
    backup_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Download a backup file."""
    try:
        backup = await auth.check_backup_access(backup_id, current_user)

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

        # `server_name` is denormalised onto `BackupEntity` (post-#228),
        # replacing the legacy `backup.server.name` relationship access.
        server_name = backup.server_name or f"server_{backup.server_id}"
        backup_filename = f"{server_name}_{backup.name}_{backup.id}.tar.gz"

        return FileResponse(
            path=backup.file_path,
            filename=backup_filename,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{backup_filename}"'},
        )

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Delete a backup."""
    try:
        backup = await auth.check_backup_access(backup_id, current_user)

        # `BackupEntity` carries `server_owner_id` denormalised by the
        # repository (#274), so the ownership check no longer needs a
        # second round-trip to fetch the parent server.
        if not AuthorizationService.can_delete_backup(backup, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and server owners can delete backups",
            )

        success = await backup_service.delete_backup(backup_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found"
            )

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Get backup statistics for a server."""
    try:
        await auth.check_server_access(server_id, current_user)
        stats = await backup_service.get_backup_statistics(server_id=server_id)
        return backup_statistics_to_response(stats)

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
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

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create scheduled backups: {str(e)}",
        )
