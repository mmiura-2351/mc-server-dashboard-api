"""FastAPI dependencies wiring the audit Ports to their adapters."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.audit.adapters.repository import SqlAlchemyAuditRepository
from app.audit.application.query_service import AuditQueryService
from app.core.database import get_db
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
