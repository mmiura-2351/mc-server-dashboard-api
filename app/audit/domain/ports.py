"""Audit-domain Protocols (Ports).

Two ports are exposed:

- `AuditRepository` — read-side, async, used by the audit router via
  `AuditQueryService`.
- `AuditWriter` — write-side, **sync**, used by every domain that
  emits audit events. The sync signature is deliberate: the operation
  is fire-and-forget against a sync SQLAlchemy session, and the 30+
  existing callers (mostly inside `def` route handlers that happen to
  be `async def` only because FastAPI requires it) call the legacy
  static API synchronously. Wrapping it in `async def` would add an
  `asyncio.run` shim at every callsite with no payoff.

`AuditRepository` is the only port that needs to be wrapped in an
`AuditQueryService` — there is no transactional composition for
audit reads, so no UnitOfWork.
"""

from typing import List, Optional, Protocol

from app.audit.domain.entities import (
    AuditEventCommand,
    AuditLogEntity,
    AuditStatistics,
    LogFilters,
)


class AuditWriter(Protocol):
    """Write-side port for audit events.

    Implementations **must not raise**: an audit failure must never
    block the calling business operation. Errors are logged and
    swallowed.
    """

    def record(self, command: AuditEventCommand) -> None: ...


class AuditRepository(Protocol):
    """Read-side port backing the audit router."""

    async def list_logs(
        self,
        filters: LogFilters,
        *,
        limit: int,
        offset: int,
    ) -> List[AuditLogEntity]: ...

    async def count_logs(self, filters: LogFilters) -> int: ...

    async def list_security_alerts(
        self, severity: Optional[str], limit: int
    ) -> List[AuditLogEntity]: ...

    async def list_user_activity(
        self, user_id: int, limit: int
    ) -> List[AuditLogEntity]: ...

    async def get_statistics(self) -> AuditStatistics: ...
