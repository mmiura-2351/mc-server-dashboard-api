"""
Comprehensive test coverage for User API endpoints
Tests HTTP API layer for user management, registration, and administrative operations
"""

import pytest
from fastapi import status
from app.auth.auth import create_access_token
from app.users import schemas


def get_auth_headers(username: str):
    """Generate authentication header"""
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestUserRegistrationAPI:
    """Test user registration API endpoints"""

    def test_register_first_user(self, client):
        """First user registration (becomes admin automatically)"""
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
        assert data["role"] == "admin"

    def test_register_second_user(self, client, admin_user):
        """Second user registration (requires approval)"""
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
        assert data["role"] == "user"

    def test_register_duplicate_username(self, client, test_user):
        """Test registration with duplicate username"""
        response = client.post(
            "/api/v1/users/register",
            json={
                "username": "testuser",  # Already exists
                "email": "new@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestUserProfileAPI:
    """Test user profile management API endpoints"""

    def test_get_current_user_info(self, client, test_user):
        """Get current user information"""
        headers = get_auth_headers("testuser")
        response = client.get("/api/v1/users/me", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        assert data["role"] == "user"

    def test_update_user_info_username(self, client, test_user):
        """Update username"""
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
        assert data["access_token"] != ""

    def test_update_user_info_email(self, client, test_user):
        """Update email address"""
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

    def test_update_user_info_both(self, client, test_user):
        """Update both username and email"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me",
            json={"username": "newname", "email": "new@example.com"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user"]["username"] == "newname"
        assert data["user"]["email"] == "new@example.com"

    def test_update_user_info_no_changes(self, client, test_user):
        """Update with no actual changes"""
        headers = get_auth_headers("testuser")
        response = client.put("/api/v1/users/me", json={}, headers=headers)

        # API accepts empty update and returns current user info
        assert response.status_code == status.HTTP_200_OK

    def test_change_password(self, client, test_user):
        """Change user password"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "testpassword", "new_password": "newpassword123"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK

    def test_change_password_wrong_current(self, client, test_user):
        """Change password with wrong current password"""
        headers = get_auth_headers("testuser")
        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "wrongpassword", "new_password": "newpassword123"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_user_account(self, client, test_user):
        """Delete user account"""
        headers = get_auth_headers("testuser")
        headers["Content-Type"] = "application/json"
        response = client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "testpassword"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK

    def test_delete_user_account_wrong_password(self, client, test_user):
        """Delete account with wrong password"""
        headers = get_auth_headers("testuser")
        headers["Content-Type"] = "application/json"
        response = client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"password": "wrongpassword"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestUserApprovalAPI:
    """Test user approval API endpoints"""

    def test_approve_user_as_admin(self, client, admin_user, unapproved_user):
        """Admin can approve users"""
        headers = get_auth_headers("admin")
        response = client.post(
            f"/api/v1/users/approve/{unapproved_user.id}",
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True

    def test_approve_user_as_non_admin(self, client, test_user, unapproved_user):
        """Non-admin cannot approve users"""
        headers = get_auth_headers("testuser")
        response = client.post(
            f"/api/v1/users/approve/{unapproved_user.id}",
            headers=headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_approve_nonexistent_user(self, client, admin_user):
        """Approve non-existent user"""
        headers = get_auth_headers("admin")
        response = client.post(
            "/api/v1/users/approve/999",
            headers=headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUserRoleManagementAPI:
    """Test user role management API endpoints"""

    def test_change_role_as_admin(self, client, admin_user, test_user):
        """Admin can change user roles"""
        headers = get_auth_headers("admin")
        response = client.put(
            f"/api/v1/users/role/{test_user.id}",
            json={"role": "operator"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["role"] == "operator"

    def test_change_role_as_non_admin(self, client, test_user, operator_user):
        """Non-admin cannot change user roles"""
        headers = get_auth_headers("testuser")
        response = client.put(
            f"/api/v1/users/role/{operator_user.id}",
            json={"role": "admin"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_change_role_nonexistent_user(self, client, admin_user):
        """Change role of non-existent user"""
        headers = get_auth_headers("admin")
        response = client.put(
            "/api/v1/users/role/999",
            json={"role": "operator"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_change_role_invalid_role(self, client, admin_user, test_user):
        """Change to invalid role"""
        headers = get_auth_headers("admin")
        response = client.put(
            f"/api/v1/users/role/{test_user.id}",
            json={"role": "invalid_role"},
            headers=headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestAdminUserManagementAPI:
    """Test administrative user management API endpoints"""

    def test_get_all_users_as_admin(self, client, admin_user):
        """Admin can get all users"""
        headers = get_auth_headers("admin")
        response = client.get("/api/v1/users", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_all_users_as_non_admin(self, client, test_user):
        """Non-admin cannot get all users"""
        headers = get_auth_headers("testuser")
        response = client.get("/api/v1/users", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_user_as_admin(self, client, admin_user, test_user):
        """Admin can delete other users"""
        headers = get_auth_headers("admin")
        response = client.delete(f"/api/v1/users/{test_user.id}", headers=headers)

        assert response.status_code == status.HTTP_200_OK

    def test_delete_user_as_non_admin(self, client, test_user, operator_user):
        """Non-admin cannot delete other users"""
        headers = get_auth_headers("testuser")
        response = client.delete(f"/api/v1/users/{operator_user.id}", headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_nonexistent_user(self, client, admin_user):
        """Delete non-existent user"""
        headers = get_auth_headers("admin")
        response = client.delete("/api/v1/users/999", headers=headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAuthenticationRequiredAPI:
    """Test that endpoints require authentication"""

    def test_get_current_user_no_auth(self, client):
        """Get current user without authentication"""
        response = client.get("/api/v1/users/me")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_user_no_auth(self, client):
        """Update user without authentication"""
        response = client.put("/api/v1/users/me", json={"username": "new"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_approve_user_no_auth(self, client):
        """Approve user without authentication"""
        response = client.post("/api/v1/users/approve/1")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_change_role_no_auth(self, client):
        """Change role without authentication"""
        response = client.put("/api/v1/users/role/1", json={"role": "admin"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
