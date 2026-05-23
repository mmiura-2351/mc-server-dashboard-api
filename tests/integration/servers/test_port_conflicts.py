from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.servers.models import ServerStatus, ServerType
from tests.helpers.servers import make_server

# Every test in this file calls `POST /api/v1/servers`, which triggers
# real Java discovery inside MinecraftServerManager — skip without a JRE.
pytestmark = pytest.mark.requires_java


class TestServerPortConflicts:
    def test_create_server_allows_duplicate_ports(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        """Test that creating servers with duplicate ports is now allowed during creation"""
        # First, create a version in the database to ensure it's supported
        from app.core.datetime_utils import utcnow
        from app.versions.models import MinecraftVersion

        version = MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=utcnow(),
            is_stable=True,
            is_active=True,
        )
        db.add(version)
        db.commit()
        # Create a server with port 25565
        make_server(
            db,
            admin_user,
            name="First Server",
            description="A server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/first_server",
            port=25565,
        )

        # Mock JAR download and caching to avoid actual network calls
        with (
            patch(
                "app.versions.application.jar_cache_manager.jar_cache_manager.get_or_download_jar"
            ) as mock_cache,
            patch(
                "app.versions.application.jar_cache_manager.jar_cache_manager.copy_jar_to_server"
            ) as mock_copy,
        ):
            mock_cache.return_value = "/cache/test-vanilla-1.21.6.jar"
            mock_copy.return_value = "/server/server.jar"

            # Try to create another server with the same port - this should now succeed
            server_data = {
                "name": "Second Server",
                "description": "Another server with same port",
                "minecraft_version": "1.21.6",
                "server_type": "vanilla",
                "port": 25565,
                "max_memory": 1024,
                "max_players": 20,
            }

            response = client.post(
                "/api/v1/servers/", headers=admin_headers, json=server_data
            )

            assert response.status_code == status.HTTP_201_CREATED
            server_response = response.json()
            assert server_response["port"] == 25565
            assert server_response["name"] == "Second Server"

        # Cleanup
        import shutil
        from pathlib import Path

        server_dir = Path(server_response["directory_path"])
        if server_dir.exists():
            shutil.rmtree(server_dir)

    def test_create_server_port_conflict_with_stopped_server_allowed(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        """Test that creating a server succeeds when port conflicts with stopped server"""
        # First, create a version in the database to ensure it's supported
        from app.core.datetime_utils import utcnow
        from app.versions.models import MinecraftVersion

        version = MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=utcnow(),
            is_stable=True,
            is_active=True,
        )
        db.add(version)
        db.commit()

        # Create a stopped server with port 25566
        make_server(
            db,
            admin_user,
            name="Stopped Server",
            description="A stopped server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/stopped_server",
            port=25566,
        )

        # Mock JAR download and caching to avoid actual network calls
        with (
            patch(
                "app.versions.application.jar_cache_manager.jar_cache_manager.get_or_download_jar"
            ) as mock_cache,
            patch(
                "app.versions.application.jar_cache_manager.jar_cache_manager.copy_jar_to_server"
            ) as mock_copy,
        ):
            mock_cache.return_value = "/cache/test-vanilla-1.21.6.jar"
            mock_copy.return_value = "/server/server.jar"

            # Try to create another server with the same port as stopped server
            server_data = {
                "name": "New Server",
                "description": "This should succeed",
                "minecraft_version": "1.21.6",
                "server_type": "vanilla",
                "port": 25566,
                "max_memory": 1024,
                "max_players": 20,
            }

            response = client.post(
                "/api/v1/servers/", headers=admin_headers, json=server_data
            )

            assert response.status_code == status.HTTP_201_CREATED
            server_response = response.json()
            assert server_response["port"] == 25566
            assert server_response["name"] == "New Server"

        # Cleanup
        import shutil
        from pathlib import Path

        server_dir = Path(server_response["directory_path"])
        if server_dir.exists():
            shutil.rmtree(server_dir)

    def test_create_server_rejects_duplicate_port_when_existing_is_active(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        """Issue #33: creation must reject a port already held by an
        active server (``starting`` or ``running``) and return a 409 with
        structured ``suggested_ports`` so the frontend can offer free
        alternatives without a second round-trip.

        Stopped servers do NOT block reuse — that behaviour is preserved
        by the two preceding tests.
        """
        # First, create a version in the database to ensure it's supported
        from app.core.datetime_utils import utcnow
        from app.versions.models import MinecraftVersion

        version = MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=utcnow(),
            is_stable=True,
            is_active=True,
        )
        db.add(version)
        db.commit()

        # Create a starting server with port 25567 — this should block reuse
        make_server(
            db,
            admin_user,
            name="Starting Server",
            description="A starting server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            status=ServerStatus.starting,
            directory_path="./servers/starting_server",
            port=25567,
        )

        # Mock JAR download and caching to avoid actual network calls
        with (
            patch(
                "app.versions.application.jar_cache_manager.jar_cache_manager.get_or_download_jar"
            ) as mock_cache,
            patch(
                "app.versions.application.jar_cache_manager.jar_cache_manager.copy_jar_to_server"
            ) as mock_copy,
        ):
            mock_cache.return_value = "/cache/test-vanilla-1.21.6.jar"
            mock_copy.return_value = "/server/server.jar"

            # Try to create another server with the same port — must 409
            server_data = {
                "name": "New Server",
                "description": "Conflicts with active server on 25567",
                "minecraft_version": "1.21.6",
                "server_type": "vanilla",
                "port": 25567,
                "max_memory": 1024,
                "max_players": 20,
            }

            response = client.post(
                "/api/v1/servers/", headers=admin_headers, json=server_data
            )

            assert response.status_code == status.HTTP_409_CONFLICT
            body = response.json()
            # Standardized error envelope (Issue #76): ``error`` is the
            # machine code, ``details`` is a list of ErrorDetail entries.
            assert body["error"] == "SERVER_PORT_CONFLICT"
            details = body["details"]
            assert isinstance(details, list) and len(details) >= 1

            # First detail is the conflict itself; subsequent entries
            # (if any) are PORT_SUGGESTION candidates populated by
            # ``port_allocator.find_available_ports``.
            conflict = next(d for d in details if d["code"] == "PORT_IN_USE")
            assert conflict["field"] == "port"
            assert "25567" in conflict["message"]
            assert "Starting Server" in conflict["message"]

            suggestions = [
                int(d["message"]) for d in details if d["code"] == "PORT_SUGGESTION"
            ]
            # Suggestions start after the held port and never include it.
            assert 25567 not in suggestions
            for suggested in suggestions:
                assert suggested >= 25568
