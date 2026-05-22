from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.servers.application.minecraft_server import MinecraftServerManager
from app.servers.models import Server, ServerStatus, ServerType


def _make_repo_factory(conflicts):
    """Build a `server_repository_factory` whose `list_by_port` returns `conflicts`."""
    repo = Mock()
    repo.list_by_port = AsyncMock(return_value=conflicts)

    def factory(_db):
        return repo

    return factory


class TestPortValidation:
    """Test cases for `_validate_port_availability` after #228 PR 2d.

    The port-conflict lookup now goes through
    `ServerRepository.list_by_port(...)` instead of a raw
    `db_session.query(ServerModel)`. Tests inject a fake
    `server_repository_factory` on the manager to control the repository
    response.
    """

    @pytest.fixture
    def manager(self):
        return MinecraftServerManager()

    @pytest.fixture
    def mock_server(self):
        return Server(
            id=1,
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=1024,
            port=25565,
            directory_path="/test/server/path",
        )

    @pytest.fixture
    def mock_db_session(self):
        return Mock()

    @pytest.mark.asyncio
    async def test_validate_port_availability_no_conflict(
        self, manager, mock_server, mock_db_session
    ):
        """Port available when repo returns no conflicts and socket is free."""
        manager.server_repository_factory = _make_repo_factory(conflicts=[])
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 1  # port available
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, mock_db_session
            )

        assert available is True
        assert "available" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_database_conflict(
        self, manager, mock_server, mock_db_session
    ):
        """Repo returns a running server using the same port -> conflict."""
        conflicting = Mock()
        conflicting.name = "existing-server"
        conflicting.status = ServerStatus.running
        manager.server_repository_factory = _make_repo_factory(conflicts=[conflicting])

        available, message = await manager._validate_port_availability(
            mock_server, mock_db_session
        )

        assert available is False
        assert "already in use by running server 'existing-server'" in message
        assert "Stop the server to free up the port" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_system_conflict(
        self, manager, mock_server, mock_db_session
    ):
        """No DB conflict but `connect_ex == 0` -> external port-in-use."""
        manager.server_repository_factory = _make_repo_factory(conflicts=[])
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 0
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, mock_db_session
            )

        assert available is False
        assert "already in use by another process" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_no_db_session(self, manager, mock_server):
        """No db_session -> skip DB check, only socket probe runs."""
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, None
            )

        assert available is True
        assert "available" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_socket_exception(
        self, manager, mock_server, mock_db_session
    ):
        """Socket exception is caught and surfaced as a validation failure."""
        manager.server_repository_factory = _make_repo_factory(conflicts=[])
        with patch("socket.socket", side_effect=Exception("Socket error")):
            available, message = await manager._validate_port_availability(
                mock_server, mock_db_session
            )

        assert available is False
        assert "Port validation failed: Socket error" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_database_exception(
        self, manager, mock_server, mock_db_session
    ):
        """Repository exception is caught and surfaced as a validation failure."""
        repo = Mock()
        repo.list_by_port = AsyncMock(side_effect=Exception("Database error"))

        def factory(_db):
            return repo

        manager.server_repository_factory = factory

        available, message = await manager._validate_port_availability(
            mock_server, mock_db_session
        )

        assert available is False
        assert "Port validation failed: Database error" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_starting_server_conflict(
        self, manager, mock_server, mock_db_session
    ):
        """A `starting` server is reported as a conflict (status set passed in)."""
        conflicting = Mock()
        conflicting.name = "starting-server"
        conflicting.status = ServerStatus.starting
        manager.server_repository_factory = _make_repo_factory(conflicts=[conflicting])

        available, message = await manager._validate_port_availability(
            mock_server, mock_db_session
        )

        assert available is False
        assert "already in use by starting server 'starting-server'" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_self_exclusion(
        self, manager, mock_server, mock_db_session
    ):
        """`exclude_id=server.id` keeps the server from conflicting with itself."""
        # The repository contract is to honour `exclude_id`, so the
        # fake returns the empty list here — equivalent to "no other
        # server with this port".
        manager.server_repository_factory = _make_repo_factory(conflicts=[])
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 1
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, mock_db_session
            )

        assert available is True
        assert "available" in message
        # And confirm the exclude_id was actually passed through to the
        # repository call.
        factory = manager.server_repository_factory
        repo = factory(mock_db_session)
        repo.list_by_port.assert_awaited_with(
            mock_server.port,
            statuses=[ServerStatus.running, ServerStatus.starting],
            exclude_id=mock_server.id,
        )
