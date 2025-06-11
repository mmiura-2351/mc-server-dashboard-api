"""
新しいバックアップスケジューラーAPIエンドポイント
サーバー所有者と管理者のアクセス許可対応
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.backups.models import BackupScheduleLog
from app.backups.schemas import (
    BackupScheduleLogResponse,
    BackupScheduleRequest,
    BackupScheduleResponse,
    BackupScheduleUpdateRequest,
    SchedulerStatusResponse,
)
from app.core.database import get_db
from app.services.authorization_service import authorization_service
from app.services.backup_scheduler import backup_scheduler
from app.users.models import Role, User

router = APIRouter(tags=["backup-scheduler"])


@router.post(
    "/scheduler/servers/{server_id}/schedule",
    response_model=BackupScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_backup_schedule(
    server_id: int,
    request: BackupScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a backup schedule for a server
    
    Create an automated backup schedule for the specified server.
    Only server owners and admins can create schedules.
    
    - **interval_hours**: How often to create backups (1-168 hours)
    - **max_backups**: Maximum number of backups to keep (1-30)  
    - **enabled**: Whether the schedule is active
    - **only_when_running**: Only backup when server is running
    """
    try:
        # Check server access (owner or admin)
        authorization_service.check_server_access(server_id, current_user, db)

        # Only operators and admins can create schedules
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create backup schedules",
            )

        schedule = await backup_scheduler.create_schedule(
            db=db,
            server_id=server_id,
            interval_hours=request.interval_hours,
            max_backups=request.max_backups,
            enabled=request.enabled,
            only_when_running=request.only_when_running,
            executed_by_user_id=current_user.id,
        )

        return BackupScheduleResponse.from_orm(schedule)

    except ValueError as e:
        if "already has" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        elif "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create backup schedule: {str(e)}",
        )


@router.get(
    "/scheduler/servers/{server_id}/schedule",
    response_model=BackupScheduleResponse,
)
async def get_backup_schedule(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get backup schedule for a server
    
    Returns the backup schedule configuration for the specified server.
    Server owners and admins can access schedules.
    """
    try:
        # Check server access (owner or admin)
        authorization_service.check_server_access(server_id, current_user, db)

        schedule = await backup_scheduler.get_schedule(db=db, server_id=server_id)

        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No backup schedule found for server {server_id}",
            )

        return BackupScheduleResponse.from_orm(schedule)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get backup schedule: {str(e)}",
        )


@router.put(
    "/scheduler/servers/{server_id}/schedule",
    response_model=BackupScheduleResponse,
)
async def update_backup_schedule(
    server_id: int,
    request: BackupScheduleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update backup schedule for a server
    
    Updates the backup schedule settings for a server.
    Only server owners and admins can update schedules.
    """
    try:
        # Check server access (owner or admin)
        authorization_service.check_server_access(server_id, current_user, db)

        # Only operators and admins can update schedules
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can update backup schedules",
            )

        schedule = await backup_scheduler.update_schedule(
            db=db,
            server_id=server_id,
            interval_hours=request.interval_hours,
            max_backups=request.max_backups,
            enabled=request.enabled,
            only_when_running=request.only_when_running,
            executed_by_user_id=current_user.id,
        )

        return BackupScheduleResponse.from_orm(schedule)

    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update backup schedule: {str(e)}",
        )


@router.delete(
    "/scheduler/servers/{server_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_backup_schedule(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete backup schedule for a server
    
    Removes the backup schedule for the specified server.
    Only server owners and admins can delete schedules.
    """
    try:
        # Check server access (owner or admin)
        authorization_service.check_server_access(server_id, current_user, db)

        # Only operators and admins can delete schedules
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can delete backup schedules",
            )

        success = await backup_scheduler.delete_schedule(
            db=db,
            server_id=server_id,
            executed_by_user_id=current_user.id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No backup schedule found for server {server_id}",
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete backup schedule: {str(e)}",
        )


@router.get(
    "/scheduler/servers/{server_id}/logs",
    response_model=List[BackupScheduleLogResponse],
)
async def get_backup_schedule_logs(
    server_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get backup schedule logs for a server
    
    Returns the history of backup schedule operations for the specified server.
    Server owners and admins can access logs.
    """
    try:
        # Check server access (owner or admin)
        authorization_service.check_server_access(server_id, current_user, db)

        # Calculate offset
        offset = (page - 1) * size

        # Query logs
        logs = (
            db.query(BackupScheduleLog)
            .filter(BackupScheduleLog.server_id == server_id)
            .order_by(BackupScheduleLog.created_at.desc())
            .offset(offset)
            .limit(size)
            .all()
        )

        # Create response with user information
        log_responses = []
        for log in logs:
            log_data = BackupScheduleLogResponse.from_orm(log)
            
            # Add username if executed by a user
            if log.executed_by_user_id:
                user = db.query(User).filter(User.id == log.executed_by_user_id).first()
                if user:
                    log_data.executed_by_username = user.username
            
            log_responses.append(log_data)

        return log_responses

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get backup schedule logs: {str(e)}",
        )


@router.get(
    "/scheduler/status",
    response_model=SchedulerStatusResponse,
)
async def get_scheduler_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get backup scheduler status (admin only)
    
    Returns the current status of the backup scheduler including
    total schedules, enabled schedules, and system information.
    """
    try:
        # Only admins can view scheduler status
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view scheduler status",
            )

        # Get all schedules
        all_schedules = await backup_scheduler.list_schedules(db=db)
        enabled_schedules = await backup_scheduler.list_schedules(db=db, enabled_only=True)

        # Find next execution time
        next_execution = None
        if enabled_schedules:
            next_times = [s.next_backup_at for s in enabled_schedules if s.next_backup_at]
            if next_times:
                next_execution = min(next_times)

        return SchedulerStatusResponse(
            is_running=backup_scheduler.is_running,
            total_schedules=len(all_schedules),
            enabled_schedules=len(enabled_schedules),
            cache_size=backup_scheduler.cache_size,
            next_execution=next_execution,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduler status: {str(e)}",
        )


@router.get(
    "/scheduler/schedules",
    response_model=List[BackupScheduleResponse],
)
async def list_all_backup_schedules(
    enabled_only: bool = Query(False, description="Only return enabled schedules"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all backup schedules (admin only)
    
    Returns a list of all backup schedules in the system.
    Only admins can access this endpoint.
    """
    try:
        # Only admins can list all schedules
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can list all backup schedules",
            )

        schedules = await backup_scheduler.list_schedules(db=db, enabled_only=enabled_only)

        return [BackupScheduleResponse.from_orm(schedule) for schedule in schedules]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list backup schedules: {str(e)}",
        )