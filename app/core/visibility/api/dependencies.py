"""FastAPI dependency wiring for the visibility domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires, mirroring the templates / groups / backups precedent
(see `app/backups/api/dependencies.py`).
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.visibility.adapters.uow import SqlAlchemyVisibilityUnitOfWork
from app.core.visibility.application.migration import VisibilityMigrationService
from app.core.visibility.application.service import VisibilityService
from app.core.visibility.domain.ports import VisibilityUnitOfWork


def get_visibility_uow(db: Session = Depends(get_db)) -> VisibilityUnitOfWork:
    """Return a `VisibilityUnitOfWork` bound to the current request's session."""
    return SqlAlchemyVisibilityUnitOfWork(db=db)


def get_visibility_service(
    uow: VisibilityUnitOfWork = Depends(get_visibility_uow),
) -> VisibilityService:
    """Return a per-request `VisibilityService` with its Port wired."""
    return VisibilityService(uow=uow)


def get_visibility_migration_service(
    uow: VisibilityUnitOfWork = Depends(get_visibility_uow),
) -> VisibilityMigrationService:
    """Return a per-request `VisibilityMigrationService`."""
    return VisibilityMigrationService(uow=uow)


def make_visibility_service(db: Session) -> VisibilityService:
    """Build a `VisibilityService` for a request-scoped session.

    Used by the legacy shim (`app.services.visibility_service`) so callers
    that did ``VisibilityService(db)`` keep working without importing
    adapters.
    """
    return VisibilityService(uow=SqlAlchemyVisibilityUnitOfWork(db=db))


def make_visibility_migration_service(db: Session) -> VisibilityMigrationService:
    """Build a `VisibilityMigrationService` for a request-scoped session."""
    return VisibilityMigrationService(uow=SqlAlchemyVisibilityUnitOfWork(db=db))
