"""Backward-compat shim for `app.versions.service`.

The canonical service lives in `app.versions.application.service`. This
shim adapts the historical `VersionUpdateService(db: Session)` signature
to the new UoW-based constructor so existing imports (the scheduler, the
management CLI, the test suite) keep working until they migrate to
`app.versions.api.dependencies.get_version_service`. Deprecated.
"""

from sqlalchemy.orm import Session

from app.versions.adapters.uow import SqlAlchemyUnitOfWork
from app.versions.application.service import (
    VersionUpdateService as _ApplicationVersionUpdateService,
)


class VersionUpdateService(_ApplicationVersionUpdateService):
    """Deprecated session-based constructor wrapper.

    Prefer `app.versions.application.service.VersionUpdateService` with an
    explicit `UnitOfWork`, wired via
    `app.versions.api.dependencies.get_version_service`.
    """

    def __init__(self, db: Session):
        # Tests pass a `MagicMock(spec=Session)`; production callers pass a
        # real `Session`. The UoW only reads attributes from the object, so
        # both work.
        super().__init__(uow=SqlAlchemyUnitOfWork(db=db))
        self.db: Session = db


def get_version_update_service() -> VersionUpdateService:
    """Build a `VersionUpdateService` with a freshly-obtained DB session.

    Retained for callers that bypass FastAPI's `Depends`. New code should
    use `app.versions.api.dependencies.get_version_service` instead.
    """
    from app.core.database import get_db

    db = next(get_db())
    return VersionUpdateService(db)


__all__ = ["VersionUpdateService", "get_version_update_service"]
