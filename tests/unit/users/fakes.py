"""In-memory fakes for the users domain Ports."""

from dataclasses import replace
from types import TracebackType
from typing import Dict, List, Optional

from app.core.datetime_utils import utcnow
from app.users.domain.entities import (
    CreateUserCommand,
    UpdateUserCommand,
    UserEntity,
)
from app.users.domain.value_objects import Role


class FakeUserRepository:
    """Dict-backed `UserRepository` (and `UserReadPort`) for unit tests."""

    def __init__(self) -> None:
        self._users: Dict[int, UserEntity] = {}
        self._next_id = 1

    def _put(self, user: UserEntity) -> UserEntity:
        assert user.id is not None
        self._users[user.id] = user
        return user

    # ----- Reads -----

    async def get_by_id(self, user_id: int) -> Optional[UserEntity]:
        return self._users.get(user_id)

    async def get_by_username(self, username: str) -> Optional[UserEntity]:
        for u in self._users.values():
            if u.username == username:
                return u
        return None

    async def get_by_email(self, email: str) -> Optional[UserEntity]:
        for u in self._users.values():
            if u.email == email:
                return u
        return None

    async def list_all(self) -> List[UserEntity]:
        return sorted(self._users.values(), key=lambda u: u.id or 0)

    async def count(self) -> int:
        return len(self._users)

    async def count_by_role(self, role: Role) -> int:
        return sum(1 for u in self._users.values() if u.role == role)

    async def email_exists_for_other_user(self, email: str, exclude_user_id: int) -> bool:
        return any(
            u.email == email and u.id != exclude_user_id for u in self._users.values()
        )

    # ----- Writes -----

    async def create(self, command: CreateUserCommand) -> UserEntity:
        now = utcnow()
        user = UserEntity(
            id=self._next_id,
            username=command.username,
            email=command.email,
            hashed_password=command.hashed_password,
            role=command.role,
            is_active=True,
            is_approved=command.is_approved,
            created_at=now,
            updated_at=now,
        )
        self._next_id += 1
        return self._put(user)

    async def update(
        self, user_id: int, command: UpdateUserCommand
    ) -> Optional[UserEntity]:
        existing = self._users.get(user_id)
        if existing is None:
            return None
        updated = replace(existing, **command.applied_fields(), updated_at=utcnow())
        return self._put(updated)

    async def delete(self, user_id: int) -> bool:
        if user_id not in self._users:
            return False
        del self._users[user_id]
        return True


class FakeUsersUnitOfWork:
    """In-memory `UsersUnitOfWork`.

    Same caveat as `tests.unit.versions.fakes.FakeUnitOfWork`: `rollback()`
    counts the call but does not unwind in-memory state.
    """

    def __init__(self, users: Optional[FakeUserRepository] = None) -> None:
        self.users: FakeUserRepository = users or FakeUserRepository()
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeUsersUnitOfWork":
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
