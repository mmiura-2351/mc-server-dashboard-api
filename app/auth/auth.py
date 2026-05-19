"""JWT primitives — token encode/decode with no persistence dependency.

`create_access_token` and `verify_token` are imported widely across the
app. Refresh-token lifecycle lives in `app.auth.application.service.AuthService`.
"""

from datetime import datetime, timedelta, timezone

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


def verify_token(token: str, credentials_exception):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception
