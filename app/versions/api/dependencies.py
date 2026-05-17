"""FastAPI dependency wiring for the versions domain.

This is the only file in `api/` allowed to import from `adapters/`.
It selects concrete adapters and binds them to the Ports the
application layer requires.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.application.service import VersionUpdateService
from app.versions.domain.ports import VersionRepository


def get_version_repository(db: Session = Depends(get_db)) -> VersionRepository:
    """Return a `VersionRepository` bound to the current request's session."""
    return SqlAlchemyVersionRepository(db)


def get_version_service(
    repository: VersionRepository = Depends(get_version_repository),
) -> VersionUpdateService:
    """Return a `VersionUpdateService` with its persistence Port wired."""
    return VersionUpdateService(repository=repository)
