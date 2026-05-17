"""FastAPI dependency wiring for the versions domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.versions.adapters.uow import SqlAlchemyUnitOfWork
from app.versions.application.service import VersionUpdateService
from app.versions.domain.ports import UnitOfWork


def get_unit_of_work(db: Session = Depends(get_db)) -> UnitOfWork:
    """Return a `UnitOfWork` bound to the current request's session."""
    return SqlAlchemyUnitOfWork(db=db)


def get_version_service(
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> VersionUpdateService:
    """Return a `VersionUpdateService` with its UoW wired."""
    return VersionUpdateService(uow=uow)
