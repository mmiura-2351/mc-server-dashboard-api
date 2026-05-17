"""SQLAlchemy implementation of the `UnitOfWork` Port.

Wraps a single `Session` for the duration of one logical operation,
exposes a `VersionRepository` bound to that session, and commits (or
rolls back) atomically.

Two construction modes are supported:
- `SqlAlchemyUnitOfWork(db=session)` — caller owns the session lifecycle
  (FastAPI's `Depends(get_db)` already manages it). The UoW commits or
  rolls back but does not close the session.
- `SqlAlchemyUnitOfWork.from_session_factory(factory)` — UoW opens its
  own session via the factory (e.g. `SessionLocal`) and closes it on
  exit. Used by background workers (scheduler / management CLI).

**Re-entry semantics**: the same `SqlAlchemyUnitOfWork` instance may be
entered (`async with`) multiple times within one application service
call. In `db=session` mode the underlying session is reused, so the
calls form one logical session with multiple transactions. In
`session_factory` mode each entry opens — and the matching exit closes —
a *fresh* session, meaning each `async with` is an independent
transaction on its own connection. Application services that need
strict single-session-single-transaction semantics in factory mode
should serialize their work in a single `async with` block.

**Forgot-to-commit warning**: if you exit the context normally (no
exception) without having called `commit()`, the UoW logs a warning and
issues a `rollback()` defensively so the session is not left with an
open transaction holding row locks. This makes the missing-commit bug
loud rather than silent — see PR #229 review item A.
"""

import logging
from types import TracebackType
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.domain.ports import VersionRepository

logger = logging.getLogger(__name__)


class SqlAlchemyUnitOfWork:
    """SQLAlchemy-backed `UnitOfWork`."""

    versions: VersionRepository

    def __init__(
        self,
        db: Optional[Session] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ):
        if db is None and session_factory is None:
            raise ValueError("Either db or session_factory must be provided")
        self._db: Optional[Session] = db
        self._session_factory = session_factory
        self._owns_session = db is None
        self._committed = False

    @classmethod
    def from_session_factory(
        cls, session_factory: Callable[[], Session]
    ) -> "SqlAlchemyUnitOfWork":
        return cls(session_factory=session_factory)

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        if self._db is None:
            assert self._session_factory is not None  # for type checker
            self._db = self._session_factory()
        self.versions = SqlAlchemyVersionRepository(self._db)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
            elif not self._committed and self._has_pending_writes():
                # Normal exit but the caller staged writes without committing.
                # Roll back so we do not leave a stray open transaction
                # holding locks, and log loudly so the bug surfaces. Read-only
                # blocks (no pending writes) exit silently.
                logger.warning(
                    "SqlAlchemyUnitOfWork exited with pending writes but "
                    "no commit(); rolling back."
                )
                await self.rollback()
        finally:
            if self._owns_session and self._db is not None:
                self._db.close()
                self._db = None

    def _has_pending_writes(self) -> bool:
        """True iff the session has staged inserts/updates/deletes."""
        if self._db is None:
            return False
        return bool(self._db.new or self._db.dirty or self._db.deleted)

    async def commit(self) -> None:
        assert self._db is not None
        self._db.commit()
        self._committed = True

    async def rollback(self) -> None:
        assert self._db is not None
        self._db.rollback()
