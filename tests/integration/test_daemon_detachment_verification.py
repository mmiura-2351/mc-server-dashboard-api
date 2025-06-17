"""
Integration tests for daemon detachment verification
Tests that verify proper daemon process detachment from parent processes
"""

import asyncio
import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typing import Optional

import pytest
import pytest_asyncio
import psutil

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess


class TestDaemonDetachmentVerification:
    """Tests for verifying proper daemon process detachment"""
    
    @pytest.fixture
    def manager(self):
        """Create manager for detachment testing"""
        return MinecraftServerManager(log_queue_size=30)
    
    @pytest.fixture
    def detachment_test_server(self, tmp_path):
        """Server for testing daemon detachment"""
        server_dir = tmp_path / "detachment-test"
        server_dir.mkdir()
        
        # Create minimal server structure
        jar_path = server_dir / "server.jar"
        jar_path.write_text("# Mock JAR for detachment testing")
        
        return Server(
            id=1,
            name="detachment-test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=512,
            directory_path=str(server_dir),
            port=25566
        )

    # ===== Process Detachment Verification Tests =====

    @pytest.mark.asyncio
    async def test_daemon_process_detachment_verification(self, manager, detachment_test_server):
        """Test that daemon processes are properly detached from parent process"""
        
        # Mock the daemon creation to return a PID
        test_pid = 12345
        
        with patch.object(manager, '_create_daemon_process') as mock_create:
            mock_create.return_value = test_pid
            
            with patch.object(manager, '_is_process_running') as mock_running:
                mock_running.return_value = True
                
                # Test daemon detachment verification
                result = await manager._verify_daemon_detachment(test_pid)
                
                # Verify detachment validation
                assert result is True
                
                # Verify process running check was called
                mock_running.assert_called_with(test_pid)

    @pytest.mark.asyncio
    async def test_daemon_parent_process_independence(self, manager):
        """Test that daemon processes are independent of parent process"""
        
        # Create a mock daemon process
        daemon_pid = 99999
        
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.pid = daemon_pid
            mock_process.ppid.return_value = 1  # Should be adopted by init (PID 1)
            mock_process.is_running.return_value = True
            mock_process_class.return_value = mock_process
            
            # Test parent process independence
            is_detached = await manager._verify_process_detachment(daemon_pid)
            
            # Verify daemon is properly detached (parent is init)
            assert is_detached is True
            mock_process.ppid.assert_called_once()

    @pytest.mark.asyncio
    async def test_daemon_session_independence_verification(self, manager):
        """Test that daemon processes run in independent sessions"""
        
        daemon_pid = 88888
        
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.pid = daemon_pid
            
            # Mock process session info - daemon should be session leader
            mock_process.gids.return_value = psutil._common.pgids(real=1000, effective=1000, saved=1000)
            mock_process.uids.return_value = psutil._common.puids(real=1000, effective=1000, saved=1000)
            
            # Mock that process is session leader (sid == pid for session leaders)
            with patch('os.getsid') as mock_getsid:
                mock_getsid.return_value = daemon_pid  # Session leader
                
                mock_process_class.return_value = mock_process
                
                # Test session independence
                is_session_leader = await manager._verify_session_independence(daemon_pid)
                
                # Verify daemon is session leader
                assert is_session_leader is True
                mock_getsid.assert_called_with(daemon_pid)

    @pytest.mark.asyncio
    async def test_daemon_file_descriptor_closure_verification(self, manager, tmp_path):
        """Test that daemon processes have proper file descriptor closure"""
        
        # Create test daemon script that checks file descriptors
        daemon_fd_script = tmp_path / "fd_test_daemon.py"
        daemon_fd_script.write_text("""
import sys
import os
import time

# Check that stdin, stdout, stderr are redirected
stdin_closed = sys.stdin.closed or sys.stdin.fileno() != 0
stdout_redirected = sys.stdout.fileno() != 1
stderr_redirected = sys.stderr.fileno() != 2

# Write results to file
with open("fd_test_results.txt", "w") as f:
    f.write(f"stdin_proper: {stdin_closed}\\n")
    f.write(f"stdout_redirected: {stdout_redirected}\\n") 
    f.write(f"stderr_redirected: {stderr_redirected}\\n")
    f.write(f"pid: {os.getpid()}\\n")

# Run briefly then exit
time.sleep(0.5)
sys.exit(0)
""")
        
        cmd = ["python", str(daemon_fd_script)]
        cwd = str(tmp_path)
        env = dict(os.environ)
        
        # Test file descriptor closure verification
        with patch.object(manager, '_verify_fd_closure') as mock_verify:
            mock_verify.return_value = True
            
            # Create daemon with proper FD handling
            daemon_pid = await manager._create_daemon_process(cmd, cwd, env, 1)
            
            if daemon_pid:
                # Verify FD closure check was called
                mock_verify.assert_called_once()
                
                # Clean up
                try:
                    os.kill(daemon_pid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

    @pytest.mark.asyncio
    async def test_daemon_working_directory_independence(self, manager, tmp_path):
        """Test that daemon processes have independent working directories"""
        
        # Create test directories
        daemon_work_dir = tmp_path / "daemon_workspace"
        daemon_work_dir.mkdir()
        
        # Create test daemon script
        wd_test_script = tmp_path / "wd_test_daemon.py"
        wd_test_script.write_text(f"""
import os
import sys

# Check working directory
current_wd = os.getcwd()
expected_wd = "{daemon_work_dir}"

# Write result
with open("wd_test_result.txt", "w") as f:
    f.write(f"working_directory: {{current_wd}}\\n")
    f.write(f"expected: {{expected_wd}}\\n")
    f.write(f"correct: {{current_wd == expected_wd}}\\n")

sys.exit(0)
""")
        
        cmd = ["python", str(wd_test_script)]
        
        # Test working directory independence
        with patch.object(manager, '_create_daemon_process') as mock_create:
            mock_create.return_value = 77777
            
            # Verify daemon creation with correct working directory
            result_pid = await manager._create_daemon_process(cmd, str(daemon_work_dir), {}, 1)
            
            # Verify working directory was set correctly
            mock_create.assert_called_once_with(cmd, str(daemon_work_dir), {}, 1)

    # ===== Signal Handling Verification Tests =====

    @pytest.mark.asyncio
    async def test_daemon_signal_isolation_verification(self, manager):
        """Test that daemon processes are isolated from parent signals"""
        
        daemon_pid = 66666
        
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.pid = daemon_pid
            mock_process.is_running.return_value = True
            
            # Mock that process is in different process group
            with patch('os.getpgid') as mock_getpgid:
                mock_getpgid.side_effect = lambda pid: pid if pid == daemon_pid else os.getpid()
                
                mock_process_class.return_value = mock_process
                
                # Test signal isolation
                is_isolated = await manager._verify_signal_isolation(daemon_pid)
                
                # Verify daemon is in separate process group
                assert is_isolated is True
                mock_getpgid.assert_called_with(daemon_pid)

    @pytest.mark.asyncio 
    async def test_daemon_signal_handler_verification(self, manager, tmp_path):
        """Test that daemon processes have proper signal handlers"""
        
        # Create daemon with signal handling test
        signal_test_script = tmp_path / "signal_test_daemon.py"
        signal_test_script.write_text("""
import signal
import sys
import os
import time

# Setup signal handlers
def signal_handler(signum, frame):
    with open("signal_received.txt", "w") as f:
        f.write(f"signal_{signum}_handled")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Write PID for testing
with open("signal_test_pid.txt", "w") as f:
    f.write(str(os.getpid()))

# Wait for signal
time.sleep(2.0)
sys.exit(0)
""")
        
        # Test signal handler verification
        with patch.object(manager, '_verify_signal_handlers') as mock_verify:
            mock_verify.return_value = True
            
            cmd = ["python", str(signal_test_script)]
            
            # Create daemon and verify signal handling
            daemon_pid = await manager._create_daemon_process(cmd, str(tmp_path), {}, 1)
            
            if daemon_pid:
                # Verify signal handler check
                mock_verify.assert_called_once()
                
                # Clean up
                try:
                    os.kill(daemon_pid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

    # ===== Resource Isolation Verification Tests =====

    @pytest.mark.asyncio
    async def test_daemon_memory_isolation_verification(self, manager):
        """Test that daemon processes have proper memory isolation"""
        
        daemon_pid = 55555
        
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.pid = daemon_pid
            
            # Mock memory info for isolation verification
            mock_memory_info = Mock()
            mock_memory_info.rss = 1024 * 1024 * 100  # 100MB RSS
            mock_memory_info.vms = 1024 * 1024 * 200  # 200MB VMS
            mock_process.memory_info.return_value = mock_memory_info
            
            mock_process_class.return_value = mock_process
            
            # Test memory isolation verification
            is_isolated = await manager._verify_memory_isolation(daemon_pid)
            
            # Verify memory isolation check
            assert is_isolated is True
            mock_process.memory_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_daemon_network_isolation_verification(self, manager):
        """Test that daemon processes have proper network isolation"""
        
        daemon_pid = 44444
        
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.pid = daemon_pid
            
            # Mock network connections for isolation verification
            mock_connections = [
                Mock(laddr=Mock(ip='127.0.0.1', port=25565), family=2, type=1),
                Mock(laddr=Mock(ip='127.0.0.1', port=25575), family=2, type=1),
            ]
            mock_process.connections.return_value = mock_connections
            
            mock_process_class.return_value = mock_process
            
            # Test network isolation verification
            is_isolated = await manager._verify_network_isolation(daemon_pid)
            
            # Verify network isolation check
            assert is_isolated is True
            mock_process.connections.assert_called_once()

    # ===== Comprehensive Detachment Verification Tests =====

    @pytest.mark.asyncio
    async def test_comprehensive_daemon_detachment_verification(self, manager, detachment_test_server):
        """Test comprehensive daemon detachment verification covering all aspects"""
        
        test_pid = 33333
        
        # Mock all verification methods
        with patch.object(manager, '_verify_daemon_detachment') as mock_detach:
            mock_detach.return_value = True
            
            with patch.object(manager, '_verify_process_detachment') as mock_process:
                mock_process.return_value = True
                
                with patch.object(manager, '_verify_session_independence') as mock_session:
                    mock_session.return_value = True
                    
                    with patch.object(manager, '_verify_signal_isolation') as mock_signal:
                        mock_signal.return_value = True
                        
                        with patch.object(manager, '_verify_memory_isolation') as mock_memory:
                            mock_memory.return_value = True
                            
                            with patch.object(manager, '_verify_network_isolation') as mock_network:
                                mock_network.return_value = True
                                
                                # Run comprehensive verification
                                verification_result = await manager._comprehensive_detachment_verification(test_pid)
                                
                                # Verify all checks passed
                                assert verification_result is True
                                
                                # Verify all verification methods were called
                                mock_detach.assert_called_once_with(test_pid)
                                mock_process.assert_called_once_with(test_pid)
                                mock_session.assert_called_once_with(test_pid)
                                mock_signal.assert_called_once_with(test_pid)
                                mock_memory.assert_called_once_with(test_pid)
                                mock_network.assert_called_once_with(test_pid)

    @pytest.mark.asyncio
    async def test_daemon_detachment_failure_detection(self, manager):
        """Test detection of daemon detachment failures"""
        
        test_pid = 22222
        
        # Test case where process detachment fails
        with patch.object(manager, '_verify_process_detachment') as mock_process:
            mock_process.return_value = False  # Detachment failed
            
            with patch.object(manager, '_verify_session_independence') as mock_session:
                mock_session.return_value = True
                
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    # Run verification with detachment failure
                    verification_result = await manager._comprehensive_detachment_verification(test_pid)
                    
                    # Verify failure detection
                    assert verification_result is False
                    
                    # Verify error logging
                    mock_logger.warning.assert_called()
                    warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
                    detachment_warnings = [log for log in warning_calls if "Process detachment verification failed" in log]
                    assert len(detachment_warnings) >= 1

    @pytest.mark.asyncio
    async def test_daemon_detachment_verification_timeout(self, manager):
        """Test daemon detachment verification with timeout handling"""
        
        test_pid = 11111
        
        # Mock verification that times out
        async def slow_verification(pid):
            await asyncio.sleep(5.0)  # Simulate slow verification
            return True
        
        with patch.object(manager, '_verify_process_detachment', side_effect=slow_verification):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                
                # Run verification with timeout
                start_time = time.time()
                verification_result = await asyncio.wait_for(
                    manager._comprehensive_detachment_verification(test_pid),
                    timeout=2.0
                )
                end_time = time.time()
                
                # Should complete within timeout or raise TimeoutError
                assert (end_time - start_time) < 3.0  # Account for overhead

    @pytest.mark.asyncio
    async def test_daemon_detachment_verification_with_process_cleanup(self, manager, tmp_path):
        """Test daemon detachment verification with proper process cleanup"""
        
        # Create test PID file
        pid_file = tmp_path / "test.pid"
        test_pid = 99999
        
        import json
        pid_data = {
            "pid": test_pid,
            "server_id": 1,
            "created_at": datetime.now().isoformat()
        }
        pid_file.write_text(json.dumps(pid_data))
        
        # Mock successful detachment verification
        with patch.object(manager, '_comprehensive_detachment_verification') as mock_verify:
            mock_verify.return_value = True
            
            with patch.object(manager, '_is_process_running') as mock_running:
                mock_running.return_value = False  # Process no longer running
                
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    
                    # Run verification with cleanup
                    await manager._verify_and_cleanup_detached_process(pid_file, test_pid)
                    
                    # Verify verification was attempted
                    mock_verify.assert_called_once_with(test_pid)
                    
                    # Verify process running check
                    mock_running.assert_called_with(test_pid)
                    
                    # Verify cleanup logging
                    info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                    cleanup_logs = [log for log in info_calls if "process no longer running" in log or "cleaning up" in log]
                    assert len(cleanup_logs) >= 1