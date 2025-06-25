from unittest.mock import Mock, patch

import pytest

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager


class TestPortValidation:
    """Test cases for _validate_port_availability method"""

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
        """Test port validation when no conflicts exist"""
        # Mock database query to return no conflicting servers
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        # Mock socket to return connection failed (port available)
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = (
                1  # Connection failed = port available
            )
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
        """Test port validation when database shows conflicting server"""
        # Create a mock conflicting server
        conflicting_server = Mock()
        conflicting_server.name = "existing-server"
        conflicting_server.status = ServerStatus.running

        # Mock database query to return conflicting server
        mock_db_session.query.return_value.filter.return_value.first.return_value = (
            conflicting_server
        )

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
        """Test port validation when system-level conflict exists"""
        # Mock database query to return no conflicting servers
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        # Mock socket to return connection success (port in use)
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = (
                0  # Connection success = port in use
            )
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, mock_db_session
            )

            assert available is False
            assert "already in use by another process" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_no_db_session(self, manager, mock_server):
        """Test port validation when no database session provided"""
        # Mock socket to return connection failed (port available)
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = (
                1  # Connection failed = port available
            )
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
        """Test port validation when socket operation fails"""
        # Mock database query to return no conflicting servers
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        # Mock socket to raise exception
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
        """Test port validation when database query fails"""
        # Mock database query to raise exception
        mock_db_session.query.side_effect = Exception("Database error")

        available, message = await manager._validate_port_availability(
            mock_server, mock_db_session
        )

        assert available is False
        assert "Port validation failed: Database error" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_starting_server_conflict(
        self, manager, mock_server, mock_db_session
    ):
        """Test port validation with starting server conflict"""
        # Create a mock conflicting server that is starting
        conflicting_server = Mock()
        conflicting_server.name = "starting-server"
        conflicting_server.status = ServerStatus.starting

        # Mock database query to return conflicting starting server
        mock_db_session.query.return_value.filter.return_value.first.return_value = (
            conflicting_server
        )

        available, message = await manager._validate_port_availability(
            mock_server, mock_db_session
        )

        assert available is False
        assert "already in use by starting server 'starting-server'" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_self_exclusion(
        self, manager, mock_server, mock_db_session
    ):
        """Test that server doesn't conflict with itself"""
        # Create a mock server with same ID (should be excluded)
        same_server = Mock()
        same_server.id = mock_server.id  # Same ID as the server being validated
        same_server.name = "same-server"
        same_server.status = ServerStatus.running

        # The database filter should exclude servers with the same ID
        # We'll mock this by returning None (no conflicts found)
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        # Mock socket to return connection failed (port available)
        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = (
                1  # Connection failed = port available
            )
            mock_socket.return_value = mock_sock_instance

            available, message = await manager._validate_port_availability(
                mock_server, mock_db_session
            )

            assert available is True
            assert "available" in message
