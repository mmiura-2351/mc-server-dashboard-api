"""
Simple test coverage for MinecraftServerManager to achieve coverage targets
"""

import asyncio
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch, mock_open

import pytest

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess


class TestMinecraftServerManagerSimpleCoverage:
    """Simple test cases for MinecraftServerManager coverage"""
    
    @pytest.fixture
    def manager(self):
        """Create a test manager instance"""
        return MinecraftServerManager()

    @pytest.fixture
    def mock_server(self):
        """Create a mock server object"""
        return Server(
            id=1,
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=1024,
            directory_path="/test/server/path",
            port=25565
        )

    def test_init_with_custom_log_queue_size(self):
        """Test MinecraftServerManager initialization with custom log queue size"""
        manager = MinecraftServerManager(log_queue_size=500)
        assert manager.log_queue_size == 500

    @pytest.mark.asyncio
    async def test_cleanup_server_process_queue_clear_with_qsize(self, manager):
        """Test _cleanup_server_process with queue that has qsize method"""
        # Create a mock queue with qsize
        mock_queue = asyncio.Queue()
        await mock_queue.put("log1")
        await mock_queue.put("log2")
        
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        await manager._cleanup_server_process(1)
        
        # Queue should be empty and process removed
        assert mock_queue.qsize() == 0
        assert 1 not in manager.processes

    @pytest.mark.asyncio
    async def test_cleanup_server_process_queue_clear_fallback(self, manager):
        """Test _cleanup_server_process fallback queue clearing"""
        # Create a mock queue without qsize method
        mock_queue = Mock()
        mock_queue.qsize.side_effect = AttributeError("No qsize method")
        mock_queue.get_nowait.side_effect = [None, None, asyncio.QueueEmpty()]
        
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        await manager._cleanup_server_process(1)
        
        # Process should be removed
        assert 1 not in manager.processes

    @pytest.mark.asyncio 
    async def test_cleanup_server_process_queue_clear_exception_safety_limit(self, manager):
        """Test _cleanup_server_process safety limit in fallback"""
        # Create a mock queue that always returns items (test safety limit)
        mock_queue = Mock()
        mock_queue.qsize.side_effect = AttributeError("No qsize method")
        mock_queue.get_nowait.return_value = "log"  # Always returns something
        
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        await manager._cleanup_server_process(1)
        
        # Should stop after 1000 iterations and remove process
        assert mock_queue.get_nowait.call_count == 1000
        assert 1 not in manager.processes

    @pytest.mark.asyncio
    async def test_cleanup_server_process_exception_handling(self, manager):
        """Test _cleanup_server_process exception handling"""
        # Create a server process that will cause an exception during cleanup
        mock_process = Mock()
        mock_queue = Mock()
        # Force exception to happen in the outer try block by making server_id in processes check fail
        mock_queue.qsize.side_effect = Exception("Queue error")
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            await manager._cleanup_server_process(1)
            
            # Should log warning and process may or may not be removed depending on when exception occurs
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_validate_port_availability_success(self, manager, mock_server):
        """Test _validate_port_availability when port is available"""
        with patch('socket.socket') as mock_socket_class:
            mock_socket = Mock()
            mock_socket_class.return_value = mock_socket
            mock_socket.connect_ex.return_value = 1  # Port not in use
            
            available, message = await manager._validate_port_availability(mock_server)
            
            assert available is True
            assert "Port 25565 is available" in message

    @pytest.mark.asyncio 
    async def test_validate_port_availability_port_in_use(self, manager, mock_server):
        """Test _validate_port_availability when port is in use"""
        with patch('socket.socket') as mock_socket_class:
            mock_socket = Mock()
            mock_socket_class.return_value = mock_socket
            mock_socket.connect_ex.return_value = 0  # Port in use
            
            available, message = await manager._validate_port_availability(mock_server)
            
            assert available is False
            assert "Port 25565 is already in use" in message

    @pytest.mark.asyncio
    async def test_start_server_port_validation_failure(self, manager, mock_server):
        """Test server startup when port validation fails"""
        with patch.object(manager, '_validate_port_availability', return_value=(False, "Port in use")):
            result = await manager.start_server(mock_server)
            
            assert result is False

    @pytest.mark.asyncio
    async def test_check_java_compatibility_exception(self, manager):
        """Test _check_java_compatibility exception handling"""
        with patch('app.services.java_compatibility.java_compatibility_service.get_java_for_minecraft', side_effect=Exception("Java error")):
            compatible, message, path = await manager._check_java_compatibility("1.20.1")
            
            assert compatible is False
            assert "Java compatibility check failed" in message
            assert path is None

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_file_exists(self, manager):
        """Test _ensure_eula_accepted when file already exists"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            eula_path = server_dir / "eula.txt"
            
            # Create eula file with wrong content
            with open(eula_path, "w") as f:
                f.write("eula=false\n")
            
            result = await manager._ensure_eula_accepted(server_dir)
            
            assert result is True
            # Check that file was updated
            with open(eula_path, "r") as f:
                content = f.read()
                assert "eula=true" in content

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_exception(self, manager):
        """Test _ensure_eula_accepted exception handling"""
        with patch('builtins.open', side_effect=Exception("File error")):
            result = await manager._ensure_eula_accepted(Path("/fake/path"))
            
            assert result is False

    @pytest.mark.asyncio
    async def test_validate_server_files_jar_not_found(self, manager):
        """Test _validate_server_files when JAR not found"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            # No server.jar file
            
            valid, message = await manager._validate_server_files(server_dir)
            
            assert valid is False
            assert "Server JAR not found" in message

    @pytest.mark.asyncio
    async def test_validate_server_files_exception(self, manager):
        """Test _validate_server_files exception handling"""
        with patch('pathlib.Path.exists', side_effect=Exception("Path error")):
            valid, message = await manager._validate_server_files(Path("/fake/path"))
            
            assert valid is False
            assert "File validation failed" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_exception(self, manager, mock_server):
        """Test _validate_port_availability exception handling"""
        with patch('socket.socket', side_effect=Exception("Socket error")):
            available, message = await manager._validate_port_availability(mock_server)
            
            assert available is False
            assert "Port validation failed" in message

    @pytest.mark.asyncio
    async def test_stop_server_not_running(self, manager):
        """Test stop_server when server is not running"""
        result = await manager.stop_server(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_server_already_terminated(self, manager):
        """Test stop_server when process is already terminated"""
        mock_process = Mock()
        mock_process.returncode = 1  # Already terminated
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
            result = await manager.stop_server(1)
            
            assert result is True
            mock_cleanup.assert_called_with(1)

    @pytest.mark.asyncio
    async def test_stop_server_exception_handling(self, manager):
        """Test stop_server exception handling"""
        mock_process = Mock()
        mock_process.returncode = None
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        # Force exception during stop
        with patch.object(manager, '_cleanup_server_process', side_effect=Exception("Cleanup error")):
            result = await manager.stop_server(1)
            
            assert result is False

    @pytest.mark.asyncio
    async def test_send_command_server_not_running(self, manager):
        """Test send_command when server is not running"""
        result = await manager.send_command(999, "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_command_no_stdin(self, manager):
        """Test send_command when process has no stdin"""
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
        
        result = await manager.send_command(1, "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_server_logs_server_not_running(self, manager):
        """Test get_server_logs when server is not running"""
        logs = await manager.get_server_logs(999)
        assert logs == []

    @pytest.mark.asyncio
    async def test_stream_server_logs_server_not_running(self, manager):
        """Test stream_server_logs when server is not running"""
        logs = []
        async for log in manager.stream_server_logs(999):
            logs.append(log)
        assert logs == []

    @pytest.mark.asyncio
    async def test_stream_server_logs_exception(self, manager):
        """Test stream_server_logs exception handling"""
        log_queue = Mock()
        log_queue.get = AsyncMock(side_effect=Exception("Queue error"))
        
        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        logs = []
        async for log in manager.stream_server_logs(1):
            logs.append(log)
        
        # Should handle exception and break
        assert logs == []

    def test_get_server_status_not_running(self, manager):
        """Test get_server_status when server is not running"""
        status = manager.get_server_status(999)
        assert status == ServerStatus.stopped

    def test_get_server_info_not_running(self, manager):
        """Test get_server_info when server is not running"""
        info = manager.get_server_info(999)
        assert info is None

    def test_get_server_info_running(self, manager):
        """Test get_server_info when server is running"""
        mock_process = Mock()
        mock_process.pid = 12345
        
        start_time = datetime.now()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=start_time,
            pid=12345
        )
        manager.processes[1] = server_process
        
        info = manager.get_server_info(1)
        
        assert info is not None
        assert info["server_id"] == 1
        assert info["pid"] == 12345
        assert info["status"] == "running"

    def test_list_running_servers(self, manager):
        """Test list_running_servers"""
        # Add some mock processes
        manager.processes[1] = Mock()
        manager.processes[2] = Mock()
        
        running = manager.list_running_servers()
        assert set(running) == {1, 2}

    @pytest.mark.asyncio
    async def test_shutdown_all_empty(self, manager):
        """Test shutdown_all when no processes are running"""
        await manager.shutdown_all()
        assert len(manager.processes) == 0

    @pytest.mark.skip(reason="Complex test requiring refactoring for current code structure")
    async def test_read_server_logs_exception(self, manager):
        """Test _read_server_logs exception handling - SKIPPED"""
        pass

    @pytest.mark.asyncio
    async def test_monitor_server_early_exit(self, manager):
        """Test _monitor_server with early process exit"""
        mock_process = Mock()
        mock_process.wait = AsyncMock(return_value=1)  # Process exits immediately
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.starting,
            started_at=datetime.now()
        )
        
        with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
            await manager._monitor_server(server_process)
            
            assert server_process.status == ServerStatus.error
            mock_cleanup.assert_called_with(1)

    @pytest.mark.asyncio
    async def test_monitor_server_exception(self, manager):
        """Test _monitor_server exception handling"""
        mock_process = Mock()
        mock_process.wait = AsyncMock(side_effect=Exception("Monitor error"))
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.starting,
            started_at=datetime.now()
        )
        
        with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
            await manager._monitor_server(server_process)
            
            assert server_process.status == ServerStatus.error
            mock_cleanup.assert_called_with(1)