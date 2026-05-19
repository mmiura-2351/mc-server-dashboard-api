"""SQLAlchemy adapters for the audit domain Ports.

`SqlAlchemyAuditRepository` implements the read-side `AuditRepository`
(returns `AuditLogEntity` / `AuditStatistics` DTOs — never ORM rows).

`SqlAlchemyAuditWriter` implements the write-side `AuditWriter`. It
preserves the pre-#223 behaviour:

- If a request-scoped `AuditTracker` was passed in at construction time
  (typical FastAPI flow via `app.middleware.audit_middleware`), events
  are appended to the tracker and flushed at request end by the
  middleware.
- Otherwise the event is written directly with `db.add` + `db.commit`.
- Any exception is logged and swallowed: audit must never break the
  caller.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.audit.domain.entities import (
    AuditEventCommand,
    AuditLogEntity,
    AuditStatistics,
    LogFilters,
)
from app.audit.models import AuditLog

logger = logging.getLogger(__name__)


class AuditTrackerProtocol(Protocol):
    """Structural interface for the request-scoped AuditTracker.

    Declared here to avoid a hard import from `app.middleware` into the
    adapter layer. `app.middleware.audit_middleware.AuditTracker` satisfies
    this protocol structurally — no inheritance needed. Mypy will catch
    drift on either side without creating an import cycle.
    """

    def add_event(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> None: ...


def _log_to_entity(row: AuditLog) -> AuditLogEntity:
    """Convert an `AuditLog` ORM row to an entity.

    `details` is normalised to `dict` regardless of how the column came
    back (SQLite stores JSON as a string). `user_email` is filled in
    when the join populated `row.user`; callers that don't need it can
    leave the relationship un-eagerloaded.
    """
    details = row.details
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            details = None

    email = row.user.email if row.user is not None else None

    return AuditLogEntity(
        id=row.id,
        user_id=row.user_id,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        details=details,
        ip_address=row.ip_address,
        created_at=row.created_at,
        user_email=email,
    )


def _apply_filters(query, filters: LogFilters):
    """Apply a `LogFilters` to a SQLAlchemy `AuditLog` query."""
    if filters.user_id is not None:
        query = query.filter(AuditLog.user_id == filters.user_id)
    if filters.action:
        query = query.filter(AuditLog.action.ilike(f"%{filters.action}%"))
    if filters.resource_type:
        query = query.filter(AuditLog.resource_type == filters.resource_type)
    if filters.resource_id is not None:
        query = query.filter(AuditLog.resource_id == filters.resource_id)
    return query


class SqlAlchemyAuditRepository:
    """SQLAlchemy-backed `AuditRepository`."""

    def __init__(self, db: Session):
        self._db = db

    async def list_logs(
        self,
        filters: LogFilters,
        *,
        limit: int,
        offset: int,
    ) -> List[AuditLogEntity]:
        query = _apply_filters(
            self._db.query(AuditLog).options(joinedload(AuditLog.user)),
            filters,
        )
        rows = (
            query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
        )
        return [_log_to_entity(r) for r in rows]

    async def count_logs(self, filters: LogFilters) -> int:
        return _apply_filters(self._db.query(AuditLog), filters).count()

    async def list_security_alerts(
        self, severity: Optional[str], limit: int
    ) -> List[AuditLogEntity]:
        query = (
            self._db.query(AuditLog)
            .options(joinedload(AuditLog.user))
            .filter(AuditLog.resource_type == "security")
        )
        if severity:
            # Matches the legacy JSON-path filter exactly. Works on
            # Postgres (`->>` operator); SQLite falls back to a no-op
            # match — the legacy behaviour kept this same caveat.
            query = query.filter(AuditLog.details.op("->>")('"severity"') == severity)
        rows = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
        return [_log_to_entity(r) for r in rows]

    async def list_user_activity(self, user_id: int, limit: int) -> List[AuditLogEntity]:
        rows = (
            self._db.query(AuditLog)
            .options(joinedload(AuditLog.user))
            .filter(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_log_to_entity(r) for r in rows]

    async def get_statistics(self) -> AuditStatistics:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        thirty_days_ago = now - timedelta(days=30)
        week_ago = now - timedelta(days=7)

        total_logs = self._db.query(AuditLog).count()
        recent_logs = (
            self._db.query(AuditLog).filter(AuditLog.created_at >= yesterday).count()
        )

        active_users_rows = (
            self._db.query(AuditLog.user_id, func.count(AuditLog.id).label("c"))
            .filter(AuditLog.created_at >= thirty_days_ago)
            .filter(AuditLog.user_id.isnot(None))
            .group_by(AuditLog.user_id)
            .order_by(func.count(AuditLog.id).desc())
            .limit(10)
            .all()
        )
        common_actions_rows = (
            self._db.query(AuditLog.action, func.count(AuditLog.id).label("c"))
            .filter(AuditLog.created_at >= thirty_days_ago)
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
            .limit(10)
            .all()
        )
        resource_distribution_rows = (
            self._db.query(AuditLog.resource_type, func.count(AuditLog.id).label("c"))
            .filter(AuditLog.created_at >= thirty_days_ago)
            .group_by(AuditLog.resource_type)
            .order_by(func.count(AuditLog.id).desc())
            .all()
        )
        security_events = (
            self._db.query(AuditLog)
            .filter(AuditLog.created_at >= week_ago)
            .filter(AuditLog.resource_type == "security")
            .count()
        )

        return AuditStatistics(
            total_logs=total_logs,
            recent_logs_24h=recent_logs,
            security_events_7d=security_events,
            most_active_users_30d=[(row[0], row[1]) for row in active_users_rows],
            most_common_actions_30d=[(row[0], row[1]) for row in common_actions_rows],
            resource_type_distribution_30d=[
                (row[0], row[1]) for row in resource_distribution_rows
            ],
        )


class SqlAlchemyAuditWriter:
    """SQLAlchemy-backed `AuditWriter`.

    The direct-write path uses a **fresh** session (via
    `app.core.database.SessionLocal`) so the audit insert is
    transactionally isolated from any caller-side pending writes.
    Previously the writer reused the caller's session and called
    `commit()` on it, which silently committed any in-flight business
    operation state (Resolves #240).

    The tracker path is unchanged: when an `AuditTracker` is present
    (typical FastAPI request flow), events are appended to the
    tracker and flushed by the middleware at request end.

    **SQLite caveat**: when the *caller* holds an open write transaction
    (e.g. a pending `INSERT` in the request's session), the fresh session
    used by the direct-write path will block on SQLite's file-level lock.
    The `except` swallow then silently drops the audit record.  In practice
    the tracker path dominates all FastAPI request flows, so the direct-write
    path is only hit when there is no `AuditTracker` (e.g. background jobs or
    tests).  Production deployments on PostgreSQL are unaffected — row-level
    locking means the two sessions do not contend.
    """

    def __init__(
        self,
        tracker: Optional[AuditTrackerProtocol] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> None:
        self._tracker = tracker
        # `session_factory` is injectable so tests can point the
        # direct-write path at a known engine. Defaults to the
        # application `SessionLocal`, which conftest binds to the
        # worker-scoped test SQLite via `DATABASE_URL`.
        if session_factory is None:
            from app.core.database import SessionLocal as _SessionLocal

            self._session_factory: Callable[[], Session] = _SessionLocal
        else:
            self._session_factory = session_factory

    def record(self, command: AuditEventCommand) -> None:
        try:
            if self._tracker is not None and hasattr(self._tracker, "add_event"):
                # Tracker is request-scoped — let the middleware flush
                # the batch at request end. The tracker carries its own
                # `ip_address`, so the one on the command is ignored
                # here (matches pre-#223 behaviour).
                self._tracker.add_event(
                    action=command.action,
                    resource_type=command.resource_type,
                    resource_id=command.resource_id,
                    details=command.details,
                    user_id=command.user_id,
                )
                return

            # Separate session so audit writes never commit the
            # caller's pending transaction state.
            db = self._session_factory()
            try:
                audit_log = AuditLog.create_log(
                    action=command.action,
                    resource_type=command.resource_type,
                    user_id=command.user_id,
                    resource_id=command.resource_id,
                    details=command.details,
                    ip_address=command.ip_address,
                )
                db.add(audit_log)
                db.commit()
                logger.debug(
                    "Created audit log: %s on %s:%s by user %s",
                    command.action,
                    command.resource_type,
                    command.resource_id,
                    command.user_id,
                )
            finally:
                db.close()
        except Exception as exc:
            # Audit must never break the caller — log and swallow.
            logger.error(
                "Failed to log audit event %s on %s:%s — %s",
                command.action,
                command.resource_type,
                command.resource_id,
                exc,
            )
            # No rollback needed: the direct-write path owns a fresh
            # session that was closed in `finally`; the tracker path
            # mutates only in-memory state.
