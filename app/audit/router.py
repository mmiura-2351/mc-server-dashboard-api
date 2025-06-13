from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.service import AuditService
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.services.authorization_service import AuthorizationService
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

    # Include user information if available
    user_email: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    logs: List[AuditLogResponse]
    total_count: int
    page: int
    page_size: int


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
):
    """
    Get audit logs with filtering and pagination.
    Only admins can view all logs, other users can only view their own logs.
    """
    authorization_service = AuthorizationService()

    # Check if user can view audit logs
    if not authorization_service.is_admin(current_user):
        # Non-admin users can only view their own audit logs
        if user_id is not None and user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="You can only view your own audit logs"
            )
        user_id = current_user.id

    # Log this audit log access
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

    # Calculate offset
    offset = (page - 1) * page_size

    # Get audit logs
    logs = AuditService.get_audit_logs(
        db=db,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        limit=page_size,
        offset=offset,
    )

    # Get total count for pagination
    query = db.query(AuditLog)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)

    total_count = query.count()

    # Convert to response format with user information
    log_responses = []
    for log in logs:
        log_dict = {
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.get_details(),
            "ip_address": log.ip_address,
            "created_at": log.created_at,
            "user_email": log.user.email if log.user else None,
        }
        log_responses.append(AuditLogResponse(**log_dict))

    return AuditLogListResponse(
        logs=log_responses,
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
):
    """
    Get recent security alerts from audit logs.
    Only admins can access security alerts.
    """
    authorization_service = AuthorizationService()

    # Only admins can view security alerts
    if not authorization_service.is_admin(current_user):
        raise HTTPException(
            status_code=403, detail="Only administrators can view security alerts"
        )

    # Log this security alert access
    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_security_alerts",
        target_resource_type="security_alert",
        details={"severity_filter": severity, "limit": limit},
        user_id=current_user.id,
    )

    # Get security alerts
    alerts = AuditService.get_security_alerts(
        db=db,
        severity=severity,
        limit=limit,
    )

    # Convert to response format
    alert_responses = []
    for alert in alerts:
        alert_dict = {
            "id": alert.id,
            "user_id": alert.user_id,
            "action": alert.action,
            "resource_type": alert.resource_type,
            "resource_id": alert.resource_id,
            "details": alert.get_details(),
            "ip_address": alert.ip_address,
            "created_at": alert.created_at,
            "user_email": alert.user.email if alert.user else None,
        }
        alert_responses.append(AuditLogResponse(**alert_dict))

    return alert_responses


@router.get("/user/{user_id}/activity", response_model=List[AuditLogResponse])
async def get_user_activity(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=200, description="Maximum number of activity logs"),
):
    """
    Get recent activity for a specific user.
    Users can view their own activity, admins can view any user's activity.
    """
    authorization_service = AuthorizationService()

    # Check permissions
    if not authorization_service.is_admin(current_user) and user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own activity")

    # Verify target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Log this activity access
    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_user_activity",
        target_resource_type="user",
        target_resource_id=user_id,
        details={"target_user_email": target_user.email, "limit": limit},
        user_id=current_user.id,
    )

    # Get user activity
    activities = AuditService.get_user_activity(
        db=db,
        user_id=user_id,
        limit=limit,
    )

    # Convert to response format
    activity_responses = []
    for activity in activities:
        activity_dict = {
            "id": activity.id,
            "user_id": activity.user_id,
            "action": activity.action,
            "resource_type": activity.resource_type,
            "resource_id": activity.resource_id,
            "details": activity.get_details(),
            "ip_address": activity.ip_address,
            "created_at": activity.created_at,
            "user_email": activity.user.email if activity.user else None,
        }
        activity_responses.append(AuditLogResponse(**activity_dict))

    return activity_responses


@router.get("/statistics")
async def get_audit_statistics(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get audit log statistics and summaries.
    Only admins can access audit statistics.
    """
    authorization_service = AuthorizationService()

    # Only admins can view audit statistics
    if not authorization_service.is_admin(current_user):
        raise HTTPException(
            status_code=403, detail="Only administrators can view audit statistics"
        )

    # Log this statistics access
    AuditService.log_admin_action(
        db=db,
        request=request,
        action="view_audit_statistics",
        target_resource_type="audit_statistics",
        user_id=current_user.id,
    )

    # Get various statistics
    from datetime import timedelta

    from sqlalchemy import func

    # Total audit logs
    total_logs = db.query(AuditLog).count()

    # Logs in last 24 hours
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    recent_logs = db.query(AuditLog).filter(AuditLog.created_at >= yesterday).count()

    # Most active users (last 30 days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    active_users = (
        db.query(AuditLog.user_id, func.count(AuditLog.id).label("activity_count"))
        .filter(AuditLog.created_at >= thirty_days_ago)
        .filter(AuditLog.user_id.isnot(None))
        .group_by(AuditLog.user_id)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
        .all()
    )

    # Most common actions (last 30 days)
    common_actions = (
        db.query(AuditLog.action, func.count(AuditLog.id).label("count"))
        .filter(AuditLog.created_at >= thirty_days_ago)
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
        .all()
    )

    # Resource type distribution (last 30 days)
    resource_distribution = (
        db.query(AuditLog.resource_type, func.count(AuditLog.id).label("count"))
        .filter(AuditLog.created_at >= thirty_days_ago)
        .group_by(AuditLog.resource_type)
        .order_by(func.count(AuditLog.id).desc())
        .all()
    )

    # Security events count (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    security_events = (
        db.query(AuditLog)
        .filter(AuditLog.created_at >= week_ago)
        .filter(AuditLog.resource_type == "security")
        .count()
    )

    return {
        "total_audit_logs": total_logs,
        "recent_logs_24h": recent_logs,
        "security_events_7d": security_events,
        "most_active_users_30d": [
            {"user_id": user_id, "activity_count": count}
            for user_id, count in active_users
        ],
        "most_common_actions_30d": [
            {"action": action, "count": count} for action, count in common_actions
        ],
        "resource_type_distribution_30d": [
            {"resource_type": resource_type, "count": count}
            for resource_type, count in resource_distribution
        ],
        "statistics_generated_at": datetime.now(timezone.utc),
    }
