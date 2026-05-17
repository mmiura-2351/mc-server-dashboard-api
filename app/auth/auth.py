"""JWT primitives plus deprecated session-based refresh-token shims.

The pure JWT helpers (`create_access_token`, `verify_token`) are the
permanent home for token encode/decode logic; they have no persistence
dependency and are imported widely across the app.

The three refresh-token functions kept here are **deprecated shims**
that forward to `app.auth.application.service.AuthService` while
legacy callers (notably `app/auth/router.py` and the test suite that
patches these names) migrate. New code should use `AuthService` via
`Depends(get_auth_service)`.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings

# ---------------------------------------------------------------------------
# JWT primitives (permanent — no persistence dependency)
# ---------------------------------------------------------------------------


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str, credentials_exception):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


# ---------------------------------------------------------------------------
# Deprecated refresh-token shims
# ---------------------------------------------------------------------------
#
# These functions wrap the new `AuthService` so existing callers do not
# break. They construct a `SqlAlchemyAuthUnitOfWork` from the caller's
# `Session` and run the use case synchronously. To be removed once
# `app/auth/router.py` and the test patches migrate to
# `Depends(get_auth_service)` — see #221 follow-up.


def _run(coro):
    """Run *coro* on a fresh event loop. Synchronous shim only."""
    import asyncio

    return asyncio.run(coro)


def create_refresh_token(user_id: int, db: Session) -> str:
    """Deprecated. Use `AuthService.create_refresh_token` via DI."""
    from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
    from app.auth.application.service import AuthService

    service = AuthService(uow=SqlAlchemyAuthUnitOfWork(db=db))
    return _run(service.create_refresh_token(user_id))


def verify_refresh_token(token: str, db: Session) -> Optional[int]:
    """Deprecated. Use `AuthService.verify_refresh_token` via DI."""
    from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
    from app.auth.application.service import AuthService

    service = AuthService(uow=SqlAlchemyAuthUnitOfWork(db=db))
    return _run(service.verify_refresh_token(token))


def revoke_refresh_token(token: str, db: Session) -> bool:
    """Deprecated. Use `AuthService.revoke_refresh_token` via DI."""
    from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
    from app.auth.application.service import AuthService

    service = AuthService(uow=SqlAlchemyAuthUnitOfWork(db=db))
    return _run(service.revoke_refresh_token(token))
