"""Pure domain entities for the users module.

These dataclasses are the language the application layer speaks. They have
no SQLAlchemy, Pydantic, FastAPI, or any framework dependency beyond
`Role` (a stdlib `enum.Enum` whose import-site happens to be the ORM
module — see `__init__.py`).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.users.models import Role


@dataclass(frozen=True)
class UserEntity:
    """A user, independent of how it is persisted."""

    username: str
    email: str
    hashed_password: str
    role: Role
    is_active: bool
    is_approved: bool
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class CreateUserCommand:
    """Inputs to register a new user."""

    username: str
    email: str
    hashed_password: str
    role: Role
    is_approved: bool


@dataclass(frozen=True)
class UpdateUserCommand:
    """Sparse user-profile update.

    `None` means "leave the column untouched"; only non-`None` fields are
    applied. (Same caveat as `app.versions.domain.entities.UpdateVersionCommand`
    — see that class docstring if a `MISSING`-sentinel becomes necessary.)
    """

    username: Optional[str] = None
    email: Optional[str] = None
    hashed_password: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    is_approved: Optional[bool] = None

    def applied_fields(self) -> dict:
        """Return only the fields the caller actually set (i.e. non-`None`).

        A `None` argument is treated as "skip", not "set to NULL".
        """
        return {name: value for name, value in self.__dict__.items() if value is not None}
