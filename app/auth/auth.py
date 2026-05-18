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

import secrets as _secrets
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
# Deprecated synchronous refresh-token shims
# ---------------------------------------------------------------------------
#
# These functions preserve the legacy `(user_id, db: Session)` /
# `(token, db: Session)` signature for callers that have not yet
# migrated to `AuthService` via `Depends(get_auth_service)`. They
# execute the same SQL the new `SqlAlchemyRefreshTokenRepository` would,
# but synchronously — no event loop is created. This keeps the contract
# identical for `tests/integration/test_refresh_token.py` and avoids the
# pytest-xdist worker instability we saw when the shims were
# `asyncio.run` wrappers (PR #230 CI run #26035042275).
#
# TODO (#222 follow-up): delete this block once that integration test
# either migrates to FastAPI route-level fixtures or to AuthService
# directly.


def create_refresh_token(user_id: int, db: Session) -> str:
    """Deprecated. Use `AuthService.create_refresh_token` via DI."""
    from app.core.config import settings as _settings
    from app.users.models import RefreshToken as _RefreshToken

    # Revoke previously-active refresh tokens for this user.
    db.query(_RefreshToken).filter(
        _RefreshToken.user_id == user_id, _RefreshToken.is_revoked.is_(False)
    ).update({"is_revoked": True}, synchronize_session=False)

    token = _secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=_settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    db.add(_RefreshToken(token=token, user_id=user_id, expires_at=expires_at))
    db.commit()
    return token


def verify_refresh_token(token: str, db: Session) -> Optional[int]:
    """Deprecated. Use `AuthService.verify_refresh_token` via DI."""
    from app.users.models import RefreshToken as _RefreshToken

    row = db.query(_RefreshToken).filter(_RefreshToken.token == token).first()
    if row is None or not row.is_valid():
        return None
    return row.user_id


def revoke_refresh_token(token: str, db: Session) -> bool:
    """Deprecated. Use `AuthService.revoke_refresh_token` via DI."""
    from app.users.models import RefreshToken as _RefreshToken

    row = db.query(_RefreshToken).filter(_RefreshToken.token == token).first()
    if row is None:
        return False
    row.is_revoked = True
    db.commit()
    return True
