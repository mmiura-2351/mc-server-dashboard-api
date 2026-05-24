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

from app.backups.api.dependencies import get_backup_repository
from app.backups.domain.ports import BackupRepository
from app.core.database import SessionLocal, get_db
from app.groups.api.dependencies import get_group_service
from app.groups.application.service import GroupService
from app.servers.adapters.repository import SqlAlchemyServerRepository
from app.servers.adapters.uow import SqlAlchemyServersUnitOfWork
from app.servers.application.authorization import AuthorizationService
from app.servers.application.service import ServerService
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


def get_authorization_service(
    server_repo: ServerRepository = Depends(get_server_repository),
    backup_repo: BackupRepository = Depends(get_backup_repository),
) -> AuthorizationService:
    """Return a per-request `AuthorizationService` with sibling Ports wired.

    Introduced in #228 PR 2b: replaces the legacy module-level
    `authorization_service` singleton (which depended on the caller
    threading `db: Session` through every check).
    """
    return AuthorizationService(server_repo, backup_repo)


def get_server_service(
    uow: ServersUnitOfWork = Depends(get_servers_uow),
    server_repo: ServerRepository = Depends(get_server_repository),
    group_service: GroupService = Depends(get_group_service),
) -> ServerService:
    """Return a per-request `ServerService` with all sibling-domain Ports wired.

    Introduced in #228 PR 2c when `app/services/server_service.py` and
    `app/servers/service.py` were merged into
    `app/servers/application/service.py`. The injected `GroupService` is
    consumed via the correct `attach_group_to_server` call inside
    `create_server` (#259).
    """
    return ServerService(
        uow=uow,
        server_repo=server_repo,
        group_service=group_service,
    )


def make_servers_uow_from_session_factory() -> ServersUnitOfWork:
    """Build a `ServersUnitOfWork` that opens its own session per use.

    Mirrors `app.backups.api.dependencies.make_backup_scheduler` —
    background workers must not piggy-back on a request-scoped session
    so each invocation opens / closes its own via `SessionLocal`.
    """
    return SqlAlchemyServersUnitOfWork.from_session_factory(SessionLocal)


def make_server_repository_from_session(db: Session) -> ServerRepository:
    """Build a `ServerRepository` bound to an externally-managed `Session`.

    Introduced for #228 PR 2d so `MinecraftServerManager` can perform the
    port-conflict check via `ServerRepository.list_by_port(...)` while
    still sharing the caller's already-open session. After #272 the
    control router also uses this helper to hand the manager an explicit
    repository at start/restart time, replacing the transitional ORM
    refetch that used to live in those handlers.
    """
    return SqlAlchemyServerRepository(db)
