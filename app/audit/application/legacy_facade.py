"""Sync compatibility facade preserving the pre-#223 static `AuditService` API.

The 30+ existing callers (in `app/auth/api/router.py`,
`app/servers/routers/control.py`, `app/services/authorization_service.py`,
and the audit router itself) invoke `AuditService.log_*(request=..., ...)`
synchronously. Migrating those callsites to FastAPI `Depends(AuditWriter)`
is deferred to the per-domain refactors (#224-#228).

Each `log_*` static method builds a `SqlAlchemyAuditWriter` from the
request-scoped `AuditTracker` (preserves the middleware batch path)
and delegates to `writer.record(...)`.

The pre-#223 read methods (`get_audit_logs`, `get_security_alerts`,
`get_user_activity`) are intentionally **not** carried over: their
only consumers were the audit router (migrated to `AuditQueryService`
in this PR) and `tests/integration/test_audit.py` (also migrated).
Anyone re-introducing a read should go through `AuditQueryService`.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import Request

from app.audit.adapters.repository import SqlAlchemyAuditWriter
from app.audit.domain.entities import AuditEventCommand
from app.middleware.audit_middleware import (
    get_audit_tracker,
    get_current_user_id,
)

logger = logging.getLogger(__name__)


def _extract_ip_address(request: Request) -> Optional[str]:
    """Extract client IP address from request headers / direct client."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    if hasattr(request, "client") and request.client:
        return request.client.host

    return None


def _writer(request: Request) -> SqlAlchemyAuditWriter:
    """Build a writer for a single legacy call.

    The writer manages its own session via `session_factory` — see #240
    and `SqlAlchemyAuditWriter` for the transaction-isolation rationale.
    """
    return SqlAlchemyAuditWriter(tracker=get_audit_tracker(request))


class AuditService:
    """Compat facade: same surface as the pre-#223 `AuditService`."""

    @staticmethod
    def log_authentication_event(
        request: Request,
        action: str,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ):
        audit_details = {
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            "success": success,
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"auth_{action}_{'success' if success else 'failure'}",
                resource_type="authentication",
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_user_management_event(
        request: Request,
        action: str,
        target_user_id: int,
        details: Optional[Dict[str, Any]] = None,
        current_user_id: Optional[int] = None,
    ):
        current_user_id = current_user_id or get_current_user_id()
        audit_details = {
            "target_user_id": target_user_id,
            "performed_by": current_user_id,
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"user_{action}",
                resource_type="user",
                resource_id=target_user_id,
                user_id=current_user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_server_event(
        request: Request,
        action: str,
        server_id: int,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {"server_id": server_id, **(details or {})}
        _writer(request).record(
            AuditEventCommand(
                action=f"server_{action}",
                resource_type="server",
                resource_id=server_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_server_command_event(
        request: Request,
        server_id: int,
        command: str,
        success: bool = True,
        output: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {
            "server_id": server_id,
            "command": command,
            "success": success,
            "output_length": len(output) if output else 0,
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"server_command_{'success' if success else 'failure'}",
                resource_type="server",
                resource_id=server_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_backup_event(
        request: Request,
        action: str,
        server_id: Optional[int] = None,
        backup_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {
            "server_id": server_id,
            "backup_id": backup_id,
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"backup_{action}",
                resource_type="backup",
                resource_id=backup_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_group_event(
        request: Request,
        action: str,
        group_id: int,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {"group_id": group_id, **(details or {})}
        _writer(request).record(
            AuditEventCommand(
                action=f"group_{action}",
                resource_type="group",
                resource_id=group_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_template_event(
        request: Request,
        action: str,
        template_id: int,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {"template_id": template_id, **(details or {})}
        _writer(request).record(
            AuditEventCommand(
                action=f"template_{action}",
                resource_type="template",
                resource_id=template_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_file_event(
        request: Request,
        action: str,
        server_id: int,
        file_path: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {
            "server_id": server_id,
            "file_path": file_path,
            "file_name": file_path.split("/")[-1] if "/" in file_path else file_path,
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"file_{action}",
                resource_type="file",
                resource_id=server_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_permission_check(
        request: Request,
        resource_type: str,
        resource_id: Optional[int],
        permission: str,
        granted: bool,
        user_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {
            "permission": permission,
            "granted": granted,
            "resource_type": resource_type,
            "resource_id": resource_id,
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"permission_check_{'granted' if granted else 'denied'}",
                resource_type="permission",
                resource_id=resource_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_admin_action(
        request: Request,
        action: str,
        target_resource_type: str,
        target_resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {
            "target_resource_type": target_resource_type,
            "target_resource_id": target_resource_id,
            "admin_action": action,
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"admin_{action}",
                resource_type="admin_action",
                resource_id=target_resource_id,
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )

    @staticmethod
    def log_security_event(
        request: Request,
        event_type: str,
        severity: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ):
        user_id = user_id or get_current_user_id()
        audit_details = {
            "event_type": event_type,
            "severity": severity,
            "request_path": str(request.url.path),
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            **(details or {}),
        }
        _writer(request).record(
            AuditEventCommand(
                action=f"security_{event_type}",
                resource_type="security",
                user_id=user_id,
                details=audit_details,
                ip_address=_extract_ip_address(request),
            )
        )


__all__ = ["AuditService"]
