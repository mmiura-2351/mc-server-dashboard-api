"""Integration tests for the port-discovery endpoints (Issue #32).

These exercise:
  * ``GET /api/v1/servers/ports/available`` — bulk discovery with count clamping
    and the ``NoAvailablePortError`` path.
  * ``GET /api/v1/servers/ports/check/{port}`` — individual port checks for
    available / held-by-active-server / held-by-stopped-server cases.

Stopped servers do not block re-use — that contract matches the
existing :mod:`tests.integration.servers.test_port_conflicts` suite.
"""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from app.servers.models import ServerStatus, ServerType
from tests.helpers.servers import make_server


class TestListAvailablePorts:
    def test_returns_requested_count_starting_at_default(
        self, client: TestClient, admin_headers
    ):
        """No active servers → first ``count`` ports from ``start`` are free."""
        response = client.get(
            "/api/v1/servers/ports/available",
            headers=admin_headers,
            params={"start": 25565, "count": 3},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["start_port"] == 25565
        assert body["ports"] == [25565, 25566, 25567]

    def test_skips_active_ports(self, client: TestClient, admin_headers, db, admin_user):
        """Ports held by active servers are skipped, stopped are reusable."""
        # Active (starting) — blocks reuse
        make_server(
            db,
            admin_user,
            name="Active Server",
            port=25565,
            status=ServerStatus.starting,
            directory_path="./servers/active_server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
        )
        # Stopped — does NOT block reuse
        make_server(
            db,
            admin_user,
            name="Stopped Server",
            port=25566,
            status=ServerStatus.stopped,
            directory_path="./servers/stopped_server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
        )

        response = client.get(
            "/api/v1/servers/ports/available",
            headers=admin_headers,
            params={"start": 25565, "count": 3},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        # 25565 is skipped (active); 25566 is allowed (stopped); then 25567/25568.
        assert body["ports"] == [25566, 25567, 25568]

    def test_count_above_50_rejected_by_validation(
        self, client: TestClient, admin_headers
    ):
        """``count`` is clamped at 50 by the Pydantic ``Query(le=50)`` constraint."""
        response = client.get(
            "/api/v1/servers/ports/available",
            headers=admin_headers,
            params={"start": 25565, "count": 51},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = response.json()
        # Standard error envelope from the global validation handler.
        assert body["error"] == "VALIDATION_ERROR"

    def test_count_50_accepted_returns_up_to_50(self, client: TestClient, admin_headers):
        """``count=50`` is the upper bound and returns exactly that many ports."""
        response = client.get(
            "/api/v1/servers/ports/available",
            headers=admin_headers,
            params={"start": 25565, "count": 50},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["ports"]) == 50
        assert body["ports"][0] == 25565
        assert body["ports"][-1] == 25614

    def test_unauthenticated_returns_401(self, client: TestClient):
        """No bearer token → 401 (FastAPI's auth dependency)."""
        response = client.get("/api/v1/servers/ports/available")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


class TestCheckPort:
    def test_port_available_when_no_holder(self, client: TestClient, admin_headers):
        response = client.get("/api/v1/servers/ports/check/25565", headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {"port": 25565, "available": True, "holder": None}

    def test_port_unavailable_when_active_server_holds(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        make_server(
            db,
            admin_user,
            name="Live Server",
            port=25599,
            status=ServerStatus.running,
            directory_path="./servers/live_server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
        )

        response = client.get("/api/v1/servers/ports/check/25599", headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["port"] == 25599
        assert body["available"] is False
        assert body["holder"] == "Live Server"

    def test_stopped_server_does_not_block(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        """Stopped servers don't count as port holders — port is still available."""
        make_server(
            db,
            admin_user,
            name="Sleeping",
            port=25600,
            status=ServerStatus.stopped,
            directory_path="./servers/sleeping",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
        )

        response = client.get("/api/v1/servers/ports/check/25600", headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["available"] is True
        assert body["holder"] is None

    def test_port_below_1024_rejected(self, client: TestClient, admin_headers):
        """Well-known ports below 1024 are rejected by the path constraint."""
        response = client.get("/api/v1/servers/ports/check/80", headers=admin_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_unauthenticated_returns_401(self, client: TestClient):
        response = client.get("/api/v1/servers/ports/check/25565")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
