from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
from app.auth.application.service import AuthService
from app.users.domain.value_objects import Role
from app.users.models import RefreshToken, User
from tests.helpers.users import make_user


def _make_auth_service(db: Session) -> AuthService:
    return AuthService(uow=SqlAlchemyAuthUnitOfWork(db=db))


def _insert_inactive_user(db: Session) -> User:
    """Create a non-active user directly via the shared `make_user`
    helper (test setup only). Uses the centralized rounds=4 bcrypt
    context — see `tests.helpers.security.pwd_context` (#168)."""
    return make_user(
        db,
        username="inactive_user",
        email="inactive@example.com",
        password="testpassword",
        role=Role.user,
        is_active=False,
        is_approved=True,
    )


class TestRefreshTokenAPI:
    """Tests for the refresh-token API."""

    def test_login_returns_refresh_token(self, client: TestClient, test_user: User):
        """The login response includes a refresh token."""
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
        """A valid refresh token mints a new access token."""
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
        """Refresh fails for an invalid refresh token."""
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "invalid_token"}
        )

        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_logout_success(self, client: TestClient, test_user: User, db: Session):
        """Logout succeeds with a valid refresh token."""
        refresh_token = await _make_auth_service(db).create_refresh_token(test_user.id)

        response = client.post(
            "/api/v1/auth/logout", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"

    def test_logout_invalid_token(self, client: TestClient):
        """Logout fails for an invalid refresh token."""
        response = client.post(
            "/api/v1/auth/logout", json={"refresh_token": "invalid_token"}
        )

        assert response.status_code == 400
        assert "Invalid refresh token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_token_revoked_after_logout(
        self, client: TestClient, test_user: User, db: Session
    ):
        """The refresh token is revoked after logout."""
        refresh_token = await _make_auth_service(db).create_refresh_token(test_user.id)

        client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token_inactive_user(self, client: TestClient, db: Session):
        """Refresh fails for an inactive user's token."""
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
    """Tests for the refresh-token internal logic."""

    @pytest.mark.asyncio
    async def test_create_refresh_token(self, test_user: User, db: Session):
        """Refresh-token creation works."""
        token = await _make_auth_service(db).create_refresh_token(test_user.id)

        assert token is not None
        assert len(token) > 0

        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        assert refresh_token is not None
        assert refresh_token.user_id == test_user.id
        assert not refresh_token.is_revoked

    @pytest.mark.asyncio
    async def test_verify_refresh_token_valid(self, test_user: User, db: Session):
        """A valid refresh token verifies."""
        svc = _make_auth_service(db)
        token = await svc.create_refresh_token(test_user.id)
        user_id = await svc.verify_refresh_token(token)

        assert user_id == test_user.id

    @pytest.mark.asyncio
    async def test_verify_refresh_token_invalid(self, db: Session):
        """An invalid refresh token does not verify."""
        user_id = await _make_auth_service(db).verify_refresh_token("invalid_token")
        assert user_id is None

    @pytest.mark.asyncio
    async def test_revoke_refresh_token(self, test_user: User, db: Session):
        """Revocation invalidates the refresh token."""
        svc = _make_auth_service(db)
        token = await svc.create_refresh_token(test_user.id)

        success = await svc.revoke_refresh_token(token)
        assert success is True

        user_id = await svc.verify_refresh_token(token)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_refresh_token_expiration(self, test_user: User, db: Session):
        """An expired refresh token does not verify."""
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
        """Creating a new refresh token revokes the existing one."""
        svc = _make_auth_service(db)
        first_token = await svc.create_refresh_token(test_user.id)
        second_token = await svc.create_refresh_token(test_user.id)

        assert await svc.verify_refresh_token(first_token) is None
        assert await svc.verify_refresh_token(second_token) == test_user.id

    @pytest.mark.asyncio
    async def test_refresh_token_model_is_valid(self, test_user: User, db: Session):
        """`RefreshToken.is_valid` behaves correctly."""
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
        """`RefreshToken.is_expired` behaves correctly."""
        token = await _make_auth_service(db).create_refresh_token(test_user.id)
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

        assert refresh_token.is_expired() is False

        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert refresh_token.is_expired() is True
