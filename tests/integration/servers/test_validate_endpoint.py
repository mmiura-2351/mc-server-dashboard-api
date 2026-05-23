"""Integration tests for ``POST /api/v1/servers/validate`` wiring.

Issue #338: PR #334 added the endpoint to
``app/servers/routers/management.py`` but it was not re-registered on
the unified router (``app/servers/routers/__init__.py``) and therefore
returned 404 in production. These tests guard against that regression
by hitting the endpoint through the real FastAPI app/router stack and
asserting the response shape, **not** by importing the handler
function directly.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.error_schemas import ErrorDetail
from app.main import app
from app.servers.api.dependencies import get_server_service
from app.servers.schemas import ValidateServerCreationResponse


def _valid_payload(**overrides):
    payload = {
        "name": "validate-test-server",
        "minecraft_version": "1.20.1",
        "server_type": "vanilla",
        "port": 25565,
        "max_memory": 1024,
        "max_players": 20,
    }
    payload.update(overrides)
    return payload


def _override_service(*, response: ValidateServerCreationResponse):
    """Install a dependency override that returns ``response`` from
    ``ServerService.validate_creation_request``.

    Returns a teardown callable; tests are expected to invoke it in a
    ``finally`` (or use the helper fixture below) to keep app state
    clean across tests running in parallel.
    """

    class _StubService:
        validate_creation_request = AsyncMock(return_value=response)

    stub = _StubService()
    app.dependency_overrides[get_server_service] = lambda: stub

    def _teardown():
        app.dependency_overrides.pop(get_server_service, None)

    return stub, _teardown


class TestValidateEndpointWiring:
    """Issue #338 — endpoint must be reachable on the unified router."""

    def test_unauthenticated_request_returns_401(self, client: TestClient):
        """No bearer token → 401, proving the route is mounted (not 404)."""
        response = client.post("/api/v1/servers/validate", json=_valid_payload())

        # The critical assertion is "not 404": prior to the fix the
        # endpoint was unmounted and FastAPI returned 404 here.
        assert response.status_code != status.HTTP_404_NOT_FOUND
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_valid_request_returns_200(
        self, client: TestClient, admin_headers
    ):
        """Happy path: service stub returns ``valid=True`` → 200 passthrough."""
        expected = ValidateServerCreationResponse(
            valid=True, warnings=[], suggested_ports=[25565, 25566, 25567]
        )
        stub, teardown = _override_service(response=expected)
        try:
            response = client.post(
                "/api/v1/servers/validate",
                headers=admin_headers,
                json=_valid_payload(),
            )
        finally:
            teardown()

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["valid"] is True
        assert body["warnings"] == []
        assert body["suggested_ports"] == [25565, 25566, 25567]
        stub.validate_creation_request.assert_awaited_once()

    def test_authenticated_request_with_invalid_port_returns_422(
        self, client: TestClient, admin_headers
    ):
        """Pydantic-level validation (port out of 1024-65535) → 422.

        Confirms the route is wired through the schema validator, not
        just the auth gate.
        """
        response = client.post(
            "/api/v1/servers/validate",
            headers=admin_headers,
            json=_valid_payload(port=1023),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_authenticated_request_with_name_conflict_returns_200_with_warning(
        self, client: TestClient, admin_headers
    ):
        """Domain conflict → 200 + ``valid=False`` + ``SERVER_NAME_CONFLICT``."""
        expected = ValidateServerCreationResponse(
            valid=False,
            warnings=[
                ErrorDetail(
                    field=None,
                    message="A server named 'validate-test-server' already exists.",
                    code="SERVER_NAME_CONFLICT",
                )
            ],
            suggested_ports=[25566, 25567, 25568],
        )
        stub, teardown = _override_service(response=expected)
        try:
            response = client.post(
                "/api/v1/servers/validate",
                headers=admin_headers,
                json=_valid_payload(),
            )
        finally:
            teardown()

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["valid"] is False
        codes = {w["code"] for w in body["warnings"]}
        assert "SERVER_NAME_CONFLICT" in codes
        assert body["suggested_ports"] == [25566, 25567, 25568]
        stub.validate_creation_request.assert_awaited_once()


@pytest.mark.parametrize("path_id", ["validate"])
def test_validate_path_not_shadowed_by_server_id_route(
    client: TestClient, admin_headers, path_id
):
    """Ordering guard: ``/validate`` must be matched before ``/{server_id}``.

    If a future refactor swaps the registration order, ``POST
    /api/v1/servers/validate`` would fall through to a ``server_id``
    handler that expects an integer path parameter and the response
    would not be 200/401/422 from the validate handler. We assert the
    response comes from the validate handler by checking the response
    is reachable as the validate endpoint (401 without auth).
    """
    response = client.post(f"/api/v1/servers/{path_id}", json=_valid_payload())
    # If shadowed by `/{server_id}` (PUT/GET/DELETE only) the POST would
    # 405; if `server_id` accepted POST and parsed "validate" as int it
    # would 422 with a path-param error. Either way, 401 here proves the
    # validate route owns this path.
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
