import pytest
import asyncio
import subprocess
from unittest.mock import Mock, patch, AsyncMock, call
from pathlib import Path
from datetime import datetime

from app.services.minecraft_server import MinecraftServerManager, ServerProcess
from app.servers.models import Server, ServerStatus, ServerType


class TestMinecraftServerManagerKeyMethods:
    """Focused tests for key MinecraftServerManager methods to improve coverage"""

    @pytest.fixture
    def manager(self):
        """Create a fresh MinecraftServerManager instance"""
        return MinecraftServerManager()

    @pytest.fixture
    def mock_server(self):
        """Create a mock Server object"""
        server = Mock(spec=Server)
        server.id = 1
        server.name = "test_server"
        server.directory_path = "servers/test_server"
        server.port = 25565
        server.max_memory = 1024
        server.max_players = 20
        server.server_type = ServerType.vanilla
        server.minecraft_version = "1.20.1"
        return server

    # ==========================================
    # Java Availability Tests (High Coverage Impact)
    # ==========================================

    @pytest.mark.asyncio
    async def test_check_java_availability_success(self, manager):
        """Test successful Java availability check"""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"", b"openjdk version 17.0.1")
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            result = await manager._check_java_availability()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_java_availability_not_found(self, manager):
        """Test Java not found"""
        with patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError()):
            result = await manager._check_java_availability()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_java_availability_timeout(self, manager):
        """Test Java check timeout"""
        mock_process = AsyncMock()
        mock_process.communicate.side_effect = asyncio.TimeoutError()
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError()):
                result = await manager._check_java_availability()
                assert result is False

    @pytest.mark.asyncio
    async def test_check_java_availability_error_code(self, manager):
        """Test Java returns error code"""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b"", b"")
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            result = await manager._check_java_availability()
            assert result is False

    # ==========================================
    # EULA Tests (High Coverage Impact)
    # ==========================================

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_new_file(self, manager):
        """Test creating new EULA file"""
        mock_path = Path("test_server")
        
        with patch('pathlib.Path.exists', return_value=False), \
             patch('builtins.open', mock_open_func()) as mock_file:
            
            result = await manager._ensure_eula_accepted(mock_path)
            assert result is True
            mock_file.assert_called()

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_file_error(self, manager):
        """Test EULA file operation error"""
        mock_path = Path("test_server")
        
        with patch('pathlib.Path.exists', side_effect=PermissionError("Access denied")):
            result = await manager._ensure_eula_accepted(mock_path)
            assert result is False

    # ==========================================
    # Server File Validation Tests
    # ==========================================

    @pytest.mark.asyncio
    async def test_validate_server_files_success(self, manager):
        """Test successful server file validation"""
        mock_path = Path("test_server")
        
        with patch('pathlib.Path.exists', return_value=True), \
             patch('os.access', return_value=True):
            
            result = await manager._validate_server_files(mock_path)
            assert result[0] is True
            assert "successfully" in result[1]

    @pytest.mark.asyncio
    async def test_validate_server_files_jar_missing(self, manager):
        """Test validation with missing server.jar"""
        mock_path = Path("test_server")
        
        with patch('pathlib.Path.exists', return_value=False):
            result = await manager._validate_server_files(mock_path)
            assert result[0] is False
            assert "Server JAR not found" in result[1]

    @pytest.mark.asyncio
    async def test_validate_server_files_not_readable(self, manager):
        """Test validation with unreadable server.jar"""
        mock_path = Path("test_server")
        
        with patch('pathlib.Path.exists', return_value=True), \
             patch('os.access', side_effect=lambda path, mode: mode != os.R_OK):
            
            result = await manager._validate_server_files(mock_path)
            assert result[0] is False
            assert "not readable" in result[1]

    # ==========================================
    # Start Server Tests (Critical for Coverage)
    # ==========================================

    @pytest.mark.asyncio
    async def test_start_server_already_running(self, manager, mock_server):
        """Test starting server that's already running"""
        # Add server to processes dict
        manager.processes[mock_server.id] = Mock()
        
        result = await manager.start_server(mock_server)
        assert result is False

    @pytest.mark.asyncio
    async def test_start_server_directory_not_found(self, manager, mock_server):
        """Test starting server with non-existent directory"""
        with patch('pathlib.Path.exists', return_value=False):
            result = await manager.start_server(mock_server)
            assert result is False

    @pytest.mark.asyncio
    async def test_start_server_java_not_available(self, manager, mock_server):
        """Test starting server when Java is not available"""
        with patch('pathlib.Path.exists', return_value=True), \
             patch.object(manager, '_check_java_availability', return_value=False):
            
            result = await manager.start_server(mock_server)
            assert result is False

    @pytest.mark.asyncio
    async def test_start_server_invalid_files(self, manager, mock_server):
        """Test starting server with invalid files"""
        with patch('pathlib.Path.exists', return_value=True), \
             patch.object(manager, '_check_java_availability', return_value=True), \
             patch.object(manager, '_validate_server_files', return_value=(False, "Invalid files")):
            
            result = await manager.start_server(mock_server)
            assert result is False

    @pytest.mark.asyncio
    async def test_start_server_eula_failure(self, manager, mock_server):
        """Test starting server when EULA acceptance fails"""
        with patch('pathlib.Path.exists', return_value=True), \
             patch.object(manager, '_check_java_availability', return_value=True), \
             patch.object(manager, '_validate_server_files', return_value=(True, "")), \
             patch.object(manager, '_ensure_eula_accepted', return_value=False):
            
            result = await manager.start_server(mock_server)
            assert result is False

    # ==========================================
    # Stop Server Tests (Critical for Coverage)
    # ==========================================

    @pytest.mark.asyncio
    async def test_stop_server_not_running(self, manager):
        """Test stopping server that's not running"""
        result = await manager.stop_server(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_server_graceful_success(self, manager):
        """Test successful graceful server stop"""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdin.write = Mock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdin.is_closing.return_value = False
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch('asyncio.wait_for', return_value=None):
            result = await manager.stop_server(1)
            assert result is True
            assert 1 not in manager.processes

    @pytest.mark.asyncio
    async def test_stop_server_no_stdin(self, manager):
        """Test stopping server when stdin is not available"""
        mock_process = Mock()
        mock_process.stdin = None
        mock_process.terminate = Mock()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        result = await manager.stop_server(1)
        assert result is True
        assert 1 not in manager.processes

    # ==========================================
    # Send Command Tests (Important for Coverage)
    # ==========================================

    @pytest.mark.asyncio
    async def test_send_command_success(self, manager):
        """Test successful command sending"""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdin.write = Mock()
        mock_process.stdin.drain = AsyncMock()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        result = await manager.send_command(1, "say Hello")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_command_no_stdin(self, manager):
        """Test sending command when stdin is not available"""
        mock_process = Mock()
        mock_process.stdin = None
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        result = await manager.send_command(1, "say Hello")
        assert result is False

    # ==========================================
    # Shutdown All Tests
    # ==========================================

    @pytest.mark.asyncio
    async def test_shutdown_all_no_servers(self, manager):
        """Test shutdown_all with no running servers"""
        await manager.shutdown_all()
        assert len(manager.processes) == 0

    @pytest.mark.asyncio
    async def test_shutdown_all_with_servers(self, manager):
        """Test shutdown_all with running servers"""
        # Add mock servers
        manager.processes[1] = Mock()
        manager.processes[2] = Mock()
        
        with patch.object(manager, 'stop_server', return_value=True) as mock_stop:
            await manager.shutdown_all()
            # shutdown_all creates stop tasks but doesn't clear processes dict directly
            # The actual clearing happens in stop_server method
            assert mock_stop.call_count == 2

    # ==========================================
    # Stream Logs Tests
    # ==========================================

    @pytest.mark.asyncio
    async def test_stream_server_logs_no_process(self, manager):
        """Test streaming logs when server is not running"""
        log_generator = manager.stream_server_logs(999)
        
        # Test that generator doesn't yield anything for non-existent server
        logs = []
        count = 0
        async for log in log_generator:
            logs.append(log)
            count += 1
            if count > 5:  # Prevent infinite loop
                break
        
        assert len(logs) == 0

    # ==========================================
    # Additional Core Method Tests
    # ==========================================

    def test_get_server_info_with_process(self, manager):
        """Test get_server_info with running process"""
        mock_process = Mock()
        mock_process.pid = 12345
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        info = manager.get_server_info(1)
        assert info is not None
        assert info["status"] == "running"  # get_server_info returns status.value (string)
        assert info["pid"] == 12345

    def test_list_running_servers_with_multiple(self, manager):
        """Test listing multiple running servers"""
        # Add multiple mock servers
        for i in range(3):
            manager.processes[i] = Mock()
        
        running_servers = manager.list_running_servers()
        assert len(running_servers) == 3
        assert sorted(running_servers) == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_get_server_logs_with_process(self, manager):
        """Test getting server logs with running process"""
        mock_queue = Mock()  # Use regular Mock, not AsyncMock for queue
        # Mock queue that returns some logs then is empty
        mock_queue.qsize.return_value = 2
        mock_queue.get_nowait.side_effect = ["Log line 1", "Log line 2"]
        
        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        logs = await manager.get_server_logs(1, lines=10)
        assert len(logs) == 2
        assert logs[0] == "Log line 1"
        assert logs[1] == "Log line 2"


def mock_open_func():
    """Helper function to create a proper mock_open that works with our tests"""
    from unittest.mock import mock_open
    return mock_open()


# Import os for file access tests
import os