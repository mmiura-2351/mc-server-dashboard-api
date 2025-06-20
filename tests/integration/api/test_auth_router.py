import pytest
from fastapi import status


class TestAuthRouter:
    def test_login_success(self, client, test_user):
        """有効なユーザーでのログイン成功"""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpassword"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_username(self, client):
        """存在しないユーザー名でのログイン失敗"""
        response = client.post(
            "/api/v1/auth/token", data={"username": "nonexistent", "password": "password"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]

    def test_login_invalid_password(self, client, test_user):
        """間違ったパスワードでのログイン失敗"""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "wrongpassword"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]

    def test_login_unapproved_user(self, client, unapproved_user):
        """未承認ユーザーでのログイン失敗"""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Account pending approval" in response.json()["detail"]

    def test_login_admin_user(self, client, admin_user):
        """管理者ユーザーでのログイン成功"""
        response = client.post(
            "/api/v1/auth/token", data={"username": "admin", "password": "adminpassword"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_missing_username(self, client):
        """ユーザー名なしでのログイン失敗"""
        response = client.post("/api/v1/auth/token", data={"password": "password"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_login_missing_password(self, client):
        """パスワードなしでのログイン失敗"""
        response = client.post("/api/v1/auth/token", data={"username": "testuser"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
