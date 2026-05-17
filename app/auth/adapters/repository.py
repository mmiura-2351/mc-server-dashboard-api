"""SQLAlchemy implementation of `RefreshTokenRepository`.

Lives under `app/auth/adapters/` despite the ORM model being defined in
`app/users/models.py` — the `RefreshToken` table is a user-related row
in the schema but a strictly auth-domain concern in the application.

Per the UnitOfWork pattern, repository methods do **not** commit.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.auth.domain.entities import RefreshTokenEntity
from app.users.models import RefreshToken


def _to_entity(row: RefreshToken) -> RefreshTokenEntity:
    return RefreshTokenEntity(
        id=row.id,
        token=row.token,
        user_id=row.user_id,
        expires_at=row.expires_at,
        is_revoked=row.is_revoked,
        created_at=row.created_at,
    )


class SqlAlchemyRefreshTokenRepository:
    """SQLAlchemy-backed refresh-token persistence."""

    def __init__(self, db: Session):
        self.db = db

    async def get_by_token(self, token: str) -> Optional[RefreshTokenEntity]:
        row = self.db.query(RefreshToken).filter(RefreshToken.token == token).first()
        return _to_entity(row) if row else None

    async def create(
        self,
        token: str,
        user_id: int,
        expires_at: datetime,
    ) -> RefreshTokenEntity:
        row = RefreshToken(token=token, user_id=user_id, expires_at=expires_at)
        self.db.add(row)
        self.db.flush()
        return _to_entity(row)

    async def revoke_active_for_user(self, user_id: int) -> int:
        # SQLAlchemy 1.x style `update()` returns row count.
        return (
            self.db.query(RefreshToken)
            .filter(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False))
            .update({"is_revoked": True})
        )

    async def revoke(self, token: str) -> bool:
        row = self.db.query(RefreshToken).filter(RefreshToken.token == token).first()
        if row is None:
            return False
        row.is_revoked = True
        self.db.flush()
        return True
