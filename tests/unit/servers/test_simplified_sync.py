"""Test bidirectional synchronization between database and server.properties.

After #272 the simplified-sync service no longer mutates SQLAlchemy
``Server`` rows directly: it accepts a frozen ``ServerEntity`` and a
``ServerRepository`` Port. These tests reflect that contract and use
the in-memory ``FakeServerRepository`` so they no longer require a
SQLite DB just to flush a single ``port`` column.
"""

import tempfile
from pathlib import Path

import pytest

from app.servers.application.simplified_sync import simplified_sync_service
from app.servers.models import ServerStatus, ServerType
from tests.unit.servers.fakes import FakeServerRepository, make_server_entity


@pytest.fixture
def repo():
    return FakeServerRepository()


@pytest.fixture
def temp_server_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def test_server(repo, temp_server_dir):
    """Seed an in-memory ``ServerEntity`` with a matching properties file."""
    entity = make_server_entity(
        id=1,
        owner_id=1,
        name="Test Server",
        directory_path=str(temp_server_dir),
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=25565,
        max_memory=1024,
        max_players=20,
        status=ServerStatus.stopped,
        description="Test server for bidirectional sync",
    )
    repo.seed(entity)

    properties_path = temp_server_dir / "server.properties"
    with open(properties_path, "w") as f:
        f.write("server-port=25565\n")
        f.write("max-players=20\n")
        f.write("motd=A Minecraft Server\n")

    return entity


class TestBidirectionalSync:
    """Test cases for bidirectional synchronization."""

    def test_file_port_extraction(self, test_server):
        """Test extracting port from server.properties file."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        port = simplified_sync_service.get_properties_file_port(properties_path)
        assert port == 25565

    @pytest.mark.asyncio
    async def test_simplified_logic_explanation(self, repo, test_server):
        """Manual edit detection — file differs from DB, sync file → DB."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        # Initially, DB and file should match (both 25565)
        initial_port = simplified_sync_service.get_properties_file_port(properties_path)
        assert initial_port == test_server.port == 25565

        # Simulate manual file edit (only file changes, DB unchanged)
        with open(properties_path, "w") as f:
            f.write("server-port=25599\n")
            f.write("max-players=20\n")

        (
            success,
            description,
            updated,
        ) = await simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, repo
        )

        assert success is True
        assert "manual edit detected" in description.lower()
        assert updated is not None
        assert updated.port == 25599

        # And the repo carries the new value
        refreshed = await repo.get(test_server.id)
        assert refreshed is not None
        assert refreshed.port == 25599

    @pytest.mark.asyncio
    async def test_sync_from_file_to_database_when_different(self, repo, test_server):
        """Sync from file to DB when ports differ (simplified logic)."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        with open(properties_path, "w") as f:
            f.write("server-port=25570\n")
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")

        (
            success,
            description,
            updated,
        ) = await simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, repo
        )

        assert success is True
        assert "Manual edit detected" in description
        assert "synced file to database" in description
        assert updated is not None
        assert updated.port == 25570

    @pytest.mark.asyncio
    async def test_no_sync_when_ports_match_simplified(self, repo, test_server):
        """No sync needed when ports already match (simplified logic)."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        (
            success,
            description,
            updated,
        ) = await simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, repo
        )

        assert success is True
        assert "No sync needed" in description
        assert "already in sync" in description
        assert updated is None

    @pytest.mark.asyncio
    async def test_manual_file_edit_detection(self, repo, test_server):
        """Detect manual file edits in simplified logic."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        with open(properties_path, "w") as f:
            f.write("server-port=25575\n")  # Different from DB (25565)
            f.write("max-players=20\n")
            f.write("motd=Manually Edited Server\n")

        (
            success,
            description,
            updated,
        ) = await simplified_sync_service.perform_simplified_sync(
            test_server, properties_path, repo
        )

        assert success is True
        assert "manual edit detected" in description.lower()
        assert updated is not None
        assert updated.port == 25575

    @pytest.mark.asyncio
    async def test_post_api_update_no_resync_needed(self, repo, test_server):
        """After a hypothetical API update, both ends sit in sync.

        Originally this test exercised ``server_service.update_server``
        end-to-end. After #272 the simplified-sync surface is the
        smaller of the two contracts under test here, so we keep just
        the post-condition: when DB (entity) and file agree on the new
        port, the sync method reports nothing to do.
        """
        from dataclasses import replace

        properties_path = Path(test_server.directory_path) / "server.properties"

        # Pretend an API update flipped both ends to 25590.
        with open(properties_path, "w") as f:
            f.write("server-port=25590\n")
            f.write("max-players=20\n")

        repo.seed(replace(test_server, port=25590))
        synced_entity = await repo.get(test_server.id)
        assert synced_entity is not None

        (
            success,
            description,
            updated,
        ) = await simplified_sync_service.perform_simplified_sync(
            synced_entity, properties_path, repo
        )
        assert success is True
        assert "No sync needed" in description
        assert updated is None

    def test_invalid_port_in_server_properties(self, test_server):
        """Handle invalid port in server_properties."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        with open(properties_path, "w") as f:
            f.write("server-port=invalid\n")
            f.write("max-players=20\n")

        port = simplified_sync_service.get_properties_file_port(properties_path)
        assert port is None

    def test_port_range_validation(self, test_server):
        """Test port range validation (security fix)."""
        properties_path = Path(test_server.directory_path) / "server.properties"

        invalid_ports = [80, 443, 1023, 65536, 99999]
        for invalid_port in invalid_ports:
            with open(properties_path, "w") as f:
                f.write(f"server-port={invalid_port}\n")
                f.write("max-players=20\n")

            port = simplified_sync_service.get_properties_file_port(properties_path)
            assert port is None, f"Port {invalid_port} should be invalid but was accepted"

        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")

        port = simplified_sync_service.get_properties_file_port(properties_path)
        assert port == 25565

    def test_missing_properties_file(self, test_server):
        """Handle missing server.properties file."""
        properties_path = Path(test_server.directory_path) / "nonexistent.properties"

        should_sync, file_port, reason = simplified_sync_service.should_sync_from_file(
            test_server, properties_path
        )

        assert should_sync is False
        assert file_port is None
        assert "No port found" in reason

    def test_sync_preserves_other_properties(self, test_server):
        """``sync_port_from_database_to_file`` preserves custom properties."""
        from dataclasses import replace

        properties_path = Path(test_server.directory_path) / "server.properties"

        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=Custom Server\n")
            f.write("difficulty=hard\n")
            f.write("spawn-protection=16\n")

        # New entity carries the post-update port the file should
        # mirror after a database→file sync.
        bumped = replace(test_server, port=25610)
        success = simplified_sync_service.sync_port_from_database_to_file(
            bumped, properties_path
        )

        assert success is True

        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25610" in content
            assert "motd=Custom Server" in content
            assert "difficulty=hard" in content
            assert "spawn-protection=16" in content
