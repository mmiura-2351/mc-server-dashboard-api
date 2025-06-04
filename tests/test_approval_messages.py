import pytest
from fastapi import status
from app.auth.auth import create_access_token


def get_auth_headers(username: str):
    """認証ヘッダーを生成"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestApprovalMessages:

    def test_unapproved_user_login_returns_detailed_message(
        self, client, db, unapproved_user
    ):
        """未承認ユーザーのログイン時に詳細なメッセージが返される"""
        response = client.post(
            "/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "Account pending approval" in data["detail"]
        assert "administrator" in data["detail"]
        assert "approve your account" in data["detail"]

    def test_approved_user_login_succeeds(self, client, db, test_user):
        """承認済みユーザーのログインは成功する"""
        response = client.post(
            "/auth/token", data={"username": "testuser", "password": "testpassword"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_first_user_registration_auto_approved(self, client):
        """最初のユーザー登録は自動承認される"""
        response = client.post(
            "/users/register",
            json={
                "username": "firstuser",
                "email": "first@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == "firstuser"
        assert data["is_approved"] is True

    def test_second_user_registration_pending_approval(self, client, db, admin_user):
        """2番目のユーザー登録は承認待ちになる"""
        response = client.post(
            "/users/register",
            json={
                "username": "seconduser",
                "email": "second@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == "seconduser"
        assert data["is_approved"] is False

    def test_admin_can_approve_user(self, client, db, admin_user, unapproved_user):
        """管理者はユーザーを承認できる"""
        headers = get_auth_headers("admin")
        response = client.post(f"/users/approve/{unapproved_user.id}", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True

    def test_approved_user_can_login_after_approval(
        self, client, db, admin_user, unapproved_user
    ):
        """承認後のユーザーはログインできる"""
        # まず管理者がユーザーを承認
        headers = get_auth_headers("admin")
        approve_response = client.post(
            f"/users/approve/{unapproved_user.id}", headers=headers
        )
        assert approve_response.status_code == status.HTTP_200_OK

        # 承認後にログインを試行
        login_response = client.post(
            "/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert login_response.status_code == status.HTTP_200_OK
        data = login_response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_user_status_reflects_approval_state(
        self, client, db, test_user, unapproved_user
    ):
        """ユーザー情報APIで承認状態が正しく反映される"""
        # 承認済みユーザーの情報取得
        headers = get_auth_headers("testuser")
        response = client.get("/users/me", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True
        assert data["is_active"] is True

    def test_error_message_consistency(self, client, db, unapproved_user):
        """エラーメッセージの一貫性をテスト"""
        response = client.post(
            "/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        error_detail = response.json()["detail"]

        # メッセージに必要な要素が含まれているかチェック
        required_elements = [
            "Account pending approval",
            "administrator",
            "approve your account",
        ]

        for element in required_elements:
            assert element in error_detail, f"Error message should contain '{element}'"

    def test_non_existent_user_login_different_error(self, client):
        """存在しないユーザーのログインは異なるエラーメッセージ"""
        response = client.post(
            "/auth/token", data={"username": "nonexistent", "password": "password"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]
        # 承認待ちメッセージではないことを確認
        assert "pending approval" not in response.json()["detail"].lower()

    def test_wrong_password_different_error(self, client, db, test_user):
        """間違ったパスワードは異なるエラーメッセージ"""
        response = client.post(
            "/auth/token", data={"username": "testuser", "password": "wrongpassword"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]
        # 承認待ちメッセージではないことを確認
        assert "pending approval" not in response.json()["detail"].lower()
