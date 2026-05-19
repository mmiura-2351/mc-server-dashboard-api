"""Pure domain entities for the audit module.

Mirrors the entity style established by `app.users.domain.entities`
and `app.versions.domain.entities`: framework-free dataclasses that
the application/api layers exchange instead of ORM rows.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class AuditLogEntity:
    """A single audit log row, independent of how it is persisted."""

    id: int
    user_id: Optional[int]
    action: str
    resource_type: str
    resource_id: Optional[int]
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    created_at: Optional[datetime]
    # `user.email` is denormalised here so the router can avoid a second
    # round trip. Populated by adapters that join `users`; `None` when
    # the user has been deleted or no join is performed.
    user_email: Optional[str] = None


@dataclass(frozen=True)
class AuditEventCommand:
    """Input to `AuditWriter.record`.

    The adapter is responsible for routing this either through the
    request-scoped middleware tracker (batch flush) or directly to the
    database. Errors must be swallowed — audit writes are fire-and-forget.
    """

    action: str
    resource_type: str
    resource_id: Optional[int] = None
    user_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None


@dataclass(frozen=True)
class LogFilters:
    """Filter set for `/audit/logs` and friends."""

    user_id: Optional[int] = None
    action: Optional[str] = None  # treated as a case-insensitive substring
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None


@dataclass(frozen=True)
class AuditStatistics:
    """DTO returned by `/audit/statistics`.

    Bundles the six aggregate queries the router used to issue directly
    so the router becomes a single `service.get_statistics()` call.
    """

    total_logs: int
    recent_logs_24h: int
    security_events_7d: int
    most_active_users_30d: List[Tuple[Optional[int], int]]  # (user_id, count)
    most_common_actions_30d: List[Tuple[str, int]]
    resource_type_distribution_30d: List[Tuple[str, int]]
