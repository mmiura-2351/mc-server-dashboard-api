"""FastAPI dependency wiring for the groups domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires.
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.audit.adapters.repository import SqlAlchemyAuditWriter
from app.audit.domain.ports import AuditWriter
from app.core.database import get_db
from app.groups.adapters.uow import SqlAlchemyGroupsUnitOfWork
from app.groups.application.file_syncer import GroupFileSyncer
from app.groups.application.service import GroupService
from app.groups.domain.ports import GroupsUnitOfWork
from app.middleware.audit_middleware import get_audit_tracker
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.domain.ports import ServerReadPort


def get_groups_uow(db: Session = Depends(get_db)) -> GroupsUnitOfWork:
    """Return a `GroupsUnitOfWork` bound to the current request's session."""
    return SqlAlchemyGroupsUnitOfWork(db=db)


def get_server_read_port(db: Session = Depends(get_db)) -> ServerReadPort:
    """Return the minimal cross-domain `ServerReadPort` (TBD #154-8)."""
    return SqlAlchemyServerReadPort(db)


def get_audit_writer(request: Request) -> AuditWriter:
    """Return an `AuditWriter` bound to the request-scoped audit tracker.

    Tracker-mode wins when present (typical FastAPI flow). Falls back
    to the direct-write path otherwise. See `SqlAlchemyAuditWriter` for
    the transaction-isolation rationale.
    """
    return SqlAlchemyAuditWriter(tracker=get_audit_tracker(request))


def get_group_service(
    uow: GroupsUnitOfWork = Depends(get_groups_uow),
    server_read: ServerReadPort = Depends(get_server_read_port),
    audit: AuditWriter = Depends(get_audit_writer),
    db: Session = Depends(get_db),
) -> GroupService:
    """Return a per-request `GroupService` with all Ports wired.

    The file syncer is built from the same UoW's `ServerGroupRepository`
    so it shares the request's session. (Since the UoW lazily creates
    repository instances at `__aenter__`, the syncer reaches them via a
    sibling SQLAlchemy adapter constructed directly here.)
    """
    # The file syncer needs its OWN server-group repository instance
    # because it issues read-only queries outside the UoW context (the
    # legacy code did `db.query(ServerGroup)...` directly). Building a
    # second adapter on the same session is safe — both share the
    # request session via the `get_db` dependency.
    from app.groups.adapters.repository import SqlAlchemyServerGroupRepository

    server_group_repo = SqlAlchemyServerGroupRepository(db)
    file_syncer = GroupFileSyncer(
        server_groups=server_group_repo,
        server_read=server_read,
    )
    return GroupService(
        uow=uow,
        server_read=server_read,
        audit=audit,
        file_syncer=file_syncer,
    )
