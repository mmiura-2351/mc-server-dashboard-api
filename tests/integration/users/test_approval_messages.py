from fastapi import status

from tests.helpers.auth import auth_headers_for as get_auth_headers


class TestApprovalMessages:
    def test_unapproved_user_login_returns_detailed_message(
        self, client, db, unapproved_user
    ):
        """An unapproved user receives a detailed message at login time."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "Account pending approval" in data["detail"]
        assert "administrator" in data["detail"]
        assert "approve your account" in data["detail"]

    def test_approved_user_login_succeeds(self, client, db, test_user):
        """An approved user logs in successfully."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpassword"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_first_user_registration_auto_approved(self, client):
        """The first registered user is auto-approved."""
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
        assert data["is_approved"] is True

    def test_second_user_registration_pending_approval(self, client, db, admin_user):
        """The second registered user is pending approval."""
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
        assert data["is_approved"] is False

    def test_admin_can_approve_user(self, client, db, admin_user, unapproved_user):
        """An admin can approve a user."""
        headers = get_auth_headers("admin")
        response = client.post(
            f"/api/v1/users/approve/{unapproved_user.id}", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True

    def test_approved_user_can_login_after_approval(
        self, client, db, admin_user, unapproved_user
    ):
        """A user can log in after being approved."""
        # First, the admin approves the user.
        headers = get_auth_headers("admin")
        approve_response = client.post(
            f"/api/v1/users/approve/{unapproved_user.id}", headers=headers
        )
        assert approve_response.status_code == status.HTTP_200_OK

        # Then attempt login as the now-approved user.
        login_response = client.post(
            "/api/v1/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert login_response.status_code == status.HTTP_200_OK
        data = login_response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_user_status_reflects_approval_state(
        self, client, db, test_user, unapproved_user
    ):
        """The user-info API reflects the approval state correctly."""
        # Fetch info for the approved user.
        headers = get_auth_headers("testuser")
        response = client.get("/api/v1/users/me", headers=headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_approved"] is True
        assert data["is_active"] is True

    def test_error_message_consistency(self, client, db, unapproved_user):
        """The error message is internally consistent."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        error_detail = response.json()["detail"]

        # Verify the message contains all required elements.
        required_elements = [
            "Account pending approval",
            "administrator",
            "approve your account",
        ]

        for element in required_elements:
            assert element in error_detail, f"Error message should contain '{element}'"

    def test_non_existent_user_login_different_error(self, client):
        """Login for a non-existent user surfaces a different error message."""
        response = client.post(
            "/api/v1/auth/token", data={"username": "nonexistent", "password": "password"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]
        # Confirm the response is not the pending-approval message.
        assert "pending approval" not in response.json()["detail"].lower()

    def test_wrong_password_different_error(self, client, db, test_user):
        """A wrong password surfaces a different error message."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "wrongpassword"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]
        # Confirm the response is not the pending-approval message.
        assert "pending approval" not in response.json()["detail"].lower()
