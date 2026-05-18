"""Audit API router (post-#223).

All direct `db.query(...)` access removed — the router now consumes
`AuditQueryService` for reads and the legacy static
`AuditService.log_admin_action` for audit-of-audit writes (the write
surface migrates per-domain in #224-#228).

The User existence check on `/user/{user_id}/activity` is performed
through the `UserReadPort` published by #222 rather than touching
`app.users.models.User` directly.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.audit.api.dependencies import get_audit_query_service, get_user_read_port
from app.audit.application.query_service import AuditQueryService
from app.audit.domain.entities import AuditLogEntity, LogFilters
from app.audit.service import AuditService
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.services.authorization_service import AuthorizationService
from app.users.domain.ports import UserReadPort
from app.users.models import User

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    resource_type: str
    resource_id: Optional[int]
    details: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime
    user_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    logs: List[AuditLogResponse]
    total_count: int
    page: int
    page_size: int


def _entity_to_response(entity: AuditLogEntity) -> AuditLogResponse:
    # `created_at` is non-Optional on the response but Optional on the
    # entity (matches the DB column nullability). In practice the DB
    # always populates it via `server_default=func.now()`, so a
    # `None` here would indicate a row created mid-write — surface it
    # as the current timestamp rather than crashing the response.
    return AuditLogResponse(
        id=entity.id,
        user_id=entity.user_id,
        action=entity.action,
        resource_type=entity.resource_type,
        resource_id=entity.resource_id,
        details=entity.details,
        ip_address=entity.ip_address,
        created_at=entity.created_at or datetime.now(timezone.utc),
        user_email=entity.user_email,
    )


@router.get("/logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of logs per page"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[int] = Query(None, description="Filter by resource ID"),
    service: AuditQueryService = Depends(get_audit_query_service),
):
    """
    Get audit logs with filtering and pagination.
    Only admins can view all logs, other users can only view their own logs.
    """
    authorization_service = AuthorizationService()

    if not authorization_service.is_admin(current_user):
        if user_id is not None and user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="You can only view your own audit logs"
            )
        user_id = current_user.id

    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_audit_logs",
        target_resource_type="audit_log",
        details={
            "filters": {
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
            },
            "pagination": {"page": page, "page_size": page_size},
        },
        user_id=current_user.id,
    )

    filters = LogFilters(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    logs, total_count = await service.list_logs(filters, page=page, page_size=page_size)

    return AuditLogListResponse(
        logs=[_entity_to_response(log) for log in logs],
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


@router.get("/security-alerts", response_model=List[AuditLogResponse])
async def get_security_alerts(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    severity: Optional[str] = Query(
        None, description="Filter by severity (low, medium, high, critical)"
    ),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of alerts"),
    service: AuditQueryService = Depends(get_audit_query_service),
):
    """Recent security alerts (admin only)."""
    authorization_service = AuthorizationService()

    if not authorization_service.is_admin(current_user):
        raise HTTPException(
            status_code=403, detail="Only administrators can view security alerts"
        )

    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_security_alerts",
        target_resource_type="security_alert",
        details={"severity_filter": severity, "limit": limit},
        user_id=current_user.id,
    )

    alerts = await service.list_security_alerts(severity, limit)
    return [_entity_to_response(a) for a in alerts]


@router.get("/user/{user_id}/activity", response_model=List[AuditLogResponse])
async def get_user_activity(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=200, description="Maximum number of activity logs"),
    service: AuditQueryService = Depends(get_audit_query_service),
    user_read_port: UserReadPort = Depends(get_user_read_port),
):
    """Recent activity for a specific user.

    Users can view their own activity; admins can view any user's.
    """
    authorization_service = AuthorizationService()

    if not authorization_service.is_admin(current_user) and user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own activity")

    # Verify target user exists via the cross-domain UserReadPort
    # (published by #222) rather than reaching into `users.models.User`.
    target_user = await user_read_port.get_by_id(user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_user_activity",
        target_resource_type="user",
        target_resource_id=user_id,
        details={"target_user_email": target_user.email, "limit": limit},
        user_id=current_user.id,
    )

    activities = await service.list_user_activity(user_id, limit)
    return [_entity_to_response(a) for a in activities]


@router.get("/statistics")
async def get_audit_statistics(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: AuditQueryService = Depends(get_audit_query_service),
):
    """Audit log statistics and summaries (admin only)."""
    authorization_service = AuthorizationService()

    if not authorization_service.is_admin(current_user):
        raise HTTPException(
            status_code=403, detail="Only administrators can view audit statistics"
        )

    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_audit_statistics",
        target_resource_type="audit_statistics",
        user_id=current_user.id,
    )

    stats = await service.get_statistics()

    return {
        "total_audit_logs": stats.total_logs,
        "recent_logs_24h": stats.recent_logs_24h,
        "security_events_7d": stats.security_events_7d,
        "most_active_users_30d": [
            {"user_id": uid, "activity_count": count}
            for uid, count in stats.most_active_users_30d
        ],
        "most_common_actions_30d": [
            {"action": action, "count": count}
            for action, count in stats.most_common_actions_30d
        ],
        "resource_type_distribution_30d": [
            {"resource_type": rt, "count": count}
            for rt, count in stats.resource_type_distribution_30d
        ],
        "statistics_generated_at": datetime.now(timezone.utc),
    }
