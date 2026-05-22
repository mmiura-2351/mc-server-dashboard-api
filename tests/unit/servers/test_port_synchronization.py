"""Test port synchronization between database and server.properties.

After #272 the manager's helper methods accept the frozen
``ServerEntity`` and a ``ServerRepository`` Port instead of the
SQLAlchemy ``Server`` row + ``Session``. These tests use the in-memory
``FakeServerRepository`` to stand in for the persistence boundary.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.models import ServerStatus, ServerType
from tests.unit.servers.fakes import FakeServerRepository, make_server_entity


@pytest.fixture
def repo():
    return FakeServerRepository()


@pytest.fixture
def test_server_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def test_server(repo, test_server_dir):
    """Seed a server entity + matching server.properties for sync tests."""
    entity = make_server_entity(
        id=1,
        owner_id=1,
        name="Test Server",
        directory_path=str(test_server_dir),
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=25565,
        max_memory=1024,
        max_players=20,
        status=ServerStatus.stopped,
        description="Test server for port sync",
    )
    repo.seed(entity)

    properties_path = test_server_dir / "server.properties"
    with open(properties_path, "w") as f:
        f.write("server-port=25565\n")
        f.write("max-players=20\n")
        f.write("motd=A Minecraft Server\n")

    jar_path = test_server_dir / "server.jar"
    jar_path.touch()

    return entity


class TestPortSynchronization:
    """Test cases for port synchronization between database and server.properties."""

    @pytest.mark.asyncio
    async def test_manual_properties_edit_sync_on_startup(self, test_server):
        """``_sync_server_properties_from_database`` restores DB-tracked port."""
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25566\n")  # Changed from 25565 to 25566
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")

        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25566" in content

        result = await minecraft_server_manager._sync_server_properties_from_database(
            test_server, Path(test_server.directory_path)
        )
        assert result is True

        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25565" in content
            assert "server-port=25566" not in content

    @pytest.mark.asyncio
    async def test_properties_sync_preserves_other_settings(self, test_server):
        """Sync preserves unrelated server.properties entries."""
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=Custom MOTD\n")
            f.write("difficulty=hard\n")
            f.write("spawn-protection=16\n")

        result = await minecraft_server_manager._sync_server_properties_from_database(
            test_server, Path(test_server.directory_path)
        )
        assert result is True

        with open(properties_path, "r") as f:
            content = f.read()
            assert "motd=Custom MOTD" in content
            assert "difficulty=hard" in content
            assert "spawn-protection=16" in content
            assert "server-port=25565" in content
            assert "max-players=20" in content

    @pytest.mark.asyncio
    async def test_port_conflict_detection_uses_database_value(self, repo, test_server):
        """``_validate_port_availability`` consults the repository for conflicts."""
        # Build a fake repo whose ``list_by_port`` reports a conflicting
        # running server when called for port 25566 (and none for 25565).
        conflicting = Mock()
        conflicting.name = "Another Server"
        conflicting.status = ServerStatus.running

        repo_for_port_25565 = Mock()
        repo_for_port_25565.list_by_port = AsyncMock(return_value=[])

        repo_for_port_25566 = Mock()
        repo_for_port_25566.list_by_port = AsyncMock(return_value=[conflicting])

        # Manually edit first server's properties to use port 25566 (the
        # file edit on its own should NOT trigger a conflict — the
        # repository compares against ``entity.port``).
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25566\n")
            f.write("max-players=20\n")

        # Entity port = 25565 → no DB conflict reported.
        (
            is_available,
            message,
        ) = await minecraft_server_manager._validate_port_availability(
            test_server, repo_for_port_25565
        )
        assert is_available is True
        assert "available" in message

        # Bump the entity port to 25566 and the repo now reports a conflict.
        from dataclasses import replace

        bumped_entity = replace(test_server, port=25566)
        (
            is_available,
            message,
        ) = await minecraft_server_manager._validate_port_availability(
            bumped_entity, repo_for_port_25566
        )
        assert is_available is False
        assert "already in use" in message
