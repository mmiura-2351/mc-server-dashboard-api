"""Smoke tests for the visibility router mounted under /api/v1/visibility.

These tests pin the wire contract introduced by Issue #288, namely that
the router from `app.core.visibility_router` is mounted on the FastAPI
application and the import of `get_current_user` resolves at runtime.
They intentionally stay at the HTTP-edge to keep the suite fast — the
service-layer behaviour is covered exhaustively by
`tests/unit/core/visibility` and `tests/integration/core/visibility`.
"""

from fastapi import status


def _auth_headers(client, username: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestVisibilityRouterMounted:
    def test_unauthenticated_request_returns_401(self, client):
        """Without a bearer token the mounted router returns 401.

        Pre-Issue #288 the route was not registered at all, so the same
        request would have returned 404. The 401 below proves the router
        is now wired into the app and the `get_current_user` dependency
        import resolves at runtime.
        """
        response = client.get("/api/v1/visibility/server/1")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_request_reaches_handler(self, client, test_user):
        """An authenticated request reaches the handler body.

        We hit a server resource that does not exist for this user; the
        handler runs ownership checks and surfaces a 404 from
        `_check_resource_ownership_or_admin`. Reaching that branch
        confirms (a) the route is registered, (b) the bearer token is
        accepted by `get_current_user`, and (c) the DI graph for
        `VisibilityService` resolves successfully.
        """
        headers = _auth_headers(client, "testuser", "testpassword")
        response = client.get("/api/v1/visibility/server/9999", headers=headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Server not found"
