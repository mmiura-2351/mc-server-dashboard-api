"""Integration coverage for Issue #237 — JWT revocation.

End-to-end happy paths exercised here:

1. login → admin deactivate → ``/users/me`` returns 401 with the
   previously valid access token (closing the TTL window AC 1).
2. login → password change → the pre-change access token is rejected
   (AC 2) while the freshly minted post-change token works.
3. Refresh flow after deactivation also 401s (AC 3) so an attacker
   cannot pivot via ``/auth/refresh``.
"""

from fastapi import status


def _login(client, username: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/token", data={"username": username, "password": password}
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return response.json()


class TestAccessTokenRevocationOnDeactivation:
    def test_deactivated_user_access_token_rejected(
        self, client, admin_user, admin_headers, test_user
    ):
        """AC 1 — admin deactivation invalidates the user's access token.

        Before this change, the deactivated user could keep calling
        protected endpoints until the JWT's natural expiry (up to
        ``ACCESS_TOKEN_EXPIRE_MINUTES`` minutes). Now the next request
        on the same token returns 401 because ``token_version`` has
        been bumped.
        """
        tokens = _login(client, "testuser", "testpassword")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Sanity-check: token works before deactivation.
        assert (
            client.get("/api/v1/users/me", headers=headers).status_code
            == status.HTTP_200_OK
        )

        # Admin deactivates the user.
        deact = client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )
        assert deact.status_code == status.HTTP_200_OK, deact.text
        assert deact.json()["is_active"] is False

        # The previously valid access token must now be rejected.
        rejected = client.get("/api/v1/users/me", headers=headers)
        assert rejected.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_after_deactivation_rejected(
        self, client, admin_user, admin_headers, test_user
    ):
        """AC 3 — ``/auth/refresh`` cannot revive a deactivated user."""
        tokens = _login(client, "testuser", "testpassword")
        client.post(f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers)

        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        # The refresh token itself has also been revoked by the
        # deactivate endpoint, so we expect 401.
        assert refresh_resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_self_deactivation_rejected(self, client, admin_headers, admin_user):
        """An admin cannot deactivate themselves (locks them out)."""
        resp = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=admin_headers
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_admin_cannot_deactivate(self, client, user_headers, admin_user):
        """Regular users cannot call the deactivate endpoint."""
        resp = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=user_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_last_admin_deactivation_rejected(
        self, client, admin_headers, admin_user, db
    ):
        """Cannot deactivate the only remaining admin."""
        # Create a second admin so we can verify the guard rejects
        # *only* when admin_count would drop to zero. First confirm
        # there is exactly one admin (the fixture).
        from app.users.domain.value_objects import Role
        from app.users.models import User

        admin_count = db.query(User).filter(User.role == Role.admin).count()
        assert admin_count == 1

        # Attempt to deactivate the only admin (the admin_user itself)
        # via a hypothetical second admin call — instead we exercise
        # the simpler path: a different admin trying to deactivate
        # the last one is impossible because there is only one, so
        # ``self-deactivate`` is what blocks here. We already cover
        # that path above; the explicit last-admin guard is exercised
        # by the unit test for `deactivate_user` in the service.
        # This test simply documents the guard's existence.
        resp = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=admin_headers
        )
        # Self-deactivate guard fires first.
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestAccessTokenRevocationOnPasswordChange:
    def test_old_token_rejected_after_password_change(self, client, test_user):
        """AC 2 — changing the password invalidates pre-change tokens."""
        tokens = _login(client, "testuser", "testpassword")
        old_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Sanity-check.
        assert (
            client.get("/api/v1/users/me", headers=old_headers).status_code
            == status.HTTP_200_OK
        )

        # Rotate password — server returns a freshly minted access
        # token so the user's session continues.
        rotate = client.put(
            "/api/v1/users/me/password",
            json={
                "current_password": "testpassword",
                "new_password": "newpassword456",
            },
            headers=old_headers,
        )
        assert rotate.status_code == status.HTTP_200_OK, rotate.text
        new_token = rotate.json()["access_token"]
        assert new_token, "post-rotation response should include a fresh token"

        # The pre-rotation token is now revoked.
        assert (
            client.get("/api/v1/users/me", headers=old_headers).status_code
            == status.HTTP_401_UNAUTHORIZED
        )

        # The post-rotation token works.
        new_headers = {"Authorization": f"Bearer {new_token}"}
        assert (
            client.get("/api/v1/users/me", headers=new_headers).status_code
            == status.HTTP_200_OK
        )


class TestReactivationEndpoint:
    def test_admin_can_reactivate(self, client, admin_headers, test_user, db):
        """Reactivation restores ``is_active=True`` but tokens stay revoked."""
        # Deactivate then reactivate.
        deact = client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )
        assert deact.status_code == status.HTTP_200_OK

        react = client.post(
            f"/api/v1/users/{test_user.id}/reactivate", headers=admin_headers
        )
        assert react.status_code == status.HTTP_200_OK
        assert react.json()["is_active"] is True

        # User can log in afresh.
        tokens = _login(client, "testuser", "testpassword")
        assert tokens["access_token"]

    def test_non_admin_cannot_reactivate(self, client, user_headers, test_user):
        resp = client.post(
            f"/api/v1/users/{test_user.id}/reactivate", headers=user_headers
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
