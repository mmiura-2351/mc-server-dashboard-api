"""In-memory fakes for the audit domain Ports."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.audit.domain.entities import (
    AuditEventCommand,
    AuditLogEntity,
    AuditStatistics,
    LogFilters,
)


class FakeAuditWriter:
    """`AuditWriter` that just records the commands for assertions.

    The real writer's "error swallow" contract is preserved: this fake
    never raises either, so tests can use it interchangeably.
    """

    def __init__(self) -> None:
        self.events: List[AuditEventCommand] = []

    def record(self, command: AuditEventCommand) -> None:
        self.events.append(command)


class FakeAuditRepository:
    """Dict-backed `AuditRepository`."""

    def __init__(self) -> None:
        self._rows: Dict[int, AuditLogEntity] = {}
        self._next_id = 1

    def add(
        self,
        *,
        action: str,
        resource_type: str,
        user_id: Optional[int] = None,
        resource_id: Optional[int] = None,
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        created_at: Optional[datetime] = None,
        user_email: Optional[str] = None,
    ) -> AuditLogEntity:
        entity = AuditLogEntity(
            id=self._next_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            created_at=created_at or datetime.now(timezone.utc),
            user_email=user_email,
        )
        self._rows[self._next_id] = entity
        self._next_id += 1
        return entity

    def _filtered(self, filters: LogFilters) -> List[AuditLogEntity]:
        out = []
        for row in self._rows.values():
            if filters.user_id is not None and row.user_id != filters.user_id:
                continue
            if filters.action and filters.action.lower() not in row.action.lower():
                continue
            if filters.resource_type and row.resource_type != filters.resource_type:
                continue
            if filters.resource_id is not None and row.resource_id != filters.resource_id:
                continue
            out.append(row)
        return out

    async def list_logs(
        self,
        filters: LogFilters,
        *,
        limit: int,
        offset: int,
    ) -> List[AuditLogEntity]:
        rows = sorted(
            self._filtered(filters),
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return rows[offset : offset + limit]

    async def count_logs(self, filters: LogFilters) -> int:
        return len(self._filtered(filters))

    async def list_logs_with_count(
        self,
        filters: LogFilters,
        *,
        limit: int,
        offset: int,
    ) -> tuple[List[AuditLogEntity], int]:
        filtered = self._filtered(filters)
        rows = sorted(
            filtered,
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return rows[offset : offset + limit], len(filtered)

    async def list_security_alerts(
        self, severity: Optional[str], limit: int
    ) -> List[AuditLogEntity]:
        rows = [r for r in self._rows.values() if r.resource_type == "security"]
        if severity:
            rows = [
                r
                for r in rows
                if isinstance(r.details, dict) and r.details.get("severity") == severity
            ]
        rows.sort(
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return rows[:limit]

    async def list_user_activity(self, user_id: int, limit: int) -> List[AuditLogEntity]:
        rows = [r for r in self._rows.values() if r.user_id == user_id]
        rows.sort(
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return rows[:limit]

    async def get_statistics(self) -> AuditStatistics:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        thirty_days_ago = now - timedelta(days=30)
        week_ago = now - timedelta(days=7)

        total = len(self._rows)
        recent = sum(
            1 for r in self._rows.values() if r.created_at and r.created_at >= yesterday
        )
        security = sum(
            1
            for r in self._rows.values()
            if r.resource_type == "security" and r.created_at and r.created_at >= week_ago
        )

        recent_rows = [
            r
            for r in self._rows.values()
            if r.created_at and r.created_at >= thirty_days_ago
        ]
        active_users = Counter(r.user_id for r in recent_rows if r.user_id is not None)
        action_counts = Counter(r.action for r in recent_rows)
        rt_counts = Counter(r.resource_type for r in recent_rows)

        return AuditStatistics(
            total_logs=total,
            recent_logs_24h=recent,
            security_events_7d=security,
            most_active_users_30d=active_users.most_common(10),
            most_common_actions_30d=action_counts.most_common(10),
            resource_type_distribution_30d=rt_counts.most_common(),
        )
