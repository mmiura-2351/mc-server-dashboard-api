import logging
from typing import Any, Dict, List, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.middleware.audit_middleware import (
    get_audit_tracker,
    get_current_user_id,
)

logger = logging.getLogger(__name__)


class AuditService:
    """Service for comprehensive audit logging throughout the application"""

    @staticmethod
    def log_authentication_event(
        db: Session,
        request: Request,
        action: str,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ):
        """Log authentication-related events"""
        audit_action = f"auth_{action}_{'success' if success else 'failure'}"

        audit_details = {
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            "success": success,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=audit_action,
            resource_type="authentication",
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_user_management_event(
        db: Session,
        request: Request,
        action: str,
        target_user_id: int,
        details: Optional[Dict[str, Any]] = None,
        current_user_id: Optional[int] = None,
    ):
        """Log user management events (creation, approval, role changes, deletion)"""
        current_user_id = current_user_id or get_current_user_id()

        audit_details = {
            "target_user_id": target_user_id,
            "performed_by": current_user_id,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"user_{action}",
            resource_type="user",
            resource_id=target_user_id,
            user_id=current_user_id,
            details=audit_details,
        )

    @staticmethod
    def log_server_event(
        db: Session,
        request: Request,
        action: str,
        server_id: int,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log server management events"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "server_id": server_id,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"server_{action}",
            resource_type="server",
            resource_id=server_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_server_command_event(
        db: Session,
        request: Request,
        server_id: int,
        command: str,
        success: bool = True,
        output: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        """Log server command execution (critical security event)"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "server_id": server_id,
            "command": command,
            "success": success,
            "output_length": len(output) if output else 0,
            # Note: We don't log full output to avoid sensitive data
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"server_command_{'success' if success else 'failure'}",
            resource_type="server",
            resource_id=server_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_backup_event(
        db: Session,
        request: Request,
        action: str,
        server_id: Optional[int] = None,
        backup_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log backup-related events"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "server_id": server_id,
            "backup_id": backup_id,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"backup_{action}",
            resource_type="backup",
            resource_id=backup_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_group_event(
        db: Session,
        request: Request,
        action: str,
        group_id: int,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log group management events"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "group_id": group_id,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"group_{action}",
            resource_type="group",
            resource_id=group_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_template_event(
        db: Session,
        request: Request,
        action: str,
        template_id: int,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log template management events"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "template_id": template_id,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"template_{action}",
            resource_type="template",
            resource_id=template_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_file_event(
        db: Session,
        request: Request,
        action: str,
        server_id: int,
        file_path: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log file management events (high security relevance)"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "server_id": server_id,
            "file_path": file_path,
            "file_name": file_path.split("/")[-1] if "/" in file_path else file_path,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"file_{action}",
            resource_type="file",
            resource_id=server_id,  # Use server_id as resource_id for files
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_permission_check(
        db: Session,
        request: Request,
        resource_type: str,
        resource_id: Optional[int],
        permission: str,
        granted: bool,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log permission check results (for security monitoring)"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "permission": permission,
            "granted": granted,
            "resource_type": resource_type,
            "resource_id": resource_id,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"permission_check_{'granted' if granted else 'denied'}",
            resource_type="permission",
            resource_id=resource_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_admin_action(
        db: Session,
        request: Request,
        action: str,
        target_resource_type: str,
        target_resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log administrative actions (highest priority for audit)"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "target_resource_type": target_resource_type,
            "target_resource_id": target_resource_id,
            "admin_action": action,
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"admin_{action}",
            resource_type="admin_action",
            resource_id=target_resource_id,
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def log_security_event(
        db: Session,
        request: Request,
        event_type: str,
        severity: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        """Log security-related events (suspicious activity, failed access, etc.)"""
        user_id = user_id or get_current_user_id()

        audit_details = {
            "event_type": event_type,
            "severity": severity,
            "request_path": str(request.url.path),
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            **(details or {}),
        }

        AuditService._log_event(
            db=db,
            request=request,
            action=f"security_{event_type}",
            resource_type="security",
            user_id=user_id,
            details=audit_details,
        )

    @staticmethod
    def _log_event(
        db: Session,
        request: Request,
        action: str,
        resource_type: str,
        resource_id: Optional[int] = None,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Internal method to create and persist audit log entry"""
        try:
            # Try to use the audit tracker from middleware first
            audit_tracker = get_audit_tracker(request)
            if audit_tracker:
                # Add to middleware tracker for batch processing
                audit_tracker.add_event(
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                    user_id=user_id,
                )
            else:
                # Direct database logging if no middleware tracker available
                ip_address = AuditService._extract_ip_address(request)

                audit_log = AuditLog.create_log(
                    action=action,
                    resource_type=resource_type,
                    user_id=user_id,
                    resource_id=resource_id,
                    details=details,
                    ip_address=ip_address,
                )

                db.add(audit_log)
                db.commit()

                logger.debug(
                    f"Created audit log: {action} on {resource_type}:{resource_id} by user {user_id}"
                )

        except Exception as e:
            logger.error(
                f"Failed to log audit event: {action} on {resource_type}:{resource_id} - {e}"
            )
            if hasattr(db, "rollback"):
                db.rollback()

    @staticmethod
    def _extract_ip_address(request: Request) -> Optional[str]:
        """Extract client IP address from request"""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if hasattr(request, "client") and request.client:
            return request.client.host

        return None

    @staticmethod
    def get_audit_logs(
        db: Session,
        user_id: Optional[int] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        """Retrieve audit logs with filtering options"""
        query = db.query(AuditLog)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action.ilike(f"%{action}%"))
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)
        if resource_id:
            query = query.filter(AuditLog.resource_id == resource_id)

        return (
            query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
        )

    @staticmethod
    def get_security_alerts(
        db: Session,
        severity: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditLog]:
        """Get recent security-related audit events"""
        query = db.query(AuditLog).filter(AuditLog.resource_type == "security")

        if severity:
            query = query.filter(AuditLog.details.op("->>")('"severity"') == severity)

        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_user_activity(
        db: Session,
        user_id: int,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Get recent activity for a specific user"""
        return (
            db.query(AuditLog)
            .filter(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
