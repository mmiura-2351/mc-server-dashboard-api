from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    ScheduledBackupRequest,
)
from app.core.database import get_db
from app.servers.models import BackupType, Server
from app.services.backup_service import (
    BackupError,
    BackupNotFoundError,
    BackupRestorationError,
    ServerNotFoundError,
    backup_service,
)
from app.users.models import Role, User

router = APIRouter(tags=["backups"])


def check_server_access(server_id: int, current_user: User, db: Session):
    """Check if user has access to the server"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
        )

    if current_user.role != Role.admin and server.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this server",
        )

    return server


def check_backup_access(backup_id: int, current_user: User, db: Session):
    """Check if user has access to the backup"""
    from app.servers.models import Backup

    backup = db.query(Backup).filter(Backup.id == backup_id).first()
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found"
        )

    # Check server access
    check_server_access(backup.server_id, current_user, db)
    return backup


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
        check_server_access(server_id, current_user, db)

        # Only operators and admins can create backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create backups",
            )

        backup = await backup_service.create_backup(
            server_id=server_id,
            name=request.name,
            description=request.description,
            backup_type=request.backup_type,
            db=db,
        )

        return BackupResponse.from_orm(backup)

    except ServerNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BackupError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create backup: {str(e)}",
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
        check_server_access(server_id, current_user, db)

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

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list all backups: {str(e)}",
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
        backup = check_backup_access(backup_id, current_user, db)

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
        backup = check_backup_access(backup_id, current_user, db)

        # Only operators and admins can restore backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can restore backups",
            )

        # Check target server access if specified
        target_server_id = request.target_server_id or backup.server_id
        check_server_access(target_server_id, current_user, db)

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
    except BackupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BackupRestorationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
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
        backup = check_backup_access(backup_id, current_user, db)

        # Only operators and admins can restore backups
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can restore backups",
            )

        # Check target server access if specified
        target_server_id = request.target_server_id or backup.server_id
        check_server_access(target_server_id, current_user, db)

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
    except BackupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BackupRestorationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore backup and create template: {str(e)}",
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
        check_backup_access(backup_id, current_user, db)

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
        check_server_access(server_id, current_user, db)

        stats = backup_service.get_backup_statistics(server_id=server_id, db=db)

        return BackupStatisticsResponse(**stats)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get backup statistics: {str(e)}",
        )


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

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get global backup statistics: {str(e)}",
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

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create scheduled backups: {str(e)}",
        )


# Backup Scheduler Management Endpoints


@router.get("/scheduler/status")
async def get_scheduler_status(current_user: User = Depends(get_current_user)):
    """
    Get backup scheduler status (admin only)

    Returns the current status of the backup scheduler including
    scheduled servers and their next backup times.
    """
    try:
        # Only admins can view scheduler status
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view scheduler status",
            )

        from app.services.backup_scheduler import backup_scheduler

        scheduler_status = backup_scheduler.get_scheduler_status()
        return scheduler_status

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduler status: {str(e)}",
        )


@router.post("/scheduler/servers/{server_id}/schedule")
async def add_server_to_schedule(
    server_id: int,
    interval_hours: int = Query(24, ge=1, le=168, description="Backup interval in hours"),
    max_backups: int = Query(7, ge=1, le=30, description="Maximum backups to keep"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Add server to backup schedule (admin only)

    Schedules automatic backups for the specified server.

    - **interval_hours**: How often to create backups (1-168 hours)
    - **max_backups**: Maximum number of backups to keep (1-30)
    """
    try:
        # Only admins can manage scheduler
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can manage backup schedules",
            )

        # Check if server exists
        server = (
            db.query(Server).filter(Server.id == server_id, not Server.is_deleted).first()
        )
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        from app.services.backup_scheduler import backup_scheduler

        backup_scheduler.add_server_schedule(
            server_id=server_id,
            interval_hours=interval_hours,
            max_backups=max_backups,
            enabled=True,
        )

        return {
            "message": f"Server {server_id} added to backup schedule",
            "interval_hours": interval_hours,
            "max_backups": max_backups,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add server to schedule: {str(e)}",
        )


@router.put("/scheduler/servers/{server_id}/schedule")
async def update_server_schedule(
    server_id: int,
    interval_hours: Optional[int] = Query(
        None, ge=1, le=168, description="Backup interval in hours"
    ),
    max_backups: Optional[int] = Query(
        None, ge=1, le=30, description="Maximum backups to keep"
    ),
    enabled: Optional[bool] = Query(None, description="Enable/disable scheduled backups"),
    current_user: User = Depends(get_current_user),
):
    """
    Update server backup schedule (admin only)

    Updates the backup schedule settings for a server.
    """
    try:
        # Only admins can manage scheduler
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can manage backup schedules",
            )

        from app.services.backup_scheduler import backup_scheduler

        schedule = backup_scheduler.get_server_schedule(server_id)
        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found in backup schedule",
            )

        backup_scheduler.update_server_schedule(
            server_id=server_id,
            interval_hours=interval_hours,
            max_backups=max_backups,
            enabled=enabled,
        )

        updated_schedule = backup_scheduler.get_server_schedule(server_id)
        return {
            "message": f"Updated backup schedule for server {server_id}",
            "schedule": updated_schedule,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update server schedule: {str(e)}",
        )


@router.delete("/scheduler/servers/{server_id}/schedule")
async def remove_server_from_schedule(
    server_id: int, current_user: User = Depends(get_current_user)
):
    """
    Remove server from backup schedule (admin only)

    Removes a server from the automatic backup schedule.
    """
    try:
        # Only admins can manage scheduler
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can manage backup schedules",
            )

        from app.services.backup_scheduler import backup_scheduler

        schedule = backup_scheduler.get_server_schedule(server_id)
        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found in backup schedule",
            )

        backup_scheduler.remove_server_schedule(server_id)

        return {"message": f"Server {server_id} removed from backup schedule"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove server from schedule: {str(e)}",
        )
