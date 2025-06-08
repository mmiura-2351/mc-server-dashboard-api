import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings


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


def create_refresh_token(user_id: int, db: Session) -> str:
    """リフレッシュトークンを生成してデータベースに保存"""
    from app.users.models import RefreshToken

    # 既存の有効なリフレッシュトークンを無効化
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False)
    ).update({"is_revoked": True})

    # 新しいリフレッシュトークンを生成
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    refresh_token = RefreshToken(token=token, user_id=user_id, expires_at=expires_at)

    db.add(refresh_token)
    db.commit()

    return token


def verify_refresh_token(token: str, db: Session) -> Optional[int]:
    """リフレッシュトークンを検証してユーザーIDを返す"""
    from app.users.models import RefreshToken

    refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

    if not refresh_token or not refresh_token.is_valid():
        return None

    return refresh_token.user_id


def revoke_refresh_token(token: str, db: Session) -> bool:
    """リフレッシュトークンを無効化"""
    from app.users.models import RefreshToken

    refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

    if refresh_token:
        refresh_token.is_revoked = True
        db.commit()
        return True

    return False
