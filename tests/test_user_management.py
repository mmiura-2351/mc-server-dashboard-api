import pytest
from fastapi import status
from app.auth.auth import create_access_token
from app.users import schemas


def get_auth_headers(username: str):
    """認証ヘッダーを生成"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestUserManagement:

    def test_update_user_info_username(self, client, test_user):
        """ユーザー名の更新"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me", json={"username": "newusername"}, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "user" in data
        assert "access_token" in data
        assert data["user"]["username"] == "newusername"
        assert data["user"]["email"] == "test@example.com"
        assert data["access_token"] != ""  # 新しいトークンが生成される

    def test_update_user_info_email(self, client, test_user):
        """メールアドレスの更新"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me", json={"email": "newemail@example.com"}, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "user" in data
        assert "access_token" in data
        assert data["user"]["username"] == "testuser"
        assert data["user"]["email"] == "newemail@example.com"
        assert data["access_token"] == ""  # usernameが変更されていないので空のトークン

    def test_update_user_info_both(self, client, test_user):
        """ユーザー名とメールアドレスの両方を更新"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me",
            json={"username": "newusername", "email": "newemail@example.com"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "user" in data
        assert "access_token" in data
        assert data["user"]["username"] == "newusername"
        assert data["user"]["email"] == "newemail@example.com"
        assert (
            data["access_token"] != ""
        )  # usernameが変更されたので新しいトークンが生成される

    def test_update_user_info_duplicate_username(self, client, test_user, admin_user):
        """重複するユーザー名での更新失敗"""
        headers = get_auth_headers("testuser")
        response = client.put("/api/v1/users/me", json={"username": "admin"}, headers=headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Username already exists" in response.json()["detail"]

    def test_update_user_info_duplicate_email(self, client, test_user, admin_user):
        """重複するメールアドレスでの更新失敗"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me", json={"email": "admin@example.com"}, headers=headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Email already exists" in response.json()["detail"]

    def test_update_password_success(self, client, test_user):
        """パスワード更新成功"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "testpassword", "new_password": "newpassword123"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK

    def test_update_password_wrong_current(self, client, test_user):
        """間違った現在のパスワードでの更新失敗"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me/password",
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword123",
            },
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Current password is incorrect" in response.json()["detail"]

    def test_delete_user_account_success(self, client, test_user):
        """アカウント削除成功"""
        headers = get_auth_headers("testuser")
        response = client.request(
            "DELETE", "/api/v1/users/me", json={"password": "testpassword"}, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert "Account deleted successfully" in response.json()["message"]

    def test_delete_user_account_wrong_password(self, client, test_user):
        """間違ったパスワードでのアカウント削除失敗"""
        headers = get_auth_headers("testuser")
        response = client.request(
            "DELETE", "/api/v1/users/me", json={"password": "wrongpassword"}, headers=headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Password is incorrect" in response.json()["detail"]

    def test_delete_last_admin_fails(self, client, admin_user):
        """最後の管理者の削除失敗"""
        headers = get_auth_headers("admin")
        response = client.request(
            "DELETE", "/api/v1/users/me", json={"password": "adminpassword"}, headers=headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot delete the last admin user" in response.json()["detail"]

    def test_get_all_users_as_admin(self, client, admin_user, test_user):
        """管理者による全ユーザー一覧取得"""
        headers = get_auth_headers("admin")
        response = client.get("/api/v1/users/", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 2
        usernames = [user["username"] for user in data]
        assert "admin" in usernames
        assert "testuser" in usernames

    def test_get_all_users_as_non_admin(self, client, test_user):
        """一般ユーザーによる全ユーザー一覧取得失敗"""
        headers = get_auth_headers("testuser")
        response = client.get("/api/v1/users/", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admin can perform this action" in response.json()["detail"]

    def test_delete_user_by_admin_success(self, client, admin_user, test_user):
        """管理者による他ユーザー削除成功"""
        headers = get_auth_headers("admin")
        response = client.delete(f"/api/v1/users/{test_user.id}", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        assert "User deleted successfully" in response.json()["message"]

    def test_delete_user_by_admin_self_fails(self, client, admin_user):
        """管理者による自分自身の削除失敗"""
        headers = get_auth_headers("admin")
        response = client.delete(f"/api/v1/users/{admin_user.id}", headers=headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot delete your own account" in response.json()["detail"]

    def test_delete_user_by_admin_nonexistent(self, client, admin_user):
        """存在しないユーザーの削除失敗"""
        headers = get_auth_headers("admin")
        response = client.delete("/api/v1/users/999", headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "User not found" in response.json()["detail"]

    def test_delete_user_by_non_admin(self, client, test_user, unapproved_user):
        """一般ユーザーによる他ユーザー削除失敗"""
        headers = get_auth_headers("testuser")
        response = client.delete(f"/api/v1/users/{unapproved_user.id}", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admin can perform this action" in response.json()["detail"]

    def test_update_user_info_unauthorized(self, client):
        """認証なしでのユーザー情報更新失敗"""
        response = client.put("/api/v1/users/me", json={"username": "newusername"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_password_unauthorized(self, client):
        """認証なしでのパスワード更新失敗"""
        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "password", "new_password": "newpassword"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_account_unauthorized(self, client):
        """認証なしでのアカウント削除失敗"""
        response = client.request("DELETE", "/api/v1/users/me", json={"password": "password"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
