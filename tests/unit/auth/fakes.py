"""In-memory fakes for the auth domain Ports."""

from dataclasses import replace
from datetime import datetime
from types import TracebackType
from typing import Dict, Optional

from app.auth.domain.entities import RefreshTokenEntity
from app.core.datetime_utils import utcnow


class FakeRefreshTokenRepository:
    """Dict-backed `RefreshTokenRepository`."""

    def __init__(self) -> None:
        self._tokens: Dict[int, RefreshTokenEntity] = {}
        self._next_id = 1

    def _put(self, token: RefreshTokenEntity) -> RefreshTokenEntity:
        assert token.id is not None
        self._tokens[token.id] = token
        return token

    async def get_by_token(self, token: str) -> Optional[RefreshTokenEntity]:
        for t in self._tokens.values():
            if t.token == token:
                return t
        return None

    async def create(
        self, token: str, user_id: int, expires_at: datetime
    ) -> RefreshTokenEntity:
        entity = RefreshTokenEntity(
            id=self._next_id,
            token=token,
            user_id=user_id,
            expires_at=expires_at,
            is_revoked=False,
            created_at=utcnow(),
        )
        self._next_id += 1
        return self._put(entity)

    async def revoke_active_for_user(self, user_id: int) -> int:
        count = 0
        for tid, t in list(self._tokens.items()):
            if t.user_id == user_id and not t.is_revoked:
                self._tokens[tid] = replace(t, is_revoked=True)
                count += 1
        return count

    async def revoke(self, token: str) -> bool:
        for tid, t in list(self._tokens.items()):
            if t.token == token:
                self._tokens[tid] = replace(t, is_revoked=True)
                return True
        return False


class FakeAuthUnitOfWork:
    """In-memory `AuthUnitOfWork`."""

    def __init__(
        self, refresh_tokens: Optional[FakeRefreshTokenRepository] = None
    ) -> None:
        self.refresh_tokens: FakeRefreshTokenRepository = (
            refresh_tokens or FakeRefreshTokenRepository()
        )
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeAuthUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        """Increment the rollback counter. Does NOT rewind state."""
        self.rolled_back += 1
