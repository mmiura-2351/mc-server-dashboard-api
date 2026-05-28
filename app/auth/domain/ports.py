"""Port (Protocol) definitions for the auth domain.

Per `docs/app/ARCHITECTURE.md` Section 4.1 this module must not import from any
framework. All types crossing these Protocols are pure domain entities.
"""

from datetime import datetime
from types import TracebackType
from typing import Optional, Protocol

from app.auth.domain.entities import RefreshTokenEntity


class RefreshTokenRepository(Protocol):
    """Persistence port for refresh tokens.

    Implementations: `SqlAlchemyRefreshTokenRepository` (production),
    `FakeRefreshTokenRepository` (unit tests). Repository methods do
    **not** commit — wrap them in an `AuthUnitOfWork`.
    """

    async def get_by_token(self, token: str) -> Optional[RefreshTokenEntity]: ...

    async def create(
        self,
        token: str,
        user_id: int,
        expires_at: datetime,
    ) -> RefreshTokenEntity: ...

    async def revoke_active_for_user(self, user_id: int) -> int:
        """Mark every still-active refresh token of *user_id* as revoked.

        Returns the number of tokens that were revoked.
        """
        ...

    async def revoke(self, token: str) -> bool:
        """Revoke *token*. Returns False if no such token exists."""
        ...


class AuthUnitOfWork(Protocol):
    """Transactional boundary Port for the auth domain."""

    refresh_tokens: RefreshTokenRepository

    async def __aenter__(self) -> "AuthUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
