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
    """Build a `VisibilityService` for non-DI callers (e.g. management
    scripts, background tasks, or future code that needs a one-shot
    service instance outside of FastAPI's ``Depends`` graph).

    Note: the current shim at ``app.services.visibility_service`` re-exports
    the :class:`VisibilityService` class directly (not through this
    factory). This factory is reserved for future use; if no caller
    materializes, PR #3 sweep may remove it. See #228 / #287.
    """
    return VisibilityService(uow=SqlAlchemyVisibilityUnitOfWork(db=db))


def make_visibility_migration_service(db: Session) -> VisibilityMigrationService:
    """Build a `VisibilityMigrationService` for non-DI callers (e.g. a
    startup-time invocation from ``app.main`` lifespan, or management
    scripts) that need a one-shot service instance outside of FastAPI's
    ``Depends`` graph.

    Note: the current shim at ``app.services.visibility_migration_service``
    re-exports the :class:`VisibilityMigrationService` class directly
    (not through this factory). This factory is reserved for future use;
    if no caller materializes, PR #3 sweep may remove it. See #228 / #289.
    """
    return VisibilityMigrationService(uow=SqlAlchemyVisibilityUnitOfWork(db=db))
