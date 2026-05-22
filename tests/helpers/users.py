"""User factory helpers for test fixtures (Issue #168).

`make_user(db, **kw)` provides a single creation path for `User`
rows so tests don't repeat the same insert / commit / refresh dance.
Defaults match the legacy `test_user` fixture (role=user, approved).
"""

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.users.domain.value_objects import Role
from app.users.models import User
from tests.helpers.security import pwd_context


def make_user(
    db: Session,
    *,
    username: str = "testuser",
    email: Optional[str] = None,
    password: str = "testpassword",
    role: Role = Role.user,
    is_active: bool = True,
    is_approved: bool = True,
    **extra: Any,
) -> User:
    """Create and persist a `User` row.

    - `email` defaults to ``f"{username}@example.com"`` if not provided.
    - `password` is hashed with the shared test `pwd_context`
      (rounds=4) so test setup stays fast.
    - Extra keyword args are forwarded verbatim to the `User`
      constructor, letting callers set columns we don't model
      explicitly (e.g. timestamps for migration tests).
    """
    user = User(
        username=username,
        email=email if email is not None else f"{username}@example.com",
        hashed_password=pwd_context.hash(password),
        role=role,
        is_active=is_active,
        is_approved=is_approved,
        **extra,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


__all__ = ["make_user"]
