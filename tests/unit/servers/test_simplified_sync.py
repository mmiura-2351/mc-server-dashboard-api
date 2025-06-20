"""Test bidirectional synchronization between database and server.properties"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from time import sleep

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.servers.models import Server, ServerStatus, ServerType
from app.servers.schemas import ServerUpdateRequest
from app.servers.service import server_service
from app.services.simplified_sync import simplified_sync_service
from app.users.models import User, Role


@pytest.fixture
def test_db():
    """Create a test database"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(test_db):
    """Create a test user"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password="hashed",
        role=Role.admin,
        is_active=True,
        is_approved=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture
def test_server(test_db, test_user):
    """Create a test server with temporary directory"""
    with tempfile.TemporaryDirectory() as temp_dir:
        server = Server(
            name="Test Server",
            description="Test server for bidirectional sync",
            server_type=ServerType.vanilla,
            minecraft_version="1.20.1",
            port=25565,
            max_memory=1024,
            max_players=20,
            directory_path=temp_dir,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
        )
        test_db.add(server)
        test_db.commit()
        test_db.refresh(server)

        # Create server.properties file
        properties_path = Path(temp_dir) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")

        yield server


class TestBidirectionalSync:
    """Test cases for bidirectional synchronization"""

    def test_file_port_extraction(self, test_server):
        """Test extracting port from server.properties file"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        port = simplified_sync_service.get_properties_file_port(properties_path)
        assert port == 25565

    def test_simplified_logic_explanation(self, test_db, test_server):
        """
        Test that demonstrates the simplified logic principle.

        Key insight: Since API updates always modify both DB and file,
        any difference indicates manual file edit.
        """
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Initially, DB and file should match (both 25565)
        initial_port = simplified_sync_service.get_properties_file_port(properties_path)
        assert initial_port == test_server.port == 25565

        # Simulate manual file edit (only file changes, DB unchanged)
        with open(properties_path, "w") as f:
            f.write("server-port=25599\n")
            f.write("max-players=20\n")

        # Now DB (25565) and file (25599) differ
        # Simplified logic: file must be manually edited, sync file → DB
        success, description = simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, test_db
        )

        assert success is True
        assert "manual edit detected" in description.lower()

        # Database should now match the manually edited file
        test_db.refresh(test_server)
        assert test_server.port == 25599

    def test_sync_from_file_to_database_when_different(self, test_db, test_server):
        """Test syncing from file to database when ports differ (simplified logic)"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Update file with different port (manual edit simulation)
        with open(properties_path, "w") as f:
            f.write("server-port=25570\n")
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")

        # Perform simplified sync
        success, description = simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, test_db
        )

        assert success is True
        assert "Manual edit detected" in description
        assert "synced file to database" in description

        # Verify database was updated
        test_db.refresh(test_server)
        assert test_server.port == 25570

    def test_no_sync_when_ports_match_simplified(self, test_db, test_server):
        """Test no sync needed when ports already match (simplified logic)"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # File and database already have same port (25565)
        # In simplified logic, this means no manual edit occurred
        success, description = simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, test_db
        )

        assert success is True
        assert "No sync needed" in description
        assert "already in sync" in description

    def test_manual_file_edit_detection(self, test_db, test_server):
        """Test detection of manual file edits in simplified logic"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Simulate manual file edit by changing port in file only
        # (This would happen when user manually edits server.properties)
        with open(properties_path, "w") as f:
            f.write("server-port=25575\n")  # Different from DB (25565)
            f.write("max-players=20\n")
            f.write("motd=Manually Edited Server\n")

        success, description = simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, test_db
        )

        assert success is True
        assert "manual edit detected" in description.lower()

        # Verify database was updated to match file
        test_db.refresh(test_server)
        assert test_server.port == 25575

    @pytest.mark.asyncio
    async def test_api_port_update_direct_simplified(self, test_db, test_server):
        """
        Test API port update via direct port field.

        In simplified logic: API updates modify both DB and file simultaneously,
        so after API update, they should be in sync (no manual edit detected).
        """
        update_request = ServerUpdateRequest(port=25590)

        with patch.object(
            server_service.validation_service,
            "validate_server_exists",
            return_value=test_server,
        ):
            with patch.object(
                server_service.database_service, "update_server_record"
            ) as mock_update:
                # Set initial value different from update value
                test_server.port = 25565

                def update_side_effect(server, request, db):
                    server.port = 25590  # Simulate database update
                    return server

                mock_update.side_effect = update_side_effect

                # Call update_server (this should update both DB and file)
                await server_service.update_server(
                    test_server.id, update_request, test_db
                )

        # Verify server.properties was updated to match database
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25590" in content

        # After API update, DB and file should be in sync
        # So sync check should report "no sync needed"
        success, description = simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, test_db
        )
        assert success is True
        assert "No sync needed" in description

    @pytest.mark.asyncio
    async def test_api_port_update_via_server_properties(self, test_db, test_server):
        """Test API port update via server_properties field"""
        update_request = ServerUpdateRequest(
            server_properties={"server-port": "25600", "motd": "Updated MOTD"}
        )

        with patch.object(
            server_service.validation_service,
            "validate_server_exists",
            return_value=test_server,
        ):
            with patch.object(
                server_service.database_service, "update_server_record"
            ) as mock_update:
                # Simulate database update - the service should set port from server_properties
                def update_side_effect(server, request, db):
                    server.port = request.port  # Should be set to 25600
                    return server

                mock_update.side_effect = update_side_effect

                # Call update_server
                result = await server_service.update_server(
                    test_server.id, update_request, test_db
                )

        # Verify request.port was set from server_properties
        assert update_request.port == 25600

        # Also test direct sync method
        test_server.port = 25600
        await server_service._sync_server_properties_after_update(
            test_server, {"motd": "Updated MOTD"}
        )

        # Verify server.properties was updated
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25600" in content
            assert "motd=Updated MOTD" in content

    def test_invalid_port_in_server_properties(self, test_db, test_server):
        """Test handling of invalid port in server_properties"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Write invalid port
        with open(properties_path, "w") as f:
            f.write("server-port=invalid\n")
            f.write("max-players=20\n")

        port = simplified_sync_service.get_properties_file_port(properties_path)
        assert port is None

    def test_port_range_validation(self, test_db, test_server):
        """Test port range validation (security fix)"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Test ports outside valid range
        invalid_ports = [80, 443, 1023, 65536, 99999]

        for invalid_port in invalid_ports:
            with open(properties_path, "w") as f:
                f.write(f"server-port={invalid_port}\n")
                f.write("max-players=20\n")

            port = simplified_sync_service.get_properties_file_port(properties_path)
            assert port is None, f"Port {invalid_port} should be invalid but was accepted"

        # Test valid port
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")

        port = simplified_sync_service.get_properties_file_port(properties_path)
        assert port == 25565

    def test_missing_properties_file(self, test_db, test_server):
        """Test handling when server.properties file doesn't exist"""
        properties_path = Path(test_server.directory_path) / "nonexistent.properties"

        should_sync, file_port, reason = simplified_sync_service.should_sync_from_file(
            test_server, properties_path
        )

        assert should_sync is False
        assert file_port is None
        assert "No port found" in reason

    def test_sync_preserves_other_properties(self, test_db, test_server):
        """Test that sync preserves other properties in the file"""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Add custom properties
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=Custom Server\n")
            f.write("difficulty=hard\n")
            f.write("spawn-protection=16\n")

        # Update database port
        test_server.port = 25610
        test_db.commit()

        # Sync from database to file
        success = simplified_sync_service.sync_port_from_database_to_file(
            test_server, properties_path
        )

        assert success is True

        # Verify custom properties are preserved
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25610" in content
            assert "motd=Custom Server" in content
            assert "difficulty=hard" in content
            assert "spawn-protection=16" in content
