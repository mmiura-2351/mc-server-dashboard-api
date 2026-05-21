"""Factory helpers that wire the SQLAlchemy adapters into the
application services.

These functions are the single entry point used by both the FastAPI DI
graph (`app.backups.api.dependencies`) and the legacy shim
(`app.services.backup_service`). Centralising the wiring here means
the shim does not import from `adapters/` directly.
"""

from sqlalchemy.orm import Session

from app.backups.adapters.uow import SqlAlchemyBackupsUnitOfWork
from app.backups.application.scheduler import BackupSchedulerService
from app.backups.application.service import BackupService
from app.servers.adapters.read_port import SqlAlchemyServerReadPort


def make_backup_service(db: Session) -> BackupService:
    """Build a `BackupService` for a request-scoped session.

    Mirrors `make_template_service` (templates pilot).
    """
    return BackupService(
        uow=SqlAlchemyBackupsUnitOfWork(db=db),
        server_read=SqlAlchemyServerReadPort(db),
    )


def make_backup_scheduler() -> BackupSchedulerService:
    """Build the lifespan-scoped `BackupSchedulerService`.

    Both `uow_factory` and `server_read_factory` open per-call sessions
    via `SessionLocal`, so no session is held across scheduler ticks.
    The server-read factory is intentionally a callable rather than a
    pre-bound instance to avoid leaking a long-lived session into a
    background worker.
    """
    from app.core.database import SessionLocal

    return BackupSchedulerService(
        uow_factory=lambda: SqlAlchemyBackupsUnitOfWork.from_session_factory(
            SessionLocal
        ),
        server_read_factory=lambda: SqlAlchemyServerReadPort(SessionLocal()),
    )
