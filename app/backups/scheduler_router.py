"""Backup scheduler REST API router.

Uses `BackupSchedulerService` via the lifespan-scoped
`get_backup_scheduler_service` dependency. The legacy `db.query` paths
for `BackupScheduleLog` and `User` are gone (the adapter joins both
via `joinedload(executed_by)`).
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.backups.api._mappers import (
    backup_schedule_entity_to_response,
    backup_schedule_log_entity_to_response,
    scheduler_status_to_response,
)
from app.backups.api.dependencies import get_backup_scheduler_service
from app.backups.application.scheduler import BackupSchedulerService
from app.backups.domain.exceptions import (
    BackupScheduleAlreadyExistsError,
    BackupScheduleNotFoundError,
)
from app.backups.schemas import (
    BackupScheduleLogResponse,
    BackupScheduleRequest,
    BackupScheduleResponse,
    BackupScheduleUpdateRequest,
    SchedulerStatusResponse,
)
from app.core.database import get_db
from app.servers.api.dependencies import get_authorization_service
from app.servers.application.authorization import AuthorizationService
from app.users.domain.value_objects import Role
from app.users.models import User

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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Create a backup schedule for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

        entity = await scheduler.create_schedule(
            server_id=server_id,
            interval_hours=request.interval_hours,
            max_backups=request.max_backups,
            enabled=request.enabled,
            only_when_running=request.only_when_running,
            executed_by_user_id=current_user.id,
        )
        return backup_schedule_entity_to_response(entity)

    except BackupScheduleAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except BackupScheduleNotFoundError as e:
        # server-not-found case (raised from the create path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Get backup schedule for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

        entity = await scheduler.get_schedule(server_id=server_id)
        if not entity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No backup schedule found for server {server_id}",
            )
        return backup_schedule_entity_to_response(entity)

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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Update backup schedule for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

        entity = await scheduler.update_schedule(
            server_id=server_id,
            interval_hours=request.interval_hours,
            max_backups=request.max_backups,
            enabled=request.enabled,
            only_when_running=request.only_when_running,
            executed_by_user_id=current_user.id,
        )
        return backup_schedule_entity_to_response(entity)

    except BackupScheduleNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Delete backup schedule for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

        success = await scheduler.delete_schedule(
            server_id=server_id, executed_by_user_id=current_user.id
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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """Get backup schedule logs for a server."""
    try:
        await auth.check_server_access(server_id, current_user)

        logs = await scheduler.list_logs_for_server(server_id, page=page, size=size)
        return [backup_schedule_log_entity_to_response(log) for log in logs]

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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
):
    """Get backup scheduler status (admin only)."""
    try:
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view scheduler status",
            )

        all_schedules = await scheduler.list_schedules()
        enabled_schedules = await scheduler.list_schedules(enabled_only=True)

        return scheduler_status_to_response(scheduler, all_schedules, enabled_schedules)

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
    scheduler: BackupSchedulerService = Depends(get_backup_scheduler_service),
):
    """List all backup schedules (admin only)."""
    try:
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can list all backup schedules",
            )

        schedules = await scheduler.list_schedules(enabled_only=enabled_only)
        return [backup_schedule_entity_to_response(s) for s in schedules]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list backup schedules: {str(e)}",
        )
