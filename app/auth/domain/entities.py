"""Pure domain entities for the auth module."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class RefreshTokenEntity:
    """A refresh token, independent of how it is persisted."""

    token: str
    user_id: int
    expires_at: datetime
    is_revoked: bool
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired()
