"""Backwards-compatible re-export of the pre-#223 `AuditService` static API.

The implementation now lives in `app.audit.application.legacy_facade`.
30+ callers (`app/auth/api/router.py`, `app/servers/routers/control.py`,
`app/services/authorization_service.py`, tests) keep importing from
here unchanged. New code should inject the `AuditWriter` Port instead
— see `app/audit/domain/ports.py`.
"""

from app.audit.application.legacy_facade import AuditService

__all__ = ["AuditService"]
