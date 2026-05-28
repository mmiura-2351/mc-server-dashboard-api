"""FastAPI dependency wiring for the backups domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires, and exposes the lifespan-scoped scheduler instance.

It also hosts the `make_backup_service` / `make_backup_scheduler`
factory helpers that were previously located under
`app/backups/application/`. They live here (and not in `application/`)
so the application layer never imports from `adapters/` or
SQLAlchemy — matching the groups sister domain and
`docs/app/ARCHITECTURE.md` Section 4.2.
"""

from pathlib import Path

from fastapi import Depends
from sqlalchemy.orm import Session

from app.backups import backup_scheduler_instance
from app.backups.adapters.repository import SqlAlchemyBackupRepository
from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork
from app.backups.application.scheduler import BackupSchedulerService
from app.backups.application.service import BackupService
from app.backups.domain.ports import BackupRepository, BackupsUnitOfWork
from app.core.database import SessionLocal, get_db
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.domain.ports import ServerReadPort


def get_backups_uow(db: Session = Depends(get_db)) -> BackupsUnitOfWork:
    """Return a `BackupsUnitOfWork` bound to the current request's session."""
    return SqlAlchemyBackupsUnitOfWork(db=db)


def get_backup_repository(db: Session = Depends(get_db)) -> BackupRepository:
    """Return a request-scoped `BackupRepository`.

    Useful for read-only endpoints (or composite services such as the
    authorization service introduced in #228 PR 2b) that need to
    resolve a backup without participating in a UoW.
    """
    return SqlAlchemyBackupRepository(db)


def get_server_read_port(db: Session = Depends(get_db)) -> ServerReadPort:
    """Return the minimal cross-domain `ServerReadPort` (TBD #154-8)."""
    return SqlAlchemyServerReadPort(db)


def get_backup_service(
    uow: BackupsUnitOfWork = Depends(get_backups_uow),
    server_read: ServerReadPort = Depends(get_server_read_port),
) -> BackupService:
    """Return a per-request `BackupService` with its Ports wired."""
    return BackupService(uow=uow, server_read=server_read)


def get_backup_scheduler_service() -> BackupSchedulerService:
    """Return the lifespan-scoped `BackupSchedulerService`.

    Raises `RuntimeError` if the scheduler has not yet been
    initialised — that signals a startup-ordering bug.
    """
    return backup_scheduler_instance.get()


# ---------------------------------------------------------------------------
# Factory helpers (moved from app/backups/application/factories.py)
#
# These functions wire concrete SQLAlchemy adapters into the application
# services. They are intentionally located in the `api/` layer because
# `application/` is forbidden from importing `adapters/` (ARCHITECTURE.md
# Section 4.2). Both the FastAPI DI graph and the legacy shim
# (`app.services.backup_service`) call into these helpers, so the shim
# does not need to import from `adapters/` either.
# ---------------------------------------------------------------------------


def make_backup_service(
    db: Session, backups_directory: Path = Path("backups")
) -> BackupService:
    """Build a `BackupService` for a request-scoped session."""
    return BackupService(
        uow=SqlAlchemyBackupsUnitOfWork(db=db),
        server_read=SqlAlchemyServerReadPort(db),
        backups_directory=backups_directory,
    )


def make_backup_scheduler(
    backups_directory: Path = Path("backups"),
) -> BackupSchedulerService:
    """Build the lifespan-scoped `BackupSchedulerService`.

    Both `uow_factory` and `server_read_factory` open per-call sessions
    via `SessionLocal`, so no session is held across scheduler ticks.
    The server-read factory is intentionally a callable rather than a
    pre-bound instance to avoid leaking a long-lived session into a
    background worker.

    `backups_directory` is forwarded to the periodic `.pending/` /
    `.failed/` housekeeping sweep (Issue #284). Retention windows and
    sweep cadence are read from `app.core.config.settings`.
    """
    return BackupSchedulerService(
        uow_factory=lambda: SqlAlchemyBackupsUnitOfWork.from_session_factory(
            SessionLocal
        ),
        server_read_factory=lambda: SqlAlchemyServerReadPort(SessionLocal()),
        backups_directory=backups_directory,
    )
