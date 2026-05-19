"""Read-side application service for the audit domain.

Thin orchestrator around `AuditRepository`. No transactions are
required for read queries, so there is no UnitOfWork — unlike
`app.users.application.service` and `app.versions.application.service`,
this service holds the Port directly.
"""

from typing import List, Optional

from app.audit.domain.entities import (
    AuditLogEntity,
    AuditStatistics,
    LogFilters,
)
from app.audit.domain.ports import AuditRepository


class AuditQueryService:
    """Read-only use cases for the audit router."""

    def __init__(self, repository: AuditRepository):
        self._repo: AuditRepository = repository

    async def list_logs(
        self,
        filters: LogFilters,
        *,
        page: int,
        page_size: int,
    ) -> tuple[List[AuditLogEntity], int]:
        """Return one page of logs alongside the total filtered count."""
        offset = (page - 1) * page_size
        logs = await self._repo.list_logs(filters, limit=page_size, offset=offset)
        total = await self._repo.count_logs(filters)
        return logs, total

    async def list_security_alerts(
        self, severity: Optional[str], limit: int
    ) -> List[AuditLogEntity]:
        return await self._repo.list_security_alerts(severity, limit)

    async def list_user_activity(self, user_id: int, limit: int) -> List[AuditLogEntity]:
        return await self._repo.list_user_activity(user_id, limit)

    async def get_statistics(self) -> AuditStatistics:
        return await self._repo.get_statistics()
