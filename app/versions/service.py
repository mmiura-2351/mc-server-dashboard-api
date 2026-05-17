"""Backward-compat shim for `app.versions.service`.

The canonical home for this code is `app.versions.application.service`.
This shim preserves the legacy `VersionUpdateService(db: Session)` signature
so existing callers and tests keep working during the migration. To be
removed in a follow-up sub-issue once all consumers move to
`app.versions.api.dependencies.get_version_service`.
"""

from typing import Any

from sqlalchemy.orm import Session

# Re-exported so tests that patch `app.versions.service.minecraft_version_manager`
# continue to resolve the symbol. The application layer module is the canonical
# patch target; this alias is kept solely for backward compatibility.
from app.services.version_manager import minecraft_version_manager  # noqa: F401
from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.application.service import (
    VersionUpdateService as _ApplicationVersionUpdateService,
)


class VersionUpdateService(_ApplicationVersionUpdateService):
    """Deprecated session-based constructor wrapper.

    Prefer `app.versions.application.service.VersionUpdateService` with an
    explicit `VersionRepository`, wired via `app.versions.api.dependencies`.
    """

    def __init__(self, db: Any):
        # `db` is typed as Any to accept Mock sessions used in tests without
        # tripping isinstance() checks. The adapter expects something with
        # the SQLAlchemy Session interface.
        super().__init__(repository=SqlAlchemyVersionRepository(db))
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
