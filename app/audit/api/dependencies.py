"""FastAPI dependencies wiring the audit Ports to their adapters."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.audit.adapters.repository import SqlAlchemyAuditRepository, SqlAlchemyAuditWriter
from app.audit.application.query_service import AuditQueryService
from app.audit.domain.ports import AuditWriter
from app.core.database import get_db
from app.middleware.audit_middleware import get_audit_tracker
from app.users.adapters.read_port import SqlAlchemyUserReadPort
from app.users.domain.ports import UserReadPort


def get_audit_query_service(
    db: Session = Depends(get_db),
) -> AuditQueryService:
    return AuditQueryService(SqlAlchemyAuditRepository(db))


def get_user_read_port(db: Session = Depends(get_db)) -> UserReadPort:
    """Cross-domain consumer of the `UserReadPort` published by #222.

    Used by `GET /audit/user/{user_id}/activity` to verify the target
    user exists without taking a dependency on the users ORM model.
    """
    return SqlAlchemyUserReadPort(db)


def get_audit_writer(request: Request) -> AuditWriter:
    """Return an `AuditWriter` bound to the request-scoped audit tracker.

    Tracker-mode wins when present (typical FastAPI flow). Falls back
    to the direct-write path otherwise. See `SqlAlchemyAuditWriter` for
    the transaction-isolation rationale.

    Shared cross-domain factory used by the auth/users/files routers
    (#386) — mirrors the groups-domain factory in
    `app.groups.api.dependencies.get_audit_writer`.
    """
    return SqlAlchemyAuditWriter(tracker=get_audit_tracker(request))
