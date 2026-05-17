"""SQLAlchemy implementation of the `AuthUnitOfWork` Port.

Mirrors `app.versions.adapters.uow.SqlAlchemyUnitOfWork` semantics —
see that module for caller-owned vs factory-owned modes, re-entry
behaviour, and the forgot-to-commit warning.
"""

import logging
from types import TracebackType
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.auth.adapters.repository import SqlAlchemyRefreshTokenRepository
from app.auth.domain.ports import RefreshTokenRepository

logger = logging.getLogger(__name__)


class SqlAlchemyAuthUnitOfWork:
    """SQLAlchemy-backed `AuthUnitOfWork`."""

    refresh_tokens: RefreshTokenRepository

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
    ) -> "SqlAlchemyAuthUnitOfWork":
        return cls(session_factory=session_factory)

    async def __aenter__(self) -> "SqlAlchemyAuthUnitOfWork":
        if self._db is None:
            assert self._session_factory is not None
            self._db = self._session_factory()
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(self._db)
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
                logger.warning(
                    "SqlAlchemyAuthUnitOfWork exited with pending writes but "
                    "no commit(); rolling back."
                )
                await self.rollback()
        finally:
            if self._owns_session and self._db is not None:
                self._db.close()
                self._db = None

    def _has_pending_writes(self) -> bool:
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
