from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.auth import create_refresh_token, revoke_refresh_token, verify_refresh_token
from app.services.user import UserService
from app.users.models import RefreshToken, User


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

    def test_refresh_token_success(
        self, client: TestClient, test_user: User, db: Session
    ):
        """リフレッシュトークンによるアクセストークン更新の成功"""
        # リフレッシュトークンを生成
        refresh_token = create_refresh_token(test_user.id, db)

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

    def test_logout_success(self, client: TestClient, test_user: User, db: Session):
        """ログアウト成功"""
        # リフレッシュトークンを生成
        refresh_token = create_refresh_token(test_user.id, db)

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

    def test_refresh_token_revoked_after_logout(
        self, client: TestClient, test_user: User, db: Session
    ):
        """ログアウト後にリフレッシュトークンが無効化される"""
        # リフレッシュトークンを生成
        refresh_token = create_refresh_token(test_user.id, db)

        # ログアウト
        client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})

        # 同じリフレッシュトークンで更新を試行
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 401

    def test_refresh_token_inactive_user(self, client: TestClient, db: Session):
        """非アクティブユーザーのリフレッシュトークン使用失敗"""
        # 非アクティブユーザーを作成
        user_service = UserService(db)
        from app.users.schemas import UserCreate

        user_create = UserCreate(
            username="inactive_user",
            email="inactive@example.com",
            password="testpassword",
        )
        inactive_user = user_service.register_user(user_create)
        inactive_user.is_active = False
        db.commit()

        # リフレッシュトークンを生成
        refresh_token = create_refresh_token(inactive_user.id, db)

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )

        assert response.status_code == 401
        assert "User not found or inactive" in response.json()["detail"]


class TestRefreshTokenLogic:
    """リフレッシュトークンのロジックのテスト"""

    def test_create_refresh_token(self, test_user: User, db: Session):
        """リフレッシュトークン生成のテスト"""
        token = create_refresh_token(test_user.id, db)

        assert token is not None
        assert len(token) > 0

        # データベースに保存されていることを確認
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        assert refresh_token is not None
        assert refresh_token.user_id == test_user.id
        assert not refresh_token.is_revoked

    def test_verify_refresh_token_valid(self, test_user: User, db: Session):
        """有効なリフレッシュトークンの検証"""
        token = create_refresh_token(test_user.id, db)
        user_id = verify_refresh_token(token, db)

        assert user_id == test_user.id

    def test_verify_refresh_token_invalid(self, db: Session):
        """無効なリフレッシュトークンの検証"""
        user_id = verify_refresh_token("invalid_token", db)
        assert user_id is None

    def test_revoke_refresh_token(self, test_user: User, db: Session):
        """リフレッシュトークンの無効化"""
        token = create_refresh_token(test_user.id, db)

        # 無効化
        success = revoke_refresh_token(token, db)
        assert success is True

        # 無効化後は検証に失敗
        user_id = verify_refresh_token(token, db)
        assert user_id is None

    def test_refresh_token_expiration(self, test_user: User, db: Session):
        """リフレッシュトークンの有効期限テスト"""
        token = create_refresh_token(test_user.id, db)

        # 期限切れに設定
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

        # 期限切れのトークンは無効
        user_id = verify_refresh_token(token, db)
        assert user_id is None

    def test_create_refresh_token_revokes_existing(self, test_user: User, db: Session):
        """新しいリフレッシュトークン生成時に既存のトークンが無効化される"""
        # 最初のトークンを生成
        first_token = create_refresh_token(test_user.id, db)

        # 2番目のトークンを生成
        second_token = create_refresh_token(test_user.id, db)

        # 最初のトークンは無効化されている
        user_id = verify_refresh_token(first_token, db)
        assert user_id is None

        # 2番目のトークンは有効
        user_id = verify_refresh_token(second_token, db)
        assert user_id == test_user.id

    def test_refresh_token_model_is_valid(self, test_user: User, db: Session):
        """RefreshTokenモデルのis_validメソッドのテスト"""
        token = create_refresh_token(test_user.id, db)
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

        # 有効なトークン
        assert refresh_token.is_valid() is True

        # 無効化
        refresh_token.is_revoked = True
        assert refresh_token.is_valid() is False

        # 期限切れ
        refresh_token.is_revoked = False
        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert refresh_token.is_valid() is False

    def test_refresh_token_model_is_expired(self, test_user: User, db: Session):
        """RefreshTokenモデルのis_expiredメソッドのテスト"""
        token = create_refresh_token(test_user.id, db)
        refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()

        # 有効期限内
        assert refresh_token.is_expired() is False

        # 期限切れ
        refresh_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert refresh_token.is_expired() is True
