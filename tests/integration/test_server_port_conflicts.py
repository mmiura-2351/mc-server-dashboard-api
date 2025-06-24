from fastapi import status
from fastapi.testclient import TestClient

from app.servers.models import Server, ServerStatus, ServerType


class TestServerPortConflicts:
    def test_create_server_allows_duplicate_ports(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        """Test that creating servers with duplicate ports is now allowed during creation"""
        # First, create a version in the database to ensure it's supported
        from app.versions.models import MinecraftVersion
        from datetime import datetime

        version = MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=datetime.utcnow(),
            is_stable=True,
            is_active=True
        )
        db.add(version)
        db.commit()
        # Create a server with port 25565
        first_server = Server(
            name="First Server",
            description="A server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/first_server",
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
        )
        db.add(first_server)
        db.commit()

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
        from app.versions.models import MinecraftVersion
        from datetime import datetime
        
        version = MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=datetime.utcnow(),
            is_stable=True,
            is_active=True
        )
        db.add(version)
        db.commit()
        
        # Create a stopped server with port 25566
        stopped_server = Server(
            name="Stopped Server",
            description="A stopped server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/stopped_server",
            port=25566,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
        )
        db.add(stopped_server)
        db.commit()

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

    def test_create_server_allows_duplicate_ports_with_any_status(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        """Test that creating servers with duplicate ports is allowed regardless of existing server status"""
        # First, create a version in the database to ensure it's supported
        from app.versions.models import MinecraftVersion
        from datetime import datetime
        
        version = MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=datetime.utcnow(),
            is_stable=True,
            is_active=True
        )
        db.add(version)
        db.commit()
        
        # Create a starting server with port 25567
        starting_server = Server(
            name="Starting Server",
            description="A starting server",
            minecraft_version="1.21.6",
            server_type=ServerType.vanilla,
            status=ServerStatus.starting,
            directory_path="./servers/starting_server",
            port=25567,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
        )
        db.add(starting_server)
        db.commit()

        # Try to create another server with the same port - this should now succeed
        server_data = {
            "name": "New Server",
            "description": "This should succeed",
            "minecraft_version": "1.21.6",
            "server_type": "vanilla",
            "port": 25567,
            "max_memory": 1024,
            "max_players": 20,
        }

        response = client.post(
            "/api/v1/servers/", headers=admin_headers, json=server_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        server_response = response.json()
        assert server_response["port"] == 25567
        assert server_response["name"] == "New Server"

        # Cleanup
        import shutil
        from pathlib import Path

        server_dir = Path(server_response["directory_path"])
        if server_dir.exists():
            shutil.rmtree(server_dir)
