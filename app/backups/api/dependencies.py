"""FastAPI dependency wiring for the backups domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires, and exposes the lifespan-scoped scheduler instance.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.backups import backup_scheduler_instance
from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork
from app.backups.application.scheduler import BackupSchedulerService
from app.backups.application.service import BackupService
from app.backups.domain.ports import BackupsUnitOfWork
from app.core.database import get_db
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.domain.ports import ServerReadPort


def get_backups_uow(db: Session = Depends(get_db)) -> BackupsUnitOfWork:
    """Return a `BackupsUnitOfWork` bound to the current request's session."""
    return SqlAlchemyBackupsUnitOfWork(db=db)


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
