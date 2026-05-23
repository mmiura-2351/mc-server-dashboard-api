"""JWT primitives — token encode/decode with no persistence dependency.

`create_access_token` and `verify_token` are imported widely across the
app. Refresh-token lifecycle lives in `app.auth.application.service.AuthService`.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

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


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT, returning its claim payload or ``None``.

    Issue #237: the new ``_authenticate`` helper in
    :mod:`app.auth.dependencies` needs access to the full claim payload
    (notably the ``tv`` token-version claim), not just the ``sub``
    field returned by :func:`verify_token`. This helper exposes the
    decoded dict while keeping signature/expiry verification
    centralised here.

    Returns ``None`` for any ``JWTError`` (invalid signature, expired
    token, malformed payload) so callers can decide on the appropriate
    HTTP error rather than catching exceptions across module
    boundaries.
    """
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def verify_token(token: str, credentials_exception):
    """Legacy helper preserved for backwards compatibility.

    New code should call :func:`decode_token` and inspect the full
    payload (Issue #237). This wrapper continues to return the ``sub``
    claim and raise *credentials_exception* on failure so existing
    call sites (notably WebSocket / test helpers) keep working
    unchanged.
    """
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    username: Optional[str] = payload.get("sub")
    if username is None:
        raise credentials_exception
    return username
