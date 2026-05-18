"""Auth use cases (application layer).

Manages refresh-token lifecycle through the `AuthUnitOfWork` Port. JWT
encoding/decoding is delegated to `app.auth.auth` because it has no
persistence dependency.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.auth.domain.ports import AuthUnitOfWork
from app.core.config import settings


class AuthService:
    """Refresh-token use cases."""

    def __init__(self, uow: AuthUnitOfWork):
        self._uow: AuthUnitOfWork = uow

    async def create_refresh_token(self, user_id: int) -> str:
        """Issue a fresh refresh token for *user_id*.

        Any still-active refresh token of the same user is revoked first
        so each user has at most one valid token at a time (matches the
        legacy behaviour in `app.auth.auth.create_refresh_token`).
        """
        async with self._uow as uow:
            await uow.refresh_tokens.revoke_active_for_user(user_id)
            token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
            await uow.refresh_tokens.create(
                token=token, user_id=user_id, expires_at=expires_at
            )
            await uow.commit()
            return token

    async def verify_refresh_token(self, token: str) -> Optional[int]:
        """Return the owning `user_id` iff *token* is valid; else `None`."""
        async with self._uow as uow:
            entity = await uow.refresh_tokens.get_by_token(token)
        if entity is None or not entity.is_valid():
            return None
        return entity.user_id

    async def revoke_refresh_token(self, token: str) -> bool:
        """Revoke *token*. Returns False if no such token exists."""
        async with self._uow as uow:
            ok = await uow.refresh_tokens.revoke(token)
            if ok:
                await uow.commit()
            return ok
