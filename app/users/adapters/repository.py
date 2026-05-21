"""SQLAlchemy implementation of the users domain Ports.

Implements `app.users.domain.ports.UserRepository` (and structurally the
narrower `UserReadPort`). Converts ORM rows to/from `UserEntity` so the
application layer never sees ORM types.

Per the UnitOfWork pattern, repository methods **do not commit**.
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.users.domain.entities import (
    CreateUserCommand,
    UpdateUserCommand,
    UserEntity,
)
from app.users.domain.value_objects import Role
from app.users.models import User


def _user_to_entity(u: User) -> UserEntity:
    """Convert a User ORM row into a domain entity."""
    return UserEntity(
        id=u.id,
        username=u.username,
        email=u.email,
        hashed_password=u.hashed_password,
        role=u.role,
        is_active=u.is_active,
        is_approved=u.is_approved,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


class SqlAlchemyUserRepository:
    """SQLAlchemy-backed `UserRepository`."""

    def __init__(self, db: Session):
        self.db = db

    # ----- Reads -----

    async def get_by_id(self, user_id: int) -> Optional[UserEntity]:
        row = self.db.query(User).filter(User.id == user_id).first()
        return _user_to_entity(row) if row else None

    async def get_by_username(self, username: str) -> Optional[UserEntity]:
        row = self.db.query(User).filter(User.username == username).first()
        return _user_to_entity(row) if row else None

    async def get_by_email(self, email: str) -> Optional[UserEntity]:
        row = self.db.query(User).filter(User.email == email).first()
        return _user_to_entity(row) if row else None

    async def list_all(self) -> List[UserEntity]:
        rows = self.db.query(User).all()
        return [_user_to_entity(r) for r in rows]

    async def count(self) -> int:
        return self.db.query(User).count()

    async def count_by_role(self, role: Role) -> int:
        return self.db.query(User).filter(User.role == role).count()

    async def email_exists_for_other_user(self, email: str, exclude_user_id: int) -> bool:
        return (
            self.db.query(User)
            .filter(User.email == email, User.id != exclude_user_id)
            .first()
            is not None
        )

    # ----- Writes -----

    async def create(self, command: CreateUserCommand) -> UserEntity:
        row = User(
            username=command.username,
            email=command.email,
            hashed_password=command.hashed_password,
            role=command.role,
            is_approved=command.is_approved,
        )
        self.db.add(row)
        self.db.flush()
        return _user_to_entity(row)

    async def update(
        self, user_id: int, command: UpdateUserCommand
    ) -> Optional[UserEntity]:
        row = self.db.query(User).filter(User.id == user_id).first()
        if row is None:
            return None
        for field_name, value in command.applied_fields().items():
            setattr(row, field_name, value)
        self.db.flush()
        return _user_to_entity(row)

    async def delete(self, user_id: int) -> bool:
        row = self.db.query(User).filter(User.id == user_id).first()
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True
