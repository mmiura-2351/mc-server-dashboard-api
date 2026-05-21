"""FastAPI dependency wiring for the servers domain.

This is the only file in `api/` allowed to import from `adapters/`.
It binds the SQLAlchemy adapters to the abstract Ports the application
layer requires.

Introduced under #228 (PR 1/3) — these factories are *not* wired into
any router or background task in this PR. PR #2 rewires the callers.
They are exposed eagerly so that step-2-onward CLs can land
incrementally without touching this file again.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.servers.adapters.repository import SqlAlchemyServerRepository
from app.servers.adapters.uow import SqlAlchemyServersUnitOfWork
from app.servers.domain.ports import ServerRepository, ServersUnitOfWork


def get_servers_uow(db: Session = Depends(get_db)) -> ServersUnitOfWork:
    """Return a `ServersUnitOfWork` bound to the current request's session."""
    return SqlAlchemyServersUnitOfWork(db=db)


def get_server_repository(db: Session = Depends(get_db)) -> ServerRepository:
    """Return a request-scoped `ServerRepository`.

    Useful for read-only endpoints that do not need a UoW boundary.
    Production writes should go through `get_servers_uow`.
    """
    return SqlAlchemyServerRepository(db)


def make_servers_uow_from_session_factory() -> ServersUnitOfWork:
    """Build a `ServersUnitOfWork` that opens its own session per use.

    Mirrors `app.backups.api.dependencies.make_backup_scheduler` —
    background workers must not piggy-back on a request-scoped session
    so each invocation opens / closes its own via `SessionLocal`.
    """
    return SqlAlchemyServersUnitOfWork.from_session_factory(SessionLocal)
