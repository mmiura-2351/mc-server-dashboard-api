"""Read-only `UserReadPort` adapter exposed to other domains.

Wraps a `SqlAlchemyUserRepository` and surfaces only the narrow set of
read methods declared on `app.users.domain.ports.UserReadPort`. Lives
here (not in `repository.py`) to keep the concrete read adapter import
clean for consumers that should never see the write surface.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.users.adapters.repository import SqlAlchemyUserRepository
from app.users.domain.entities import UserEntity


class SqlAlchemyUserReadPort:
    """`UserReadPort` backed by SQLAlchemy."""

    def __init__(self, db: Session):
        self._repo = SqlAlchemyUserRepository(db)

    async def get_by_id(self, user_id: int) -> Optional[UserEntity]:
        return await self._repo.get_by_id(user_id)

    async def get_by_username(self, username: str) -> Optional[UserEntity]:
        return await self._repo.get_by_username(username)
