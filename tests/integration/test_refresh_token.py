from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
from app.auth.application.service import AuthService
from app.users.models import RefreshToken, Role, User


def _make_auth_service(db: Session) -> AuthService:
    return AuthService(uow=SqlAlchemyAuthUnitOfWork(db=db))


def _insert_inactive_user(db: Session) -> User:
    """Create a non-active user directly via ORM (test setup only)."""
    from passlib.context import CryptContext

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        username="inactive_user",
        email="inactive@example.com",
        hashed_password=pwd.hash("testpassword"),
        role=Role.user,
        is_active=False,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestRefreshTokenAPI:
    """リフレッシュトークンAPI のテスト"""

    def test_login_returns_refresh_token(self, client: TestClient, test_user: User):
        """ログイン時にリフレッシュトークンが返されることを確認"""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": test_user.username, "password": "testpassword"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_refresh_token_success(
        self, client: TestClient, test_user: User, db: Session
    ):
        """リフレッシュトークンによるアクセストークン更新の成功"""
        refresh_token = await _make_auth_service(db).create_refresh_token(test_user.id)

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_refresh_token_invalid(self, client: TestClient):
        """無効なリフレッシュトークンでの更新失敗"""
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "invalid_token"}
        )

        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_logout_success(self, client: TestClient, test_user: User, db: Session):
        """ログアウト成功"""
        refresh_token = await _make_auth_service(db).create_refresh_token(test_user.id)

        response = client.post(
            "/api/v1/auth/logout", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"

    def test_logout_invalid_token(self, client: TestClient):
        """無効なリフレッシュトークンでのログアウト失敗"""
        response = client.post(
            "/api/v1/auth/logout", json={"refresh_token": "invalid_token"}
        )

        assert response.status_code == 400
        assert "Invalid refresh token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_token_revoked_after_logout(
        self, client: TestClient, test_user: User, db: Session
    ):
        """ログアウト後にリフレッシュトークンが無効化される"""
        refresh_token = await _make_auth_service(db).create_refresh_token(test_user.id)

        client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token_inactive_user(self, client: TestClient, db: Session):
        """非アクティブユーザーのリフレッシュトークン使用失敗"""
        inactive_user = _insert_inactive_user(db)
        refresh_token = await _make_auth_service(db).create_refresh_token(
            inactive_user.id
        )

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 401
        assert "User not found or inactive" in response.json()["detail"]


class TestRefreshTokenLogic:
    """リフレッシュトークンのロジックのテスト"""

    @pytest.mark.asyncio
    async def test_create_refresh_token(self, test_user: User, db: Session):
        """リフレッシュトークン生成のテスト"""
        token = await _make_auth_service(db).create_refresh_token(test_user.id)

        assert token is not None
        assert len(token) > 0

        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        assert refresh_token is not None
        assert refresh_token.user_id == test_user.id
        assert not refresh_token.is_revoked

    @pytest.mark.asyncio
    async def test_verify_refresh_token_valid(self, test_user: User, db: Session):
        """有効なリフレッシュトークンの検証"""
        svc = _make_auth_service(db)
        token = await svc.create_refresh_token(test_user.id)
        user_id = await svc.verify_refresh_token(token)

        assert user_id == test_user.id

    @pytest.mark.asyncio
    async def test_verify_refresh_token_invalid(self, db: Session):
        """無効なリフレッシュトークンの検証"""
        user_id = await _make_auth_service(db).verify_refresh_token("invalid_token")
        assert user_id is None

    @pytest.mark.asyncio
    async def test_revoke_refresh_token(self, test_user: User, db: Session):
        """リフレッシュトークンの無効化"""
        svc = _make_auth_service(db)
        token = await svc.create_refresh_token(test_user.id)

        success = await svc.revoke_refresh_token(token)
        assert success is True

        user_id = await svc.verify_refresh_token(token)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_refresh_token_expiration(self, test_user: User, db: Session):
        """リフレッシュトークンの有効期限テスト"""
        svc = _make_auth_service(db)
        token = await svc.create_refresh_token(test_user.id)

        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

        user_id = await svc.verify_refresh_token(token)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_create_refresh_token_revokes_existing(
        self, test_user: User, db: Session
    ):
        """新しいリフレッシュトークン生成時に既存のトークンが無効化される"""
        svc = _make_auth_service(db)
        first_token = await svc.create_refresh_token(test_user.id)
        second_token = await svc.create_refresh_token(test_user.id)

        assert await svc.verify_refresh_token(first_token) is None
        assert await svc.verify_refresh_token(second_token) == test_user.id

    @pytest.mark.asyncio
    async def test_refresh_token_model_is_valid(self, test_user: User, db: Session):
        """RefreshTokenモデルのis_validメソッドのテスト"""
        token = await _make_auth_service(db).create_refresh_token(test_user.id)
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

        assert refresh_token.is_valid() is True

        refresh_token.is_revoked = True
        assert refresh_token.is_valid() is False

        refresh_token.is_revoked = False
        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert refresh_token.is_valid() is False

    @pytest.mark.asyncio
    async def test_refresh_token_model_is_expired(self, test_user: User, db: Session):
        """RefreshTokenモデルのis_expiredメソッドのテスト"""
        token = await _make_auth_service(db).create_refresh_token(test_user.id)
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

        assert refresh_token.is_expired() is False

        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert refresh_token.is_expired() is True
