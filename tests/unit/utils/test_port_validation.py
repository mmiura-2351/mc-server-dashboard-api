from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.servers.application.minecraft_server import MinecraftServerManager
from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerStatus, ServerType


def _make_repo(conflicts):
    """Build a fake `ServerRepository` whose `list_by_port` returns `conflicts`."""
    repo = Mock()
    repo.list_by_port = AsyncMock(return_value=conflicts)
    return repo


def _make_entity(*, port: int = 25565, server_id: int = 1) -> ServerEntity:
    """Build a minimal `ServerEntity` for the port-validation tests."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return ServerEntity(
        id=server_id,
        name="test-server",
        directory_path="/test/server/path",
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=port,
        max_memory=1024,
        max_players=20,
        owner_id=1,
        status=ServerStatus.stopped,
        created_at=now,
        updated_at=now,
    )


class TestPortValidation:
    """Test cases for `_validate_port_availability` after #272.

    The port-conflict lookup goes through the explicitly-injected
    ``ServerRepository.list_by_port(...)``. Tests construct a fake
    repository and pass it as the second argument.
    """

    @pytest.fixture
    def manager(self):
        return MinecraftServerManager()

    @pytest.fixture
    def mock_server(self):
        return _make_entity()

    @pytest.mark.asyncio
    async def test_validate_port_availability_no_conflict(self, manager, mock_server):
        """Port available when repo returns no conflicts and socket is free."""
        repo = _make_repo(conflicts=[])
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 1  # port available
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, repo
            )

        assert available is True
        assert "available" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_database_conflict(
        self, manager, mock_server
    ):
        """Repo returns a running server using the same port -> conflict."""
        conflicting = Mock()
        conflicting.name = "existing-server"
        conflicting.status = ServerStatus.running
        repo = _make_repo(conflicts=[conflicting])

        available, message = await manager._validate_port_availability(mock_server, repo)

        assert available is False
        assert "already in use by running server 'existing-server'" in message
        assert "Stop the server to free up the port" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_system_conflict(self, manager, mock_server):
        """No DB conflict but `connect_ex == 0` -> external port-in-use."""
        repo = _make_repo(conflicts=[])
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 0
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, repo
            )

        assert available is False
        assert "already in use by another process" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_no_repo(self, manager, mock_server):
        """No repository (test escape hatch) -> skip DB check, only socket probe runs."""
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, None, _for_test_default=True
            )

        assert available is True
        assert "available" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_missing_repo_raises(
        self, manager, mock_server
    ):
        """Production path with no repository -> fail loud (#281)."""
        with pytest.raises(RuntimeError, match="requires an explicit ServerRepository"):
            await manager._validate_port_availability(mock_server)

        with pytest.raises(RuntimeError, match="requires an explicit ServerRepository"):
            await manager._validate_port_availability(mock_server, None)

    @pytest.mark.asyncio
    async def test_validate_port_availability_socket_exception(
        self, manager, mock_server
    ):
        """Socket exception is caught and surfaced as a validation failure."""
        repo = _make_repo(conflicts=[])
        with patch("socket.socket", side_effect=Exception("Socket error")):
            available, message = await manager._validate_port_availability(
                mock_server, repo
            )

        assert available is False
        assert "Port validation failed: Socket error" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_database_exception(
        self, manager, mock_server
    ):
        """Repository exception is caught and surfaced as a validation failure."""
        repo = Mock()
        repo.list_by_port = AsyncMock(side_effect=Exception("Database error"))

        available, message = await manager._validate_port_availability(mock_server, repo)

        assert available is False
        assert "Port validation failed: Database error" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_starting_server_conflict(
        self, manager, mock_server
    ):
        """A `starting` server is reported as a conflict (status set passed in)."""
        conflicting = Mock()
        conflicting.name = "starting-server"
        conflicting.status = ServerStatus.starting
        repo = _make_repo(conflicts=[conflicting])

        available, message = await manager._validate_port_availability(mock_server, repo)

        assert available is False
        assert "already in use by starting server 'starting-server'" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_self_exclusion(self, manager, mock_server):
        """`exclude_id=server.id` keeps the server from conflicting with itself."""
        repo = _make_repo(conflicts=[])
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, repo
            )

        assert available is True
        assert "available" in message
        # Confirm the exclude_id was actually passed through to the
        # repository call.
        repo.list_by_port.assert_awaited_with(
            mock_server.port,
            statuses=[ServerStatus.running, ServerStatus.starting],
            exclude_id=mock_server.id,
        )
