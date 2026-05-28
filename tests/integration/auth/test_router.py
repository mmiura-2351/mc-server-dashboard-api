from fastapi import status


class TestAuthRouter:
    def test_login_success(self, client, test_user):
        """A valid user logs in successfully."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpassword"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_username(self, client):
        """Login fails for an unknown username."""
        response = client.post(
            "/api/v1/auth/token", data={"username": "nonexistent", "password": "password"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]

    def test_login_invalid_password(self, client, test_user):
        """Login fails with a wrong password."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "wrongpassword"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Incorrect username or password" in response.json()["detail"]

    def test_login_unapproved_user(self, client, unapproved_user):
        """Login fails for an unapproved user."""
        response = client.post(
            "/api/v1/auth/token",
            data={"username": "unapproved", "password": "unapprovedpassword"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Account pending approval" in response.json()["detail"]

    def test_login_inactive_user(self, client, db, test_user):
        """Deactivated user cannot authenticate (Resolves #232)."""
        from app.users.models import User

        # Deactivate the otherwise-valid, approved test user.
        user = db.query(User).filter(User.id == test_user.id).first()
        user.is_active = False
        db.commit()

        response = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpassword"},
        )

        # Service returns `None` -> router maps to 401 (matches refresh-token
        # path in `app/auth/api/router.py`).
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_admin_user(self, client, admin_user):
        """An admin user logs in successfully."""
        response = client.post(
            "/api/v1/auth/token", data={"username": "admin", "password": "adminpassword"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_missing_username(self, client):
        """Login fails when the username is missing."""
        response = client.post("/api/v1/auth/token", data={"password": "password"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_login_missing_password(self, client):
        """Login fails when the password is missing."""
        response = client.post("/api/v1/auth/token", data={"username": "testuser"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
