"""
Comprehensive integration tests for daemon lifecycle management
Tests the complete lifecycle of daemon processes including creation, monitoring, restoration, and cleanup
"""

import asyncio
import os
import signal
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typing import Optional

import pytest
import pytest_asyncio
import psutil
from sqlalchemy.orm import Session

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess
from app.services.java_compatibility import JavaVersionInfo


class MockJavaCompatibilityServiceDaemon:
    """Mock Java compatibility service for daemon lifecycle testing"""
    
    def __init__(self):
        self.java_version = JavaVersionInfo(17, 0, 1, "OpenJDK", "17.0.1+12", "/usr/bin/java")
    
    async def get_java_for_minecraft(self, minecraft_version: str):
        return self.java_version
    
    def validate_java_compatibility(self, minecraft_version: str, java_version: JavaVersionInfo):
        return True, f"Java {java_version.major_version} is compatible with Minecraft {minecraft_version}"


class TestDaemonLifecycleComprehensive:
    """Comprehensive tests for daemon process lifecycle management"""
    
    @pytest.fixture
    def manager(self):
        """Create manager with daemon-specific configuration"""
        return MinecraftServerManager(log_queue_size=50)
    
    @pytest.fixture
    def mock_java_service(self):
        """Java service that always returns compatible Java"""
        return MockJavaCompatibilityServiceDaemon()
    
    @pytest.fixture
    def daemon_test_server(self, tmp_path):
        """Server configured for daemon lifecycle testing"""
        server_dir = tmp_path / "daemon-test-server"
        server_dir.mkdir()
        
        # Create complete server structure
        jar_path = server_dir / "server.jar"
        jar_path.write_text("# Mock Minecraft Server JAR for Daemon Testing")
        
        # Create server.properties
        properties_path = server_dir / "server.properties"
        properties_path.write_text("""
server-port=25565
max-players=20
online-mode=true
enable-rcon=true
rcon.port=25575
""")
        
        # Find available port
        import socket
        sock = socket.socket()
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        
        return Server(
            id=1,
            name="daemon-lifecycle-test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=1024,
            directory_path=str(server_dir),
            port=port
        )
    
    @pytest.fixture
    def mock_db_session(self):
        """Database session for daemon testing"""
        session = Mock(spec=Session)
        session.query.return_value.filter.return_value.first.return_value = None
        return session
    
    @pytest_asyncio.fixture
    async def daemon_simulator_command(self, tmp_path):
        """Create a command that simulates a long-running daemon process"""
        daemon_script = tmp_path / "daemon_simulator.py"
        daemon_script.write_text("""
import sys
import time
import signal
import os
import threading
from pathlib import Path

# Setup signal handlers
running = True
start_time = time.time()
MAX_RUNTIME = 30  # Maximum runtime in seconds

def signal_handler(signum, frame):
    global running
    print(f"[DAEMON] Received signal {signum}, shutting down...", flush=True)
    running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Write PID to file for verification
pid_file = Path("daemon_test.pid")
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))

# Simulate Minecraft server startup sequence
print("[12:34:56] [Server thread/INFO]: Starting minecraft server version 1.20.1", flush=True)
time.sleep(0.1)
print("[12:34:56] [Server thread/INFO]: Loading properties", flush=True)
time.sleep(0.1)
print("[12:34:57] [Server thread/INFO]: Preparing level \\"world\\"", flush=True)
time.sleep(0.2)
print("[12:34:58] [Server thread/INFO]: Done (1.234s)! For help, type \\"help\\"", flush=True)
print("[12:34:58] [Server thread/INFO]: Starting remote control listener", flush=True)
print("[12:34:58] [Server thread/INFO]: RCON running on 0.0.0.0:25575", flush=True)

# Handle stdin commands in separate thread
def handle_commands():
    global running
    try:
        while running and (time.time() - start_time) < MAX_RUNTIME:
            try:
                line = input()
                if line.strip() == "stop":
                    print("[12:35:00] [Server thread/INFO]: Stopping server", flush=True)
                    running = False
                    break
                else:
                    print(f"[12:35:01] [Server thread/INFO]: Command executed: {line}", flush=True)
            except EOFError:
                running = False
                break
    except:
        running = False

command_thread = threading.Thread(target=handle_commands)
command_thread.daemon = True
command_thread.start()

# Keep daemon running with timeout protection
while running and (time.time() - start_time) < MAX_RUNTIME:
    time.sleep(0.5)

print("[12:35:02] [Server thread/INFO]: Daemon stopped", flush=True)

# Cleanup PID file
try:
    pid_file.unlink()
except:
    pass

sys.exit(0)
""")
        
        return ["python", str(daemon_script)]

    # ===== Daemon Creation Lifecycle Tests =====

    @pytest.mark.asyncio
    async def test_daemon_creation_complete_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service, daemon_simulator_command):
        """Test complete daemon creation lifecycle from start to verification"""
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                # Mock successful daemon creation
                mock_daemon.return_value = 12345
                
                with patch.object(manager, '_is_process_running') as mock_running:
                    mock_running.return_value = True
                    
                    with patch("app.services.minecraft_server.logger") as mock_logger:
                        
                        # Execute daemon creation lifecycle
                        result = await manager.start_server(daemon_test_server, mock_db_session)
                        
                        # Verify daemon creation success
                        assert result is True
                        assert daemon_test_server.id in manager.processes
                        
                        server_process = manager.processes[daemon_test_server.id]
                        
                        # Verify daemon process characteristics
                        assert server_process.process is None  # Daemon has no direct process object
                        assert server_process.pid == 12345
                        assert server_process.status in [ServerStatus.starting, ServerStatus.running]
                        assert server_process.server_directory is not None
                        
                        # Verify daemon creation was called
                        mock_daemon.assert_called_once()
                        args, kwargs = mock_daemon.call_args
                        assert len(args) == 4  # cmd, cwd, env, server_id
                        assert "java" in args[0][0]
                        assert str(daemon_test_server.directory_path) == args[1]
                        
                        # Verify process verification was called
                        assert mock_running.call_count >= 1
                        
                        # Verify logging occurred
                        info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                        creation_logs = [log for log in info_calls if "Daemon process verification successful" in log]
                        assert len(creation_logs) >= 1

    @pytest.mark.asyncio
    async def test_daemon_pid_file_management_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test PID file creation and management during daemon lifecycle"""
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                mock_daemon.return_value = 98765
                
                with patch.object(manager, '_is_process_running') as mock_running:
                    mock_running.return_value = True
                    
                    # Mock PID file writing
                    with patch.object(manager, '_write_pid_file') as mock_write_pid:
                        mock_write_pid.return_value = True
                        
                        result = await manager.start_server(daemon_test_server, mock_db_session)
                        
                        assert result is True
                        
                        # Verify PID file was written
                        mock_write_pid.assert_called_once()
                        args, kwargs = mock_write_pid.call_args
                        assert args[0] == daemon_test_server.id  # server_id
                        assert args[1] == Path(daemon_test_server.directory_path)  # server_dir
                        assert args[2].pid == 98765  # mock_process with PID
                        assert args[3] == daemon_test_server.port  # port
                        assert isinstance(args[4], list)  # cmd
                        # args[5] and args[6] are rcon_port and rcon_password

    @pytest.mark.asyncio
    async def test_daemon_process_verification_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test daemon process verification during startup lifecycle"""
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                mock_daemon.return_value = 11111
                
                # Test verification sequence: pass initial checks, then fail
                verification_calls = []
                async def mock_verification(pid):
                    verification_calls.append(pid)
                    if len(verification_calls) <= 4:  # First 4 calls pass
                        return True
                    return False  # Later calls fail (process died)
                
                with patch.object(manager, '_is_process_running', side_effect=mock_verification):
                    with patch("app.services.minecraft_server.logger") as mock_logger:
                        
                        result = await manager.start_server(daemon_test_server, mock_db_session)
                        
                        # Should initially succeed but process dies during monitoring
                        assert result is True
                        
                        # Verify verification was called multiple times
                        assert len(verification_calls) >= 4
                        assert all(pid == 11111 for pid in verification_calls)

    # ===== Daemon Monitoring Lifecycle Tests =====

    @pytest.mark.asyncio
    async def test_daemon_monitoring_complete_lifecycle(self, manager):
        """Test complete daemon monitoring lifecycle including status transitions"""
        
        # Create daemon server process
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=22222,
            server_directory=Path("/tmp/test_daemon")
        )
        
        # Add to manager's processes
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        # Mock restored process monitoring
        with patch.object(manager, '_monitor_restored_process') as mock_monitor:
            async def mock_monitor_impl(process):
                # Simulate monitoring lifecycle: starting -> running -> stopped
                process.status = ServerStatus.running
                manager._notify_status_change(process.server_id, ServerStatus.running)
                await asyncio.sleep(0.1)
                process.status = ServerStatus.stopped
                manager._notify_status_change(process.server_id, ServerStatus.stopped)
            
            mock_monitor.side_effect = mock_monitor_impl
            
            with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    # Start monitoring
                    await manager._monitor_server(server_process)
                    
                    # Verify status transitions
                    assert (1, ServerStatus.running) in status_changes
                    assert (1, ServerStatus.stopped) in status_changes
                    
                    # Verify restored process monitoring was called
                    mock_monitor.assert_called_once_with(server_process)
                    
                    # Verify cleanup was called
                    mock_cleanup.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_daemon_log_monitoring_lifecycle(self, manager, tmp_path):
        """Test daemon log monitoring throughout process lifecycle"""
        
        # Create daemon server directory and log file
        server_dir = tmp_path / "daemon_logs"
        server_dir.mkdir()
        log_file = server_dir / "server.log"
        log_file.write_text("Initial daemon log content\n")
        
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=33333,
            server_directory=server_dir
        )
        
        # Add to manager for monitoring loop
        manager.processes[1] = server_process
        
        # Start log reading task
        log_task = asyncio.create_task(manager._read_server_logs(server_process))
        
        try:
            # Simulate log file growth during daemon lifecycle
            await asyncio.sleep(0.2)
            with open(log_file, 'a') as f:
                f.write("[12:34:57] [Server thread/INFO]: Daemon process running\n")
                f.write("[12:34:58] [Server thread/INFO]: RCON listener started\n")
                f.flush()
            
            # Wait for logs to be processed
            await asyncio.sleep(0.3)
            
            # Verify logs were captured
            assert server_process.log_queue.qsize() > 0
            
            # Check log content
            logs = []
            while not server_process.log_queue.empty():
                logs.append(server_process.log_queue.get_nowait())
            
            assert len(logs) > 0
            daemon_logs = [log for log in logs if "Daemon process running" in log]
            assert len(daemon_logs) >= 1
            
        finally:
            # Cleanup: Remove from processes and cancel task
            del manager.processes[1]
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

    # ===== Daemon Restoration Lifecycle Tests =====

    @pytest.mark.asyncio
    async def test_daemon_restoration_complete_lifecycle(self, manager, tmp_path):
        """Test complete daemon restoration lifecycle from PID files"""
        
        # Create test server directory with PID file
        server_dir = tmp_path / "daemon_restore"
        server_dir.mkdir()
        
        pid_file = server_dir / "minecraft_server.pid"
        pid_data = {
            "pid": 44444,
            "server_id": 1,
            "port": 25565,
            "cmd": ["java", "-jar", "server.jar"],
            "rcon_port": 25575,
            "rcon_password": "test_password",
            "created_at": datetime.now().isoformat()
        }
        
        import json
        pid_file.write_text(json.dumps(pid_data))
        
        # Mock process running check
        with patch.object(manager, '_is_process_running') as mock_running:
            mock_running.return_value = True
            
            with patch.object(manager, '_restore_process_from_pid') as mock_restore:
                mock_restore.return_value = True
                
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    # Execute restoration lifecycle
                    results = await manager._discover_and_restore_processes()
                    
                    # Verify restoration results
                    assert isinstance(results, dict)
                    assert 1 in results
                    assert results[1] is True
                    
                    # Verify restoration was attempted
                    mock_restore.assert_called_once_with(1, server_dir)
                    
                    # Verify process running check
                    mock_running.assert_called()
                    
                    # Verify logging
                    info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                    restore_logs = [log for log in info_calls if "Successfully restored server 1" in log]
                    assert len(restore_logs) >= 1

    @pytest.mark.asyncio
    async def test_daemon_cleanup_complete_lifecycle(self, manager, tmp_path):
        """Test complete daemon cleanup lifecycle including file and resource cleanup"""
        
        # Create daemon server with resources
        server_dir = tmp_path / "daemon_cleanup"
        server_dir.mkdir()
        
        # Create PID file
        pid_file = server_dir / "minecraft_server.pid"
        pid_file.write_text('{"pid": 55555, "server_id": 1}')
        
        # Create log queue with content
        log_queue = asyncio.Queue()
        await log_queue.put("Test log 1")
        await log_queue.put("Test log 2")
        
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=55555,
            server_directory=server_dir
        )
        
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            
            # Execute cleanup lifecycle
            await manager._cleanup_server_process(1)
            
            # Verify process was removed
            assert 1 not in manager.processes
            
            # Verify status change to stopped
            assert (1, ServerStatus.stopped) in status_changes
            
            # Verify log queue was emptied
            assert log_queue.qsize() == 0
            
            # Verify cleanup logging
            info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
            cleanup_logs = [log for log in info_calls if "Cleaned up server process 1" in log]
            assert len(cleanup_logs) >= 1

    # ===== Daemon Error Handling Lifecycle Tests =====

    @pytest.mark.asyncio
    async def test_daemon_creation_failure_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test daemon creation failure handling throughout lifecycle"""
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                # Mock daemon creation failure
                mock_daemon.return_value = None
                
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    result = await manager.start_server(daemon_test_server, mock_db_session)
                    
                    # Verify failure handling
                    assert result is False
                    assert daemon_test_server.id not in manager.processes
                    
                    # Verify error logging
                    error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                    failure_logs = [log for log in error_calls if "All daemon creation methods failed" in log]
                    assert len(failure_logs) >= 1

    @pytest.mark.asyncio
    async def test_daemon_verification_failure_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test daemon verification failure handling in startup lifecycle"""
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                mock_daemon.return_value = 66666
                
                with patch.object(manager, '_is_process_running') as mock_running:
                    # Process verification fails immediately
                    mock_running.return_value = False
                    
                    with patch("app.services.minecraft_server.logger") as mock_logger:
                        
                        result = await manager.start_server(daemon_test_server, mock_db_session)
                        
                        # Verify verification failure handling
                        assert result is False
                        assert daemon_test_server.id not in manager.processes
                        
                        # Verify error logging
                        error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                        verification_logs = [log for log in error_calls if "is not running" in log or "died within" in log]
                        assert len(verification_logs) >= 1

    @pytest.mark.asyncio
    async def test_daemon_exception_handling_lifecycle(self, manager):
        """Test exception handling throughout daemon lifecycle"""
        
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=77777
        )
        
        manager.processes[1] = server_process
        
        # Record status changes
        status_changes = []
        def record_status_change(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status_change)
        
        # Mock exception in monitoring
        with patch.object(manager, '_monitor_restored_process') as mock_monitor:
            mock_monitor.side_effect = Exception("Daemon monitoring failed")
            
            with patch.object(manager, '_cleanup_server_process') as mock_cleanup:
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    # Execute monitoring with exception
                    await manager._monitor_server(server_process)
                    
                    # Verify exception handling
                    assert server_process.status == ServerStatus.error
                    assert (1, ServerStatus.error) in status_changes
                    
                    # Verify cleanup was called
                    mock_cleanup.assert_called_once_with(1)
                    
                    # Verify error logging
                    error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                    exception_logs = [log for log in error_calls if "Error monitoring server 1" in log]
                    assert len(exception_logs) >= 1

    # ===== Daemon Integration Lifecycle Tests =====

    @pytest.mark.asyncio
    async def test_daemon_full_integration_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test complete daemon integration lifecycle: creation -> monitoring -> cleanup"""
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch.object(manager, '_create_daemon_process') as mock_daemon:
                mock_daemon.return_value = 88888
                
                process_checks = []
                async def mock_process_check(pid):
                    process_checks.append(len(process_checks))
                    if len(process_checks) <= 6:  # Process runs for a while
                        return True
                    return False  # Then stops
                
                with patch.object(manager, '_is_process_running', side_effect=mock_process_check):
                    with patch.object(manager, '_write_pid_file') as mock_write_pid:
                        mock_write_pid.return_value = True
                        
                        # Record all status changes
                        status_changes = []
                        def record_status_change(server_id, status):
                            status_changes.append((server_id, status))
                        
                        manager.set_status_update_callback(record_status_change)
                        
                        with patch("app.services.minecraft_server.logger") as mock_logger:
                            
                            # 1. Daemon Creation Phase
                            result = await manager.start_server(daemon_test_server, mock_db_session)
                            assert result is True
                            assert daemon_test_server.id in manager.processes
                            
                            server_process = manager.processes[daemon_test_server.id]
                            assert server_process.process is None  # Daemon characteristic
                            assert server_process.pid == 88888
                            
                            # 2. Monitoring Phase (simulated)
                            # Start monitoring task briefly
                            monitor_task = asyncio.create_task(manager._monitor_server(server_process))
                            await asyncio.sleep(0.2)  # Let monitoring run briefly
                            
                            # 3. Cleanup Phase
                            monitor_task.cancel()
                            try:
                                await monitor_task
                            except asyncio.CancelledError:
                                pass
                            
                            await manager._cleanup_server_process(daemon_test_server.id)
                            
                            # Verify complete lifecycle
                            assert daemon_test_server.id not in manager.processes
                            
                            # Verify status progression
                            assert len(status_changes) >= 1
                            assert (daemon_test_server.id, ServerStatus.starting) in status_changes or \
                                   (daemon_test_server.id, ServerStatus.running) in status_changes
                            
                            # Verify all phases were executed
                            mock_daemon.assert_called_once()
                            mock_write_pid.assert_called_once()
                            assert len(process_checks) >= 4  # Multiple verification checks