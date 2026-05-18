"""Port (Protocol) definitions for the users domain.

Per `docs/ARCHITECTURE.md` §4.1, this module must not import from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types
crossing these Protocols are pure domain entities defined in
`entities.py`.

Three Ports are defined:
- `UserRepository`: full persistence port for users (writes + reads).
- `UserReadPort`: read-only view for *other* domains to depend on
  without inheriting write permission (#154 cross-domain rule).
- `UsersUnitOfWork`: transactional boundary Port. Wrap repository
  calls in `async with uow:` and `await uow.commit()` to finalise.
"""

from types import TracebackType
from typing import List, Optional, Protocol

from app.users.domain.entities import (
    CreateUserCommand,
    UpdateUserCommand,
    UserEntity,
)
from app.users.models import Role


class UserRepository(Protocol):
    """Persistence port for users.

    Implementations: `SqlAlchemyUserRepository` (production),
    `FakeUserRepository` (unit tests). Repository methods **do not commit**
    — wrap them in a `UsersUnitOfWork`.
    """

    # ----- Reads -----

    async def get_by_id(self, user_id: int) -> Optional[UserEntity]: ...

    async def get_by_username(self, username: str) -> Optional[UserEntity]: ...

    async def get_by_email(self, email: str) -> Optional[UserEntity]: ...

    async def list_all(self) -> List[UserEntity]: ...

    async def count(self) -> int: ...

    async def count_by_role(self, role: Role) -> int: ...

    async def email_exists_for_other_user(
        self, email: str, exclude_user_id: int
    ) -> bool: ...

    # ----- Writes -----

    async def create(self, command: CreateUserCommand) -> UserEntity: ...

    async def update(
        self, user_id: int, command: UpdateUserCommand
    ) -> Optional[UserEntity]: ...

    async def delete(self, user_id: int) -> bool: ...


class UserReadPort(Protocol):
    """Cross-domain read-only view of users.

    Consumers in other domains (audit, templates, groups, …) depend on
    this narrow Port rather than the full `UserRepository`, preventing
    accidental writes from outside the users domain.
    """

    async def get_by_id(self, user_id: int) -> Optional[UserEntity]: ...

    async def get_by_username(self, username: str) -> Optional[UserEntity]: ...


class UsersUnitOfWork(Protocol):
    """Transactional boundary Port for the users domain."""

    users: UserRepository

    async def __aenter__(self) -> "UsersUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
