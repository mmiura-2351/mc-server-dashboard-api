import pytest
from fastapi import status
from app.auth.auth import create_access_token


def get_auth_headers(username: str):
    """認証ヘッダーを生成"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestUsersRouter:

    def test_register_first_user(self, client):
        """最初のユーザー登録（管理者として）"""
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
        assert data["email"] == "first@example.com"
        assert data["is_approved"] is True

    def test_register_second_user(self, client, admin_user):
        """2番目のユーザー登録（一般ユーザーとして）"""
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
        assert data["email"] == "second@example.com"
        assert data["is_approved"] is False

    def test_register_duplicate_username(self, client, test_user):
        """重複するユーザー名での登録失敗"""
        response = client.post(
            "/users/register",
            json={
                "username": "testuser",
                "email": "different@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Username already registered" in response.json()["detail"]

    def test_get_current_user_info(self, client, test_user):
        """現在のユーザー情報取得"""
        headers = get_auth_headers("testuser")
        response = client.get("/users/me", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_get_current_user_info_unauthorized(self, client):
        """認証なしでのユーザー情報取得失敗"""
        response = client.get("/users/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_approve_user_as_admin(self, client, admin_user, unapproved_user):
        """管理者によるユーザー承認"""
        headers = get_auth_headers("admin")
        response = client.post(f"/users/approve/{unapproved_user.id}", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True

    def test_approve_user_as_non_admin(self, client, test_user, unapproved_user):
        """一般ユーザーによるユーザー承認失敗"""
        headers = get_auth_headers("testuser")
        response = client.post(f"/users/approve/{unapproved_user.id}", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admin can perform this action" in response.json()["detail"]

    def test_approve_nonexistent_user(self, client, admin_user):
        """存在しないユーザーの承認失敗"""
        headers = get_auth_headers("admin")
        response = client.post("/users/approve/999", headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "User not found" in response.json()["detail"]

    def test_change_role_as_admin(self, client, admin_user, test_user):
        """管理者によるロール変更"""
        headers = get_auth_headers("admin")
        response = client.put(
            f"/users/role/{test_user.id}", json={"role": "admin"}, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK

    def test_change_role_as_non_admin(self, client, test_user):
        """一般ユーザーによるロール変更失敗"""
        headers = get_auth_headers("testuser")
        response = client.put(
            f"/users/role/{test_user.id}", json={"role": "admin"}, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admin can perform this action" in response.json()["detail"]

    def test_change_role_nonexistent_user(self, client, admin_user):
        """存在しないユーザーのロール変更失敗"""
        headers = get_auth_headers("admin")
        response = client.put("/users/role/999", json={"role": "admin"}, headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "User not found" in response.json()["detail"]

    def test_register_invalid_email(self, client):
        """無効なメールアドレスでの登録失敗"""
        response = client.post(
            "/users/register",
            json={
                "username": "testuser",
                "email": "invalid-email",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_register_missing_fields(self, client):
        """必須フィールドなしでの登録失敗"""
        response = client.post(
            "/users/register",
            json={
                "username": "testuser"
                # email and password missing
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
