import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.audit.models import AuditLog
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

# Context variables for audit tracking per request
request_id_context: ContextVar[str] = ContextVar("request_id")
user_id_context: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
ip_address_context: ContextVar[Optional[str]] = ContextVar("ip_address", default=None)


class AuditTracker:
    """Helper class to track audit events during request processing"""

    def __init__(
        self,
        request_id: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
    ):
        self.request_id = request_id
        self.user_id = user_id
        self.ip_address = ip_address
        self.audit_events: list[Dict[str, Any]] = []

    def add_event(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        sensitive_data_filter: bool = True,
    ):
        """Add an audit event to be logged"""
        # Use context user_id if not explicitly provided
        effective_user_id = user_id or self.user_id

        # Filter sensitive data if requested
        filtered_details = (
            self._filter_sensitive_data(details)
            if sensitive_data_filter and details
            else details
        )

        event = {
            "request_id": self.request_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": filtered_details,
            "user_id": effective_user_id,
            "ip_address": self.ip_address,
            "timestamp": time.time(),
        }
        self.audit_events.append(event)

        # Also log immediately for critical events
        if action in CRITICAL_ACTIONS:
            logger.warning(
                f"CRITICAL AUDIT EVENT - Request: {self.request_id}, "
                f"User: {effective_user_id}, Action: {action}, "
                f"Resource: {resource_type}:{resource_id}, IP: {self.ip_address}"
            )

    def _filter_sensitive_data(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Filter out sensitive information from audit details"""
        if not details:
            return details

        filtered = {}
        for key, value in details.items():
            # Filter sensitive fields
            if any(sensitive in key.lower() for sensitive in SENSITIVE_FIELDS):
                filtered[key] = "[FILTERED]"
            elif isinstance(value, dict):
                filtered[key] = self._filter_sensitive_data(value)
            elif isinstance(value, str) and len(value) > 1000:
                # Truncate very long strings (e.g., large config files)
                filtered[key] = value[:1000] + "...[TRUNCATED]"
            else:
                filtered[key] = value
        return filtered

    async def flush_events(self):
        """Persist all audit events to database"""
        if not self.audit_events:
            return

        db = SessionLocal()
        try:
            for event in self.audit_events:
                audit_log = AuditLog.create_log(
                    action=event["action"],
                    resource_type=event["resource_type"],
                    user_id=event["user_id"],
                    resource_id=event["resource_id"],
                    details=event["details"],
                    ip_address=event["ip_address"],
                )
                db.add(audit_log)

            db.commit()
            logger.debug(
                f"Persisted {len(self.audit_events)} audit events for request {self.request_id}"
            )

        except Exception as e:
            logger.error(
                f"Failed to persist audit events for request {self.request_id}: {e}"
            )
            db.rollback()
        finally:
            db.close()


# Configuration for audit behavior
SENSITIVE_FIELDS = [
    "password",
    "token",
    "secret",
    "key",
    "auth",
    "credential",
    "private",
    "sensitive",
    "confidential",
    "jwt",
    "refresh",
]

CRITICAL_ACTIONS = [
    "user_delete",
    "server_delete",
    "backup_delete",
    "role_change",
    "user_approve",
    "server_command",
    "file_delete",
    "admin_action",
]

AUDITABLE_ENDPOINTS = {
    # Authentication endpoints
    "POST /api/v1/auth/token": "auth_login",
    "POST /api/v1/auth/logout": "auth_logout",
    "POST /api/v1/auth/refresh": "auth_refresh",
    # User management
    "POST /api/v1/users/register": "user_register",
    "POST /api/v1/users/approve/{user_id}": "user_approve",
    "PUT /api/v1/users/role/{user_id}": "user_role_change",
    "DELETE /api/v1/users/{user_id}": "user_delete",
    "PUT /api/v1/users/{user_id}": "user_update",
    # Server management
    "POST /api/v1/servers": "server_create",
    "PUT /api/v1/servers/{server_id}": "server_update",
    "DELETE /api/v1/servers/{server_id}": "server_delete",
    "POST /api/v1/servers/{server_id}/start": "server_start",
    "POST /api/v1/servers/{server_id}/stop": "server_stop",
    "POST /api/v1/servers/{server_id}/restart": "server_restart",
    "POST /api/v1/servers/{server_id}/command": "server_command",
    "POST /api/v1/servers/{server_id}/force-stop": "server_force_stop",
    # Backup management
    "POST /api/v1/backups/{server_id}": "backup_create",
    "DELETE /api/v1/backups/{backup_id}": "backup_delete",
    "POST /api/v1/backups/{backup_id}/restore": "backup_restore",
    "POST /api/v1/backups/scheduler/servers/{server_id}/schedule": "backup_schedule",
    "DELETE /api/v1/backups/scheduler/servers/{server_id}/schedule/{schedule_id}": "backup_schedule_delete",
    # Group management
    "POST /api/v1/groups": "group_create",
    "PUT /api/v1/groups/{group_id}": "group_update",
    "DELETE /api/v1/groups/{group_id}": "group_delete",
    "POST /api/v1/groups/{group_id}/players": "group_player_add",
    "DELETE /api/v1/groups/{group_id}/players/{player_id}": "group_player_remove",
    "POST /api/v1/groups/{group_id}/attach/{server_id}": "group_attach_server",
    "DELETE /api/v1/groups/{group_id}/attach/{server_id}": "group_detach_server",
    # Template management
    "POST /api/v1/templates": "template_create",
    "PUT /api/v1/templates/{template_id}": "template_update",
    "DELETE /api/v1/templates/{template_id}": "template_delete",
    "POST /api/v1/templates/{template_id}/clone": "template_clone",
    # File management (high-risk operations)
    "PUT /api/v1/files/{server_id}": "file_write",
    "DELETE /api/v1/files/{server_id}": "file_delete",
}


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware for comprehensive audit logging and request correlation"""

    def __init__(
        self,
        app,
        enabled: bool = True,
        log_all_requests: bool = False,
        exclude_health_checks: bool = True,
    ):
        super().__init__(app)
        self.enabled = enabled
        self.log_all_requests = log_all_requests
        self.exclude_health_checks = exclude_health_checks

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # Skip audit logging for health check and monitoring endpoints
        if self.exclude_health_checks and request.url.path in [
            "/health",
            "/api/v1/health",
            "/metrics",
            "/api/v1/metrics",
            "/monitoring",
            "/docs",
            "/openapi.json",
        ]:
            return await call_next(request)

        # Generate correlation ID for this request
        correlation_id = str(uuid.uuid4())
        request_id_context.set(correlation_id)

        # Extract IP address
        ip_address = self._extract_ip_address(request)
        ip_address_context.set(ip_address)

        # Initialize audit tracker
        audit_tracker = AuditTracker(request_id=correlation_id, ip_address=ip_address)

        # Store audit tracker in request state for access by endpoints
        request.state.audit_tracker = audit_tracker

        # Determine if this endpoint should be audited
        endpoint_pattern = self._normalize_endpoint_pattern(
            request.method, request.url.path
        )
        should_audit = endpoint_pattern in AUDITABLE_ENDPOINTS or self.log_all_requests

        # Extract user info if available (before processing request)
        user_id = await self._extract_user_id(request)
        user_id_context.set(user_id)
        audit_tracker.user_id = user_id

        start_time = time.time()

        try:
            # Process the request
            response = await call_next(request)

            # Log successful audit event if this is an auditable endpoint
            if should_audit and 200 <= response.status_code < 300:
                action = AUDITABLE_ENDPOINTS.get(endpoint_pattern, "api_request")
                await self._log_successful_request(
                    audit_tracker, request, response, action, endpoint_pattern
                )

        except Exception as e:
            # Log failed request
            if should_audit:
                action = AUDITABLE_ENDPOINTS.get(endpoint_pattern, "api_request")
                await self._log_failed_request(
                    audit_tracker, request, action, endpoint_pattern, str(e)
                )

            # Re-raise the exception
            raise

        finally:
            # Always flush audit events
            try:
                await audit_tracker.flush_events()
            except Exception as e:
                logger.error(
                    f"Failed to flush audit events for request {correlation_id}: {e}"
                )

        # Add correlation ID to response headers
        response.headers["X-Request-ID"] = correlation_id

        # Log request summary
        duration = time.time() - start_time
        logger.info(
            f"REQUEST {correlation_id} - {request.method} {request.url.path} "
            f"- {response.status_code} - {duration * 1000:.2f}ms - User: {user_id} - IP: {ip_address}"
        )

        return response

    def _extract_ip_address(self, request: Request) -> Optional[str]:
        """Extract client IP address from request"""
        # Check for forwarded headers first (for reverse proxy setups)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP if multiple are present
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if hasattr(request, "client") and request.client:
            return request.client.host

        return None

    async def _extract_user_id(self, request: Request) -> Optional[int]:
        """Extract user ID from request if authenticated"""
        try:
            # Look for Authorization header
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return None

            # We can't decode the JWT here without importing auth dependencies
            # Instead, we'll rely on the endpoint to set the user_id in context
            # This is a limitation but prevents circular imports
            return None

        except Exception as e:
            logger.debug(f"Failed to extract user ID from request: {e}")
            return None

    def _normalize_endpoint_pattern(self, method: str, path: str) -> str:
        """Normalize endpoint path to match audit configuration"""
        import re

        # Replace numeric IDs with {id} placeholders
        normalized_path = re.sub(r"/\d+", "/{id}", path)

        # Handle specific ID patterns
        normalized_path = (
            re.sub(r"\{id\}", "{user_id}", normalized_path)
            if "/users/" in normalized_path
            else normalized_path
        )
        normalized_path = (
            re.sub(r"\{id\}", "{server_id}", normalized_path)
            if "/servers/" in normalized_path
            else normalized_path
        )
        normalized_path = (
            re.sub(r"\{id\}", "{backup_id}", normalized_path)
            if "/backups/" in normalized_path
            else normalized_path
        )
        normalized_path = (
            re.sub(r"\{id\}", "{group_id}", normalized_path)
            if "/groups/" in normalized_path
            else normalized_path
        )
        normalized_path = (
            re.sub(r"\{id\}", "{template_id}", normalized_path)
            if "/templates/" in normalized_path
            else normalized_path
        )
        normalized_path = (
            re.sub(r"\{id\}", "{schedule_id}", normalized_path)
            if "/schedule/" in normalized_path
            else normalized_path
        )
        normalized_path = (
            re.sub(r"\{id\}", "{player_id}", normalized_path)
            if "/players/" in normalized_path
            else normalized_path
        )

        return f"{method} {normalized_path}"

    async def _log_successful_request(
        self,
        audit_tracker: AuditTracker,
        request: Request,
        response: Response,
        action: str,
        endpoint_pattern: str,
    ):
        """Log successful request as audit event"""
        details = {
            "endpoint": endpoint_pattern,
            "status_code": response.status_code,
            "method": request.method,
            "path": str(request.url.path),
            "query_params": dict(request.query_params),
        }

        # Add request body for auditable actions (but filter sensitive data)
        if hasattr(request, "body") and request.method in ["POST", "PUT", "PATCH"]:
            try:
                # Note: request.body() can only be called once, so we won't capture it here
                # to avoid interfering with endpoint processing
                details["has_request_body"] = True
            except Exception:
                pass

        audit_tracker.add_event(
            action=f"{action}_success",
            resource_type="api_endpoint",
            details=details,
        )

    async def _log_failed_request(
        self,
        audit_tracker: AuditTracker,
        request: Request,
        action: str,
        endpoint_pattern: str,
        error_message: str,
    ):
        """Log failed request as audit event"""
        details = {
            "endpoint": endpoint_pattern,
            "method": request.method,
            "path": str(request.url.path),
            "query_params": dict(request.query_params),
            "error": error_message[:500],  # Truncate long error messages
        }

        audit_tracker.add_event(
            action=f"{action}_failure",
            resource_type="api_endpoint",
            details=details,
        )


def get_request_id() -> Optional[str]:
    """Get current request correlation ID"""
    try:
        return request_id_context.get()
    except LookupError:
        return None


def get_current_user_id() -> Optional[int]:
    """Get current request user ID"""
    try:
        return user_id_context.get()
    except LookupError:
        return None


def get_audit_tracker(request: Request) -> Optional[AuditTracker]:
    """Get audit tracker from current request"""
    if hasattr(request, "state") and hasattr(request.state, "audit_tracker"):
        return request.state.audit_tracker
    return None


def log_audit_event(
    request: Request,
    action: str,
    resource_type: str,
    resource_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
):
    """Log an audit event for the current request"""
    audit_tracker = get_audit_tracker(request)
    if audit_tracker:
        audit_tracker.add_event(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            user_id=user_id,
        )
    else:
        logger.warning(f"No audit tracker available for logging action: {action}")
