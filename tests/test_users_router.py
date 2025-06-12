import pytest
from fastapi import status
from app.auth.auth import create_access_token


def get_auth_headers(username: str):
    """Generate authentication header"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestUsersRouter:

    def test_register_first_user(self, client):
        """First user registration (as admin)"""
        response = client.post(
            "/api/v1/users/register",
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
        """Second user registration (as regular user)"""
        response = client.post(
            "/api/v1/users/register",
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
        """Registration failure with duplicate username"""
        response = client.post(
            "/api/v1/users/register",
            json={
                "username": "testuser",
                "email": "different@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Username already registered" in response.json()["detail"]

    def test_get_current_user_info(self, client, test_user):
        """Get current user information"""
        headers = get_auth_headers("testuser")
        response = client.get("/api/v1/users/me", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_get_current_user_info_unauthorized(self, client):
        """User information retrieval failure without authentication"""
        response = client.get("/api/v1/users/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_approve_user_as_admin(self, client, admin_user, unapproved_user):
        """User approval by admin"""
        headers = get_auth_headers("admin")
        response = client.post(f"/api/v1/users/approve/{unapproved_user.id}", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True

    def test_approve_user_as_non_admin(self, client, test_user, unapproved_user):
        """User approval failure by regular user"""
        headers = get_auth_headers("testuser")
        response = client.post(f"/api/v1/users/approve/{unapproved_user.id}", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admin can perform this action" in response.json()["detail"]

    def test_approve_nonexistent_user(self, client, admin_user):
        """Approval failure for non-existent user"""
        headers = get_auth_headers("admin")
        response = client.post("/api/v1/users/approve/999", headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "User not found" in response.json()["detail"]

    def test_change_role_as_admin(self, client, admin_user, test_user):
        """Role change by admin"""
        headers = get_auth_headers("admin")
        response = client.put(
            f"/api/v1/users/role/{test_user.id}", json={"role": "admin"}, headers=headers
        )

        assert response.status_code == status.HTTP_200_OK

    def test_change_role_as_non_admin(self, client, test_user):
        """Role change failure by regular user"""
        headers = get_auth_headers("testuser")
        response = client.put(
            f"/api/v1/users/role/{test_user.id}", json={"role": "admin"}, headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Only admin can perform this action" in response.json()["detail"]

    def test_change_role_nonexistent_user(self, client, admin_user):
        """Role change failure for non-existent user"""
        headers = get_auth_headers("admin")
        response = client.put("/api/v1/users/role/999", json={"role": "admin"}, headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "User not found" in response.json()["detail"]

    def test_register_invalid_email(self, client):
        """Registration failure with invalid email address"""
        response = client.post(
            "/api/v1/users/register",
            json={
                "username": "testuser",
                "email": "invalid-email",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_register_missing_fields(self, client):
        """Registration failure without required fields"""
        response = client.post(
            "/api/v1/users/register",
            json={
                "username": "testuser"
                # email and password missing
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
