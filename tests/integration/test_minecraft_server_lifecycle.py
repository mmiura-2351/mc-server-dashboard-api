"""
Integration tests for complete MinecraftServerManager lifecycle
Tests server startup, shutdown, monitoring, and process management workflows
"""

import asyncio
import os
import signal
import socket
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.orm import Session

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess
from app.services.java_compatibility import JavaVersionInfo


class MockJavaCompatibilityServiceFullWorkflow:
    """Full workflow Java compatibility service for lifecycle testing"""
    
    def __init__(self):
        self.java_version = JavaVersionInfo(17, 0, 1, "OpenJDK", "17.0.1+12", "/usr/bin/java")
    
    async def get_java_for_minecraft(self, minecraft_version: str):
        return self.java_version
    
    def validate_java_compatibility(self, minecraft_version: str, java_version: JavaVersionInfo):
        return True, f"Java {java_version.major_version} is compatible with Minecraft {minecraft_version}"


class TestMinecraftServerLifecycleIntegration:
    """Integration tests for complete server lifecycle workflows"""
    
    @pytest.fixture
    def manager(self):
        """Create manager with realistic configuration"""
        return MinecraftServerManager(log_queue_size=100)
    
    @pytest.fixture
    def mock_java_service(self):
        """Java service that always returns compatible Java"""
        return MockJavaCompatibilityServiceFullWorkflow()
    
    @pytest.fixture
    def lifecycle_server(self, tmp_path):
        """Server with complete file system setup for lifecycle testing"""
        server_dir = tmp_path / "lifecycle-server"
        server_dir.mkdir()
        
        # Create complete server structure
        jar_path = server_dir / "server.jar"
        jar_path.write_text("# Mock Minecraft Server JAR Content")
        
        # Create server.properties
        properties_path = server_dir / "server.properties"
        properties_path.write_text("""
server-port=25565
max-players=20
online-mode=true
""")
        
        # Find available port
        sock = socket.socket()
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        
        return Server(
            id=1,
            name="lifecycle-test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=1024,
            directory_path=str(server_dir),
            port=port
        )
    
    @pytest.fixture
    def mock_db_session(self):
        """Database session for port validation"""
        session = Mock(spec=Session)
        session.query.return_value.filter.return_value.first.return_value = None
        return session
    
    @pytest_asyncio.fixture
    async def long_running_process_command(self, tmp_path):
        """Create a long-running process that simulates server behavior"""
        mock_server_script = tmp_path / "long_running_server.py"
        mock_server_script.write_text("""
import sys
import time
import signal
import threading

running = True
start_time = time.time()
MAX_RUNTIME = 10  # Maximum runtime in seconds

def signal_handler(signum, frame):
    global running
    print("[SERVER] Received signal, shutting down...", flush=True)
    running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Simulate server startup sequence
print("[12:34:56] [Server thread/INFO]: Starting minecraft server version 1.20.1", flush=True)
time.sleep(0.05)
print("[12:34:56] [Server thread/INFO]: Loading properties", flush=True)
time.sleep(0.05)
print("[12:34:57] [Server thread/INFO]: Preparing level \\"world\\"", flush=True)
time.sleep(0.1)
print("[12:34:58] [Server thread/INFO]: Done (1.234s)! For help, type \\"help\\"", flush=True)

# Handle stdin commands in separate thread
def handle_commands():
    global running
    try:
        while running:
            try:
                line = input()
                if line.strip() == "stop":
                    print("[12:35:00] [Server thread/INFO]: Stopping server", flush=True)
                    running = False
                    break
                else:
                    print(f"[12:35:01] [Server thread/INFO]: Unknown command: {line}", flush=True)
            except EOFError:
                running = False
                break
    except:
        running = False

command_thread = threading.Thread(target=handle_commands)
command_thread.daemon = True
command_thread.start()

# Keep server running with timeout
while running and (time.time() - start_time) < MAX_RUNTIME:
    time.sleep(0.1)

print("[12:35:02] [Server thread/INFO]: Server stopped", flush=True)
sys.exit(0)
""")
        
        return ["python", str(mock_server_script)]

    # ===== Complete Server Startup Workflow Integration Tests =====

    @pytest.mark.asyncio
    async def test_server_startup_complete_workflow_success(self, manager, lifecycle_server, mock_db_session, mock_java_service, long_running_process_command):
        """Test lines 263-412: Complete successful server startup workflow"""
        
        # Mock the process creation to use our controlled process
        original_create_subprocess = asyncio.create_subprocess_exec
        
        async def mock_create_subprocess(*args, **kwargs):
            # Replace the java command with our mock server command
            if args and "java" in str(args[0]):
                return await original_create_subprocess(*long_running_process_command, **kwargs)
            return await original_create_subprocess(*args, **kwargs)
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch('asyncio.create_subprocess_exec', side_effect=mock_create_subprocess):
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    # Record status changes
                    status_changes = []
                    def record_status_change(server_id, status):
                        status_changes.append((server_id, status))
                    
                    manager.set_status_update_callback(record_status_change)
                    
                    # Mock daemon process creation to avoid real process in test environment  
                    with patch.object(manager, '_create_daemon_process') as mock_daemon:
                        mock_daemon.return_value = 12345  # Mock PID
                        
                        # Mock process running check to simulate successful startup
                        with patch.object(manager, '_is_process_running') as mock_running:
                            mock_running.return_value = True
                            
                            # Execute complete startup workflow
                            result = await manager.start_server(lifecycle_server, mock_db_session)
                            
                            # Verify successful startup
                            assert result is True
                            assert lifecycle_server.id in manager.processes
                            
                            # Wait for server to be fully started
                            await asyncio.sleep(0.5)
                            
                            server_process = manager.processes[lifecycle_server.id]
                            
                            # Verify process tracking
                            assert server_process.server_id == lifecycle_server.id
                            # For daemon processes, process is None but PID should exist
                            assert server_process.process is None  # Daemon mode
                            assert server_process.pid == 12345  # Mocked PID
                            assert server_process.status in [ServerStatus.starting, ServerStatus.running]
                    
                    # Verify status callback was called
                    assert len(status_changes) >= 1
                    assert (lifecycle_server.id, ServerStatus.starting) in status_changes
                    
                    # Verify logging occurred (startup workflow logging)
                    logger_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                    startup_logs = [log for log in logger_calls if "Starting pre-flight checks" in log or "Port validation passed" in log or "Java compatibility verified" in log]
                    assert len(startup_logs) >= 2  # At least some startup logs
                    
                    # Cleanup: Stop the server and ensure process is terminated
                    try:
                        await manager.stop_server(lifecycle_server.id, force=True)
                    except Exception:
                        pass
                    
                    # Ensure process is fully terminated
                    if lifecycle_server.id in manager.processes:
                        process = manager.processes[lifecycle_server.id].process
                        if process and process.returncode is None:
                            try:
                                process.terminate()
                                await asyncio.wait_for(process.wait(), timeout=2.0)
                            except:
                                process.kill()

    @pytest.mark.asyncio
    async def test_server_startup_port_validation_failure_workflow(self, manager, lifecycle_server, mock_db_session, mock_java_service):
        """Test server startup with port validation failure (lines 266-274)"""
        
        # Create a socket conflict
        conflict_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            conflict_socket.bind(("localhost", lifecycle_server.port))
            conflict_socket.listen(1)
            
            with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    result = await manager.start_server(lifecycle_server, mock_db_session)
                    
                    # Verify failure
                    assert result is False
                    assert lifecycle_server.id not in manager.processes
                    
                    # Verify error logging
                    mock_logger.error.assert_called()
                    error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                    port_error_logs = [log for log in error_calls if "Port validation failed" in log]
                    assert len(port_error_logs) >= 1
                    
        finally:
            conflict_socket.close()

    @pytest.mark.asyncio
    async def test_server_startup_java_compatibility_failure_workflow(self, manager, lifecycle_server, mock_db_session):
        """Test server startup with Java compatibility failure (lines 277-284)"""
        
        # Mock Java service to return incompatible Java
        mock_java_service = Mock()
        mock_java_service.get_java_for_minecraft = AsyncMock(return_value=None)
        mock_java_service.discover_java_installations = AsyncMock(return_value={})
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                
                result = await manager.start_server(lifecycle_server, mock_db_session)
                
                # Verify failure
                assert result is False
                assert lifecycle_server.id not in manager.processes
                
                # Verify error logging
                mock_logger.error.assert_called()
                error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                java_error_logs = [log for log in error_calls if "Java compatibility check failed" in log]
                assert len(java_error_logs) >= 1

    @pytest.mark.asyncio
    async def test_server_startup_file_validation_failure_workflow(self, manager, lifecycle_server, mock_db_session, mock_java_service):
        """Test server startup with file validation failure (lines 290-298)"""
        
        # Remove the server.jar file to cause validation failure
        jar_path = Path(lifecycle_server.directory_path) / "server.jar"
        jar_path.unlink()
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                
                result = await manager.start_server(lifecycle_server, mock_db_session)
                
                # Verify failure
                assert result is False
                assert lifecycle_server.id not in manager.processes
                
                # Verify error logging
                mock_logger.error.assert_called()
                error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                file_error_logs = [log for log in error_calls if "file validation failed" in log]
                assert len(file_error_logs) >= 1

    @pytest.mark.asyncio
    async def test_server_startup_process_creation_failure(self, manager, lifecycle_server, mock_db_session, mock_java_service):
        """Test server startup with process creation failure (lines 336-343)"""
        
        # Mock daemon process creation to fail with OSError
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch('os.fork', side_effect=OSError("Permission denied")):
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    result = await manager.start_server(lifecycle_server, mock_db_session)
                    
                    # Verify failure
                    assert result is False
                    assert lifecycle_server.id not in manager.processes
                    
                    # Verify error logging
                    mock_logger.error.assert_called()
                    error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                    # Check for daemon creation failure messages
                    daemon_error_logs = [log for log in error_calls if "daemon creation failed" in log or "All daemon creation methods failed" in log]
                    assert len(daemon_error_logs) >= 1

    @pytest.mark.asyncio
    async def test_server_startup_process_immediate_exit(self, manager, lifecycle_server, mock_db_session, mock_java_service):
        """Test server startup with process immediate exit (lines 351-376)"""
        
        # Mock daemon process creation to return a PID but process dies after initial verification
        mock_pid = 99999
        check_count = 0
        
        async def mock_is_process_running(pid):
            nonlocal check_count
            check_count += 1
            # Allow initial verification checks to pass (first 3-4 calls)
            # Then return False to simulate process death during monitoring
            if check_count <= 4:
                return True  # Pass initial verification
            else:
                return False  # Process dies during monitoring
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                mock_daemon.return_value = mock_pid  # Return mock PID
                
                with patch.object(manager, '_is_process_running', side_effect=mock_is_process_running):
                    with patch("app.services.minecraft_server.logger") as mock_logger:
                        
                        result = await manager.start_server(lifecycle_server, mock_db_session)
                        
                        # Should initially succeed (daemon creation succeeded)
                        assert result is True
                        assert lifecycle_server.id in manager.processes
                        
                        # Give time for monitor to detect the death and clean up
                        await asyncio.sleep(1.0)
                        
                        # After monitoring detects death, process should be cleaned up
                        assert lifecycle_server.id not in manager.processes
                        
                        # Verify daemon death detection logging
                        mock_logger.error.assert_called()
                        error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                        # Look for various possible error messages related to process death
                        daemon_death_logs = [log for log in error_calls if ("died" in log or "not running" in log or "ended" in log)]
                        assert len(daemon_death_logs) >= 1

    # ===== Complete Server Shutdown Workflow Integration Tests =====

    @pytest.mark.asyncio
    async def test_server_shutdown_graceful_success_workflow(self, manager, long_running_process_command):
        """Test lines 435-449: Graceful server shutdown success workflow"""
        
        # Start a real process for testing shutdown
        process = await asyncio.create_subprocess_exec(
            *long_running_process_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # Wait for server to be ready
        await asyncio.sleep(0.3)
        
        # Create server process tracking
        log_queue = asyncio.Queue()
        server_process = ServerProcess(
            server_id=1,
            process=process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=process.pid
        )
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            # Execute graceful shutdown
            result = await manager.stop_server(1, force=False)
            
            # Verify successful shutdown
            assert result is True
            assert 1 not in manager.processes
            
            # Verify status changes
            assert (1, ServerStatus.stopping) in status_changes
            assert (1, ServerStatus.stopped) in status_changes
            
            # Verify logging
            info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
            shutdown_logs = [log for log in info_calls if "Successfully stopped server" in log]
            assert len(shutdown_logs) >= 1
            
            # Ensure process is terminated
            if process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except:
                    process.kill()

    @pytest.mark.asyncio
    async def test_server_shutdown_already_terminated_workflow(self, manager):
        """Test lines 428-433: Shutdown workflow when process already terminated"""
        
        # Create a mock process that's already terminated
        mock_process = Mock()
        mock_process.returncode = 0  # Already terminated
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
            with patch("app.services.minecraft_server.logger") as mock_logger:
                
                result = await manager.stop_server(1)
                
                # Verify successful handling
                assert result is True
                
                # Verify cleanup was called
                mock_cleanup.assert_called_with(1)
                
                # Verify status change to stopped
                assert (1, ServerStatus.stopped) in status_changes
                
                # Verify logging
                info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                terminated_logs = [log for log in info_calls if "process already terminated" in log]
                assert len(terminated_logs) >= 1

    @pytest.mark.asyncio
    async def test_server_shutdown_graceful_timeout_then_force(self, manager):
        """Test lines 455-459, 462-477: Graceful timeout then force termination"""
        
        # Create a mock process that will timeout on graceful stop
        mock_process = Mock()
        mock_process.returncode = None
        mock_process.pid = 12345
        
        # Mock stdin to be available
        mock_stdin = Mock()
        mock_stdin.write = Mock()
        mock_stdin.drain = AsyncMock()
        mock_stdin.is_closing = Mock(return_value=False)
        mock_process.stdin = mock_stdin
        
        # Mock process.wait() to timeout first, then return normally
        async def mock_wait_with_timeout():
            # This simulates a timeout during graceful stop
            raise asyncio.TimeoutError("Graceful stop timed out")
        
        mock_process.wait = mock_wait_with_timeout
        mock_process.terminate = Mock()
        
        # Mock the second wait call for force termination
        async def mock_wait_after_terminate():
            return 0  # Process terminated successfully
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            # After timeout, we need to mock the second wait call for termination
            def side_effect_wait(*args, **kwargs):
                # First call times out, subsequent calls succeed
                mock_process.wait = mock_wait_after_terminate
                raise asyncio.TimeoutError("Graceful stop timed out")
            
            mock_process.wait = Mock(side_effect=side_effect_wait)
            
            # Execute shutdown that will require force termination
            result = await manager.stop_server(1, force=False)
            
            # Verify successful shutdown via force
            assert result is True
            assert 1 not in manager.processes
            
            # Verify escalation happened
            assert (1, ServerStatus.stopping) in status_changes
            assert (1, ServerStatus.stopped) in status_changes
            
            # Verify warning about graceful stop failure
            warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
            timeout_warnings = [log for log in warning_calls if "graceful stop failed" in log and "forcing termination" in log]
            assert len(timeout_warnings) >= 1
            
            # Verify terminate was called
            mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_shutdown_force_immediate(self, manager, long_running_process_command):
        """Test immediate force termination when force=True"""
        
        process = await asyncio.create_subprocess_exec(
            *long_running_process_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        await asyncio.sleep(0.2)
        
        server_process = ServerProcess(
            server_id=1,
            process=process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=process.pid
        )
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        # Execute immediate force termination
        result = await manager.stop_server(1, force=True)
        
        # Verify successful force termination
        assert result is True
        assert 1 not in manager.processes
        
        # Verify status changes
        assert (1, ServerStatus.stopping) in status_changes
        assert (1, ServerStatus.stopped) in status_changes
        
        # Ensure process is terminated
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except:
                process.kill()

    @pytest.mark.asyncio
    async def test_server_shutdown_exception_handling_workflow(self, manager):
        """Test lines 490-498: Shutdown exception handling and cleanup"""
        
        # Create a mock process that will cause exceptions
        mock_process = Mock()
        mock_process.returncode = None
        mock_process.stdin = Mock()
        mock_process.stdin.write = Mock(side_effect=Exception("Write failed"))
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
            with patch("app.services.minecraft_server.logger") as mock_logger:
                
                result = await manager.stop_server(1)
                
                # Should still complete cleanup even with exceptions
                assert result is False  # Due to exception
                
                # Verify cleanup was called
                mock_cleanup.assert_called_with(1)
                
                # Verify error logging
                mock_logger.error.assert_called()
                error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                stop_error_logs = [log for log in error_calls if "Failed to stop server" in log]
                assert len(stop_error_logs) >= 1
                
                # Verify status change to stopped (in cleanup)
                assert (1, ServerStatus.stopped) in status_changes


class TestMinecraftServerCommandAndLoggingIntegration:
    """Integration tests for command sending and logging workflows"""
    
    @pytest.fixture
    def manager(self):
        return MinecraftServerManager(log_queue_size=50)
    
    @pytest.mark.asyncio
    async def test_send_command_success_workflow(self, manager, tmp_path):
        """Test lines 508-511: Successful command sending workflow"""
        
        # Create an interactive server script
        interactive_script = tmp_path / "interactive_server.py"
        interactive_script.write_text("""
import sys
import threading
import time

start_time = time.time()
MAX_RUNTIME = 10  # Maximum runtime

def read_commands():
    try:
        while (time.time() - start_time) < MAX_RUNTIME:
            line = input()
            print(f"[SERVER] Received command: {line}", flush=True)
            if line.strip() == "stop":
                break
    except EOFError:
        pass

# Start command reading thread
command_thread = threading.Thread(target=read_commands)
command_thread.daemon = True
command_thread.start()

print("[SERVER] Ready for commands", flush=True)

# Keep running with timeout
while (time.time() - start_time) < MAX_RUNTIME:
    time.sleep(0.1)

sys.exit(0)
""")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(interactive_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        server_process = ServerProcess(
            server_id=1,
            process=process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=process.pid
        )
        manager.processes[1] = server_process
        
        # Wait for server to be ready
        await asyncio.sleep(0.2)
        
        try:
            # Test successful command sending
            result = await manager.send_command(1, "say Hello World")
            assert result is True
            
            # Test stop command
            result = await manager.send_command(1, "stop")
            assert result is True
            
        finally:
            # Cleanup
            if 1 in manager.processes:
                await manager.stop_server(1, force=True)
            
            # Ensure process is terminated
            if process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except:
                    process.kill()

    @pytest.mark.asyncio
    async def test_send_command_server_not_running_workflow(self, manager):
        """Test lines 503-504: Command sending when server not running"""
        
        result = await manager.send_command(999, "test command")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_command_no_stdin_workflow(self, manager):
        """Test lines 507, 512: Command sending when stdin not available"""
        
        mock_process = Mock()
        mock_process.stdin = None
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        result = await manager.send_command(1, "test command")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_command_exception_workflow(self, manager):
        """Test lines 514-516: Command sending exception handling"""
        
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdin.write = Mock(side_effect=Exception("Stdin write failed"))
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            result = await manager.send_command(1, "test command")
            
            assert result is False
            mock_logger.error.assert_called()
            error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
            command_error_logs = [log for log in error_calls if "Failed to send command" in log]
            assert len(command_error_logs) >= 1