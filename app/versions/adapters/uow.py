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
"""

from types import TracebackType
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.versions.adapters.repository import SqlAlchemyVersionRepository
from app.versions.domain.ports import VersionRepository


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
        finally:
            if self._owns_session and self._db is not None:
                self._db.close()
                self._db = None

    async def commit(self) -> None:
        assert self._db is not None
        self._db.commit()

    async def rollback(self) -> None:
        assert self._db is not None
        self._db.rollback()
