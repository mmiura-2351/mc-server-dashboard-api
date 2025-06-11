"""
Enhanced test coverage for MinecraftServerManager
Target: Increase coverage from ~47% to 70%+
Focus: Missing lines and edge cases
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


class TestMinecraftServerManagerEnhanced:
    """Enhanced tests for missing coverage areas"""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager instance for each test"""
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
            directory_path="/test/server/path"
        )

    # Test EULA handling edge cases (lines 83-88)
    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_file_exists_needs_update(self, manager):
        """Test EULA file exists but needs to be updated"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            eula_path = server_dir / "eula.txt"
            
            # Create EULA file with wrong content
            with open(eula_path, "w") as f:
                f.write("eula=false\n")
            
            # Mock logging to verify the update message
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._ensure_eula_accepted(server_dir)
                
                assert result is True
                # Verify the log message was called
                mock_logger.info.assert_called()
                
                # Verify file was updated
                with open(eula_path, "r") as f:
                    content = f.read()
                    assert "eula=true" in content

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_file_exists_already_true(self, manager):
        """Test EULA file exists and already has eula=true"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            eula_path = server_dir / "eula.txt"
            
            # Create EULA file with correct content
            with open(eula_path, "w") as f:
                f.write("eula=true\n# Some other content\n")
            
            result = await manager._ensure_eula_accepted(server_dir)
            assert result is True
            
            # Verify content wasn't changed
            with open(eula_path, "r") as f:
                content = f.read()
                assert "# Some other content" in content

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_permission_error(self, manager):
        """Test EULA creation with permission error"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            
            # Mock open to raise PermissionError
            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                with patch('app.services.minecraft_server.logger') as mock_logger:
                    result = await manager._ensure_eula_accepted(server_dir)
                    
                    assert result is False
                    mock_logger.error.assert_called_with("Failed to ensure EULA acceptance: Permission denied")

    # Test file validation edge cases (line 107)
    @pytest.mark.asyncio
    async def test_validate_server_files_directory_not_writable(self, manager):
        """Test validation when server directory is not writable"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            jar_path = server_dir / "server.jar"
            
            # Create the jar file
            jar_path.touch()
            
            # Mock os.access to return False for write access on directory
            with patch('os.access') as mock_access:
                def access_side_effect(path, mode):
                    if mode == os.W_OK and str(path) == str(server_dir):
                        return False  # Directory not writable
                    return True  # Everything else is accessible
                
                mock_access.side_effect = access_side_effect
                
                valid, message = await manager._validate_server_files(server_dir)
                assert valid is False
                assert "Server directory is not writable" in message

    @pytest.mark.asyncio
    async def test_validate_server_files_jar_not_readable(self, manager):
        """Test validation when JAR file is not readable"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            jar_path = server_dir / "server.jar"
            
            # Create the jar file
            jar_path.touch()
            
            # Mock os.access to return False for read access on JAR file
            with patch('os.access') as mock_access:
                def access_side_effect(path, mode):
                    if mode == os.R_OK and str(path) == str(jar_path):
                        return False  # JAR not readable
                    return True  # Everything else is accessible
                
                mock_access.side_effect = access_side_effect
                
                valid, message = await manager._validate_server_files(server_dir)
                assert valid is False
                assert "Server JAR is not readable" in message

    # Test Java availability checks (lines 51-71)
    @pytest.mark.asyncio
    async def test_check_java_availability_success(self, manager):
        """Test successful Java availability check"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = "java 17.0.1 2021-10-19"
        
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._check_java_availability()
                
                assert result is True
                mock_run.assert_called_once_with(
                    ["java", "-version"], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
                mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_check_java_availability_failure(self, manager):
        """Test Java availability check failure"""
        mock_result = Mock()
        mock_result.returncode = 1
        
        with patch('subprocess.run', return_value=mock_result):
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._check_java_availability()
                
                assert result is False
                mock_logger.error.assert_called_with(
                    "Java is not available or not working properly"
                )

    @pytest.mark.asyncio
    async def test_check_java_availability_timeout(self, manager):
        """Test Java availability check timeout"""
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("java", 10)):
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._check_java_availability()
                
                assert result is False
                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_check_java_availability_file_not_found(self, manager):
        """Test Java availability check when Java not found"""
        with patch('subprocess.run', side_effect=FileNotFoundError("java command not found")):
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._check_java_availability()
                
                assert result is False
                mock_logger.error.assert_called()

    # Test server startup process edge cases (lines 151-257)
    @pytest.mark.asyncio
    async def test_start_server_java_not_available(self, manager, mock_server):
        """Test server start when Java is not available"""
        with patch.object(manager, '_check_java_availability', return_value=False):
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager.start_server(mock_server)
                
                assert result is False
                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_eula_acceptance_fails(self, manager, mock_server):
        """Test server start when EULA acceptance fails"""
        with patch.object(manager, '_check_java_availability', return_value=True):
            with patch.object(manager, '_ensure_eula_accepted', return_value=False):
                with patch('app.services.minecraft_server.logger') as mock_logger:
                    result = await manager.start_server(mock_server)
                    
                    assert result is False
                    mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_file_validation_fails(self, manager, mock_server):
        """Test server start when file validation fails"""
        with patch.object(manager, '_check_java_availability', return_value=True):
            with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                with patch.object(manager, '_validate_server_files', return_value=(False, "Files invalid")):
                    with patch('app.services.minecraft_server.logger') as mock_logger:
                        result = await manager.start_server(mock_server)
                        
                        assert result is False
                        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_subprocess_creation_oserror(self, manager, mock_server):
        """Test server start when subprocess creation raises OSError"""
        with patch.object(manager, '_check_java_availability', return_value=True):
            with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                with patch.object(manager, '_validate_server_files', return_value=(True, "Valid")):
                    with patch('asyncio.create_subprocess_exec', side_effect=OSError("Failed to create process")):
                        with patch('app.services.minecraft_server.logger') as mock_logger:
                            result = await manager.start_server(mock_server)
                            
                            assert result is False
                            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_subprocess_creation_general_error(self, manager, mock_server):
        """Test server start when subprocess creation raises general exception"""
        with patch.object(manager, '_check_java_availability', return_value=True):
            with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                with patch.object(manager, '_validate_server_files', return_value=(True, "Valid")):
                    with patch('asyncio.create_subprocess_exec', side_effect=RuntimeError("Unexpected error")):
                        with patch('app.services.minecraft_server.logger') as mock_logger:
                            result = await manager.start_server(mock_server)
                            
                            assert result is False
                            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_process_none(self, manager, mock_server):
        """Test server start when subprocess creation returns None"""
        import tempfile
        from pathlib import Path
        
        # Create a temporary directory for the server
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_server.directory_path = str(temp_path)
            
            with patch.object(manager, '_check_java_availability', return_value=True):
                with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                    with patch.object(manager, '_validate_server_files', return_value=(True, "Valid")):
                        with patch('asyncio.create_subprocess_exec', return_value=None):
                            with patch('app.services.minecraft_server.logger') as mock_logger:
                                result = await manager.start_server(mock_server)
                                
                                assert result is False
                                mock_logger.error.assert_called_with(
                                    f"Process creation returned None for server {mock_server.id}"
                                )

    @pytest.mark.asyncio
    async def test_start_server_process_exits_immediately(self, manager, mock_server):
        """Test server start when process exits immediately"""
        mock_process = Mock()
        mock_process.returncode = 1  # Process already exited
        mock_process.pid = 12345
        
        with patch.object(manager, '_check_java_availability', return_value=True):
            with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                with patch.object(manager, '_validate_server_files', return_value=(True, "Valid")):
                    with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                        with patch('app.services.minecraft_server.logger') as mock_logger:
                            result = await manager.start_server(mock_server)
                            
                            assert result is False
                            mock_logger.error.assert_called()

    # Test server stopping edge cases (lines 280-345)
    @pytest.mark.asyncio
    async def test_stop_server_not_found(self, manager):
        """Test stopping a server that doesn't exist"""
        result = await manager.stop_server(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_server_no_stdin(self, manager):
        """Test stopping a server when stdin is None"""
        mock_process = Mock()
        mock_process.stdin = None
        mock_process.returncode = None
        mock_process.terminate = AsyncMock()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            result = await manager.stop_server(1, force=False)
            
            # Should attempt graceful shutdown with terminate when no stdin
            mock_process.terminate.assert_called_once()
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_stop_server_stdin_write_error(self, manager):
        """Test stopping a server when stdin write fails"""
        mock_stdin = Mock()
        mock_stdin.write.side_effect = Exception("Broken pipe")
        mock_stdin.drain = AsyncMock()
        
        mock_process = Mock()
        mock_process.stdin = mock_stdin
        mock_process.returncode = None
        mock_process.terminate = AsyncMock()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            result = await manager.stop_server(1, force=False)
            
            # Should fall back to terminate when stdin write fails
            mock_process.terminate.assert_called_once()
            mock_logger.warning.assert_called()

    # Test command sending edge cases (lines 361-363, 400-401, 410-422)
    @pytest.mark.asyncio
    async def test_send_command_server_not_found(self, manager):
        """Test sending command to non-existent server"""
        result = await manager.send_command(999, "help")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_command_no_stdin(self, manager):
        """Test sending command when stdin is None"""
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
        
        result = await manager.send_command(1, "help")
        
        # Should return False when stdin is None, but no specific error message is logged
        assert result is False

    @pytest.mark.asyncio
    async def test_send_command_stdin_error(self, manager):
        """Test sending command when stdin operation fails"""
        mock_stdin = Mock()
        mock_stdin.write.side_effect = Exception("Broken pipe")
        
        mock_process = Mock()
        mock_process.stdin = mock_stdin
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            result = await manager.send_command(1, "help")
            
            assert result is False
            mock_logger.error.assert_called()

    # Test shutdown and cleanup (lines 426-455)
    @pytest.mark.asyncio
    async def test_shutdown_all_with_processes(self, manager):
        """Test shutting down all servers with active processes"""
        # Create mock processes
        mock_process1 = Mock()
        mock_process1.returncode = None
        mock_process1.terminate = AsyncMock()
        mock_process1.wait = AsyncMock(return_value=0)
        
        mock_process2 = Mock()
        mock_process2.returncode = None
        mock_process2.terminate = AsyncMock()
        mock_process2.wait = AsyncMock(return_value=0)
        
        server_process1 = ServerProcess(
            server_id=1,
            process=mock_process1,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        
        server_process2 = ServerProcess(
            server_id=2,
            process=mock_process2,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        
        manager.processes[1] = server_process1
        manager.processes[2] = server_process2
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            await manager.shutdown_all()
            
            # Verify all processes were terminated
            mock_process1.terminate.assert_called_once()
            mock_process2.terminate.assert_called_once()
            
            # Verify processes dict is cleared
            assert len(manager.processes) == 0
            
            mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_shutdown_all_process_wait_timeout(self, manager):
        """Test shutdown when process wait times out"""
        mock_process = Mock()
        mock_process.returncode = None
        mock_process.terminate = AsyncMock()
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_process.kill = AsyncMock()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            await manager.shutdown_all()
            
            # Should try terminate first, then kill on timeout
            mock_process.terminate.assert_called_once()
            mock_process.kill.assert_called_once()
            mock_logger.warning.assert_called()

    # Test log streaming edge cases (lines 459-516)
    @pytest.mark.asyncio
    async def test_get_server_logs_server_not_found(self, manager):
        """Test getting logs for non-existent server"""
        logs = await manager.get_server_logs(999, 10)
        assert logs == []

    @pytest.mark.asyncio
    async def test_get_server_logs_no_process(self, manager):
        """Test getting logs when server process doesn't exist"""
        logs = await manager.get_server_logs(1, 10)
        assert logs == []

    def test_get_server_info_with_process(self, manager):
        """Test getting server info when process exists"""
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
        assert info["pid"] == 12345
        assert info["status"] == "running"  # Status is returned as .value (string)

    def test_get_server_info_not_found(self, manager):
        """Test getting server info for non-existent server"""
        info = manager.get_server_info(999)
        assert info is None

    def test_list_running_servers_multiple(self, manager):
        """Test listing multiple running servers"""
        # Create multiple server processes
        for i in range(1, 4):
            mock_process = Mock()
            mock_process.pid = 1000 + i
            
            server_process = ServerProcess(
                server_id=i,
                process=mock_process,
                log_queue=Mock(),
                status=ServerStatus.running,
                started_at=datetime.now(),
                pid=1000 + i
            )
            manager.processes[i] = server_process
        
        running_servers = manager.list_running_servers()
        assert len(running_servers) == 3
        # list_running_servers returns List[int] of server IDs
        assert all(isinstance(server_id, int) for server_id in running_servers)
        assert set(running_servers) == {1, 2, 3}

    def test_list_running_servers_empty(self, manager):
        """Test listing running servers when none are running"""
        running_servers = manager.list_running_servers()
        assert running_servers == []

    # Test status update callback functionality
    def test_set_status_update_callback(self, manager):
        """Test setting status update callback"""
        callback = Mock()
        manager.set_status_update_callback(callback)
        assert manager._status_update_callback == callback

    def test_notify_status_change_with_callback(self, manager):
        """Test status change notification with callback"""
        callback = Mock()
        manager.set_status_update_callback(callback)
        
        manager._notify_status_change(1, ServerStatus.running)
        callback.assert_called_once_with(1, ServerStatus.running)

    def test_notify_status_change_callback_exception(self, manager):
        """Test status change notification when callback raises exception"""
        callback = Mock(side_effect=Exception("Database error"))
        manager.set_status_update_callback(callback)
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            manager._notify_status_change(1, ServerStatus.running)
            
            callback.assert_called_once_with(1, ServerStatus.running)
            mock_logger.error.assert_called()

    def test_notify_status_change_no_callback(self, manager):
        """Test status change notification when no callback is set"""
        # Should not raise any exception
        manager._notify_status_change(1, ServerStatus.running)

    # Additional tests to increase coverage
    @pytest.mark.asyncio
    async def test_validate_server_files_exception(self, manager):
        """Test _validate_server_files when exception occurs"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            
            # Create a server.jar file so we get past the file existence check
            jar_path = server_dir / "server.jar"
            jar_path.touch()
            
            # Mock os.access to raise an exception
            with patch('os.access', side_effect=Exception("Access check failed")):
                valid, message = await manager._validate_server_files(server_dir)
                assert valid is False
                assert "File validation failed: Access check failed" in message

    @pytest.mark.asyncio
    async def test_start_server_already_running(self, manager, mock_server):
        """Test starting a server that's already running"""
        # Add server to processes dict to simulate running state
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=mock_server.id,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[mock_server.id] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            result = await manager.start_server(mock_server)
            
            assert result is False
            mock_logger.warning.assert_called_with(f"Server {mock_server.id} is already running")

    @pytest.mark.asyncio
    async def test_read_server_logs_with_queue_full(self, manager):
        """Test _read_server_logs with queue full scenario"""
        import asyncio
        from unittest.mock import AsyncMock
        
        # Create a mock server process
        mock_process = AsyncMock()
        mock_stdout_lines = [b"Test log line 1\n", b"Test log line 2\n"]
        
        # Create async iterator for stdout
        async def async_lines():
            for line in mock_stdout_lines:
                yield line
        
        mock_process.stdout = async_lines()
        
        # Create a small queue that will fill up
        log_queue = asyncio.Queue(maxsize=1)
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        
        # Fill the queue to test the QueueFull exception handling
        await log_queue.put("Initial log entry")
        
        # This should test the queue full logic
        await manager._read_server_logs(server_process)
        
        # Verify queue has logs (original plus one new)
        assert not log_queue.empty()

    @pytest.mark.asyncio 
    async def test_read_server_logs_server_ready_detection(self, manager):
        """Test _read_server_logs detecting server ready status"""
        import asyncio
        from unittest.mock import AsyncMock
        
        # Create a mock server process
        mock_process = AsyncMock()
        
        # Server ready message
        ready_message = b"[12:34:56] [Server thread/INFO]: Done (1.234s)! For help, type \"help\"\n"
        
        # Create async iterator for stdout
        async def async_lines():
            yield ready_message
        
        mock_process.stdout = async_lines()
        
        log_queue = asyncio.Queue()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.starting,
            started_at=datetime.now()
        )
        
        # Set up manager to track status changes
        manager.processes[1] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            await manager._read_server_logs(server_process)
            
            # Verify status was updated to running
            assert server_process.status == ServerStatus.running
            mock_logger.info.assert_called_with("Server 1 is now running")

    @pytest.mark.asyncio
    async def test_read_server_logs_exception(self, manager):
        """Test _read_server_logs when exception occurs"""
        import asyncio
        from unittest.mock import AsyncMock
        
        # Create a mock server process that raises exception
        mock_process = AsyncMock()
        
        # Make stdout raise an exception
        async def async_lines():
            raise Exception("Stdout read error")
            yield b"never reached"
        
        mock_process.stdout = async_lines()
        
        log_queue = asyncio.Queue()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            await manager._read_server_logs(server_process)
            
            # Should log the error
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_stream_server_logs(self, manager):
        """Test stream_server_logs method"""
        import asyncio
        
        # Test with non-existent server
        async for log in manager.stream_server_logs(999):
            # Should not yield anything
            assert False, "Should not yield logs for non-existent server"
        
        # Test with existing server
        log_queue = asyncio.Queue()
        await log_queue.put("Test log line")
        
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        # Get one log line and break
        async for log in manager.stream_server_logs(1):
            assert log == "Test log line"
            # Remove from processes to break the loop
            del manager.processes[1]
            break

    def test_validate_server_files_success_path(self, manager):
        """Test _validate_server_files success path with real directory"""
        import tempfile
        import asyncio
        
        async def run_test():
            with tempfile.TemporaryDirectory() as temp_dir:
                server_dir = Path(temp_dir)
                
                # Create a server.jar file
                jar_path = server_dir / "server.jar"
                jar_path.touch()
                
                valid, message = await manager._validate_server_files(server_dir)
                assert valid is True
                assert "All files validated successfully" in message
        
        # Run the async test
        asyncio.run(run_test())

    # Strategic tests to reach 70% coverage - targeting specific missing lines
    
    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_file_creation(self, manager):
        """Test line 80: EULA file creation when file doesn't exist"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            eula_path = server_dir / "eula.txt"
            
            # Ensure file doesn't exist
            assert not eula_path.exists()
            
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._ensure_eula_accepted(server_dir)
                
                assert result is True
                assert eula_path.exists()
                
                # Verify the creation log message (line 78)
                mock_logger.info.assert_called_with(f"Creating EULA acceptance file: {eula_path}")
                
                # Verify file content (line 80)
                with open(eula_path, "r") as f:
                    content = f.read()
                    assert "eula=true" in content

    @pytest.mark.asyncio
    async def test_check_java_availability_debug_logging(self, manager):
        """Test lines 131-132: Java availability debug logging"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = "java 17.0.1 2021-10-19 LTS"
        
        with patch('subprocess.run', return_value=mock_result):
            with patch('app.services.minecraft_server.logger') as mock_logger:
                result = await manager._check_java_availability()
                
                assert result is True
                # Verify debug logging happens (lines 131-132 region)
                mock_logger.debug.assert_called()

    @pytest.mark.asyncio  
    async def test_stop_server_process_already_terminated(self, manager):
        """Test lines 274-278: Stop server when process already terminated"""
        mock_process = Mock()
        mock_process.returncode = 0  # Process already terminated
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            result = await manager.stop_server(1)
            
            assert result is True
            # Verify the specific log message (line 274)
            mock_logger.info.assert_called_with("Server 1 process already terminated")
            # Verify process was cleaned up (line 276)
            assert 1 not in manager.processes

    @pytest.mark.asyncio
    async def test_start_server_process_monitoring_with_error_output(self, manager, mock_server):
        """Test lines 211-220: Process starts but exits with error output"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_server.directory_path = str(temp_path)
            
            # Create a mock process that exits after a delay with error output
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_process.returncode = None  # Initially running
            
            # Mock stdout for error reading
            mock_stdout = AsyncMock()
            error_data = b"Java error: insufficient memory"
            
            async def mock_read(size):
                return error_data
            
            mock_stdout.read = mock_read
            mock_process.stdout = mock_stdout
            
            # Simulate process exiting during monitoring
            call_count = [0]
            original_returncode = mock_process.returncode
            
            def returncode_side_effect():
                call_count[0] += 1
                if call_count[0] <= 2:  # First 2 checks: still running
                    return None
                else:  # 3rd check: process exited
                    return 1
            
            type(mock_process).returncode = property(lambda self: returncode_side_effect())
            
            with patch.object(manager, '_check_java_availability', return_value=True):
                with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                    with patch.object(manager, '_validate_server_files', return_value=(True, "Valid")):
                        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                            with patch('app.services.minecraft_server.logger') as mock_logger:
                                result = await manager.start_server(mock_server)
                                
                                assert result is False
                                # Should log the error output (lines 216-218)
                                error_calls = [call for call in mock_logger.error.call_args_list 
                                             if 'immediate error' in str(call)]
                                assert len(error_calls) > 0

    @pytest.mark.asyncio
    async def test_start_server_process_verification_success(self, manager, mock_server):
        """Test lines 223-257: Successful process start and log reading setup"""
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_server.directory_path = str(temp_path)
            
            # Create a mock process that starts successfully
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_process.returncode = None  # Process running
            mock_process.stdout = AsyncMock()
            
            with patch.object(manager, '_check_java_availability', return_value=True):
                with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                    with patch.object(manager, '_validate_server_files', return_value=(True, "Valid")):
                        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                            with patch.object(manager, '_read_server_logs') as mock_read_logs:
                                with patch('app.services.minecraft_server.logger') as mock_logger:
                                    result = await manager.start_server(mock_server)
                                    
                                    assert result is True
                                    # Verify success logging (line 223-224)
                                    success_calls = [call for call in mock_logger.info.call_args_list 
                                                   if 'Process verification successful' in str(call)]
                                    assert len(success_calls) > 0
                                    
                                    # Verify process was added to processes dict
                                    assert mock_server.id in manager.processes
                                    
                                    # Verify log reading task was started
                                    mock_read_logs.assert_called()

    @pytest.mark.asyncio
    async def test_read_server_logs_queue_empty_exception(self, manager):
        """Test lines 442-443: Queue empty exception handling in log reading"""
        import asyncio
        from unittest.mock import AsyncMock
        
        # Create a mock server process
        mock_process = AsyncMock()
        
        # Create async iterator that yields one line
        async def async_lines():
            yield b"Test log line\n"
        
        mock_process.stdout = async_lines()
        
        # Create a queue that will be full
        log_queue = asyncio.Queue(maxsize=1)
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        
        # Fill the queue
        await log_queue.put("existing log")
        
        # Mock get_nowait to raise QueueEmpty after first call
        original_get_nowait = log_queue.get_nowait
        call_count = [0]
        
        def mock_get_nowait():
            call_count[0] += 1
            if call_count[0] == 1:
                return original_get_nowait()  # Return existing log
            else:
                raise asyncio.QueueEmpty()  # Second call raises exception (line 442)
        
        log_queue.get_nowait = mock_get_nowait
        
        # This should exercise the QueueEmpty exception path (lines 442-443)
        await manager._read_server_logs(server_process)
        
        # Queue should still have content
        assert not log_queue.empty()

    @pytest.mark.asyncio
    async def test_stream_server_logs_timeout_and_exception(self, manager):
        """Test lines 418-422: Stream logs timeout and exception handling"""
        import asyncio
        
        # Create a queue that will timeout
        log_queue = asyncio.Queue()
        
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        # Mock the queue.get to raise TimeoutError, then an exception
        call_count = [0]
        
        async def mock_get():
            call_count[0] += 1
            if call_count[0] == 1:
                raise asyncio.TimeoutError()  # First call times out (line 418)
            elif call_count[0] == 2:
                raise Exception("Queue error")  # Second call raises exception (line 421)
            else:
                # Stop the loop by removing server from processes
                if 1 in manager.processes:
                    del manager.processes[1]
                raise StopAsyncIteration()
        
        log_queue.get = mock_get
        
        with patch('app.services.minecraft_server.logger') as mock_logger:
            # Collect logs from the generator
            logs = []
            try:
                async for log in manager.stream_server_logs(1):
                    logs.append(log)
            except StopAsyncIteration:
                pass
            
            # Should handle both timeout and exception (lines 418-422)
            assert len(logs) == 0  # No logs yielded due to errors
            
            # Verify error was logged for the exception case
            if mock_logger.error.called:
                error_calls = [call for call in mock_logger.error.call_args_list 
                             if 'Error streaming logs' in str(call)]
                assert len(error_calls) > 0