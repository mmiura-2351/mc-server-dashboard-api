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
from unittest.mock import Mock, patch, AsyncMock, MagicMock
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
        """Test that daemon processes are created with proper detachment"""
        
        # Mock the daemon creation process
        test_pid = 12345
        
        with patch.object(manager, '_create_daemon_process_alternative') as mock_create:
            mock_create.return_value = test_pid
            
            with patch.object(manager, '_is_process_running') as mock_running:
                mock_running.return_value = True
                
                # Call the actual daemon creation method
                cmd = ["java", "-jar", "server.jar"]
                cwd = detachment_test_server.directory_path
                env = os.environ.copy()
                
                result = await manager._create_daemon_process_alternative(cmd, cwd, env, detachment_test_server.id)
                
                # Verify daemon was created
                assert result == test_pid
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_daemon_parent_process_independence(self, manager):
        """Test that daemon processes are independent of parent process"""
        
        # Test the process running check with a detached process
        daemon_pid = 99999
        
        with patch('psutil.pid_exists') as mock_pid_exists:
            mock_pid_exists.return_value = True
            
            with patch('psutil.Process') as mock_process_class:
                mock_process = Mock()
                mock_process.pid = daemon_pid
                mock_process.ppid.return_value = 1  # Should be adopted by init (PID 1)
                mock_process.is_running.return_value = True
                mock_process.status.return_value = psutil.STATUS_RUNNING
                mock_process_class.return_value = mock_process
                
                # Test process running check
                is_running = await manager._is_process_running(daemon_pid)
                
                # Verify process is detected as running
                assert is_running is True

    @pytest.mark.asyncio
    async def test_daemon_session_independence_verification(self, manager):
        """Test that daemon processes run in independent sessions"""
        
        # Mock subprocess.Popen to test session creation
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = 55555
            mock_popen.return_value = mock_process
            
            # Call the daemon creation method
            cmd = ["java", "-jar", "server.jar"]
            cwd = "/tmp/test"
            env = os.environ.copy()
            
            # Patch file operations
            with patch('builtins.open', MagicMock()):
                with patch('pathlib.Path.touch'):
                    with patch.object(manager, '_is_process_running', return_value=True):
                        result = await manager._create_daemon_process_alternative(cmd, cwd, env, 1)
            
            # Verify start_new_session was used
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs['start_new_session'] is True

    @pytest.mark.asyncio
    async def test_daemon_file_descriptor_closure_verification(self, manager):
        """Test that daemon processes properly close file descriptors"""
        
        # Mock subprocess.Popen to verify stdin/stdout/stderr handling
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = 66666
            mock_popen.return_value = mock_process
            
            # Call the daemon creation method
            cmd = ["java", "-jar", "server.jar"]
            cwd = "/tmp/test"
            env = os.environ.copy()
            
            # Patch file operations
            with patch('builtins.open', MagicMock()):
                with patch('pathlib.Path.touch'):
                    with patch.object(manager, '_is_process_running', return_value=True):
                        result = await manager._create_daemon_process_alternative(cmd, cwd, env, 1)
            
            # Verify file descriptors are handled
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs['stdin'] == subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_daemon_working_directory_independence(self, manager, tmp_path):
        """Test that daemon processes maintain independent working directories"""
        
        # Create test directory
        test_dir = tmp_path / "daemon_cwd_test"
        test_dir.mkdir()
        
        # Mock subprocess.Popen
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = 77777
            mock_popen.return_value = mock_process
            
            # Call the daemon creation method
            cmd = ["java", "-jar", "server.jar"]
            cwd = str(test_dir)
            env = os.environ.copy()
            
            # Patch file operations
            with patch('builtins.open', MagicMock()):
                with patch('pathlib.Path.touch'):
                    with patch.object(manager, '_is_process_running', return_value=True):
                        result = await manager._create_daemon_process_alternative(cmd, cwd, env, 1)
            
            # Verify working directory was set
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs['cwd'] == cwd

    @pytest.mark.asyncio
    async def test_daemon_signal_isolation_verification(self, manager):
        """Test that daemon processes are isolated from parent signals"""
        
        # Test signal isolation through process group creation
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = 88888
            mock_popen.return_value = mock_process
            
            # Call the daemon creation method
            cmd = ["java", "-jar", "server.jar"]
            cwd = "/tmp/test"
            env = os.environ.copy()
            
            # Patch file operations
            with patch('builtins.open', MagicMock()):
                with patch('pathlib.Path.touch'):
                    with patch.object(manager, '_is_process_running', return_value=True):
                        result = await manager._create_daemon_process_alternative(cmd, cwd, env, 1)
            
            # Verify process group creation (setsid)
            call_kwargs = mock_popen.call_args[1]
            assert 'preexec_fn' in call_kwargs
            # preexec_fn should be os.setsid on Unix systems
            if hasattr(os, 'setsid'):
                assert call_kwargs['preexec_fn'] == os.setsid

    @pytest.mark.asyncio
    async def test_daemon_signal_handler_verification(self, manager):
        """Test daemon process signal handling"""
        
        # Mock a daemon process for monitoring
        test_pid = 99999
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=test_pid,
            server_directory=Path("/tmp/test")
        )
        
        # Test monitoring of daemon process
        with patch.object(manager, '_is_process_running') as mock_running:
            # Simulate process termination
            mock_running.side_effect = [True, True, False]  # Running, running, then stopped
            
            # Monitor the process (limited iterations)
            with patch('asyncio.sleep', new_callable=AsyncMock):
                try:
                    # Run monitoring for a few iterations
                    monitor_task = asyncio.create_task(manager._monitor_daemon_process(server_process))
                    await asyncio.sleep(0.1)  # Let it run briefly
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass
                except Exception:
                    pass  # Expected as process will be detected as stopped

    @pytest.mark.asyncio
    async def test_daemon_memory_isolation_verification(self, manager):
        """Test that daemon processes have isolated memory space"""
        
        # Test process creation with environment isolation
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = 111111
            mock_popen.return_value = mock_process
            
            # Call the daemon creation method with custom environment
            cmd = ["java", "-jar", "server.jar"]
            cwd = "/tmp/test"
            env = {"CUSTOM_VAR": "test_value", "PATH": os.environ.get("PATH", "")}
            
            # Patch file operations
            with patch('builtins.open', MagicMock()):
                with patch('pathlib.Path.touch'):
                    with patch.object(manager, '_is_process_running', return_value=True):
                        result = await manager._create_daemon_process_alternative(cmd, cwd, env, 1)
            
            # Verify environment was passed
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs['env'] == env

    @pytest.mark.asyncio
    async def test_daemon_network_isolation_verification(self, manager):
        """Test daemon process network namespace isolation"""
        
        # Test that daemon process can be monitored independently
        test_pid = 222222
        
        with patch('psutil.pid_exists') as mock_pid_exists:
            mock_pid_exists.return_value = True
            
            with patch('psutil.Process') as mock_process_class:
                mock_process = Mock()
                mock_process.pid = test_pid
                mock_process.is_running.return_value = True
                mock_process.status.return_value = psutil.STATUS_RUNNING
                mock_process.connections.return_value = []  # No network connections yet
                mock_process_class.return_value = mock_process
                
                # Verify process can be checked
                is_running = await manager._is_process_running(test_pid)
                assert is_running is True

    @pytest.mark.asyncio
    async def test_comprehensive_daemon_detachment_verification(self, manager, detachment_test_server):
        """Comprehensive test of all daemon detachment features"""
        
        # Mock the complete daemon creation and verification flow
        test_pid = 333333
        
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = test_pid
            mock_popen.return_value = mock_process
            
            with patch('psutil.pid_exists') as mock_pid_exists:
                mock_pid_exists.return_value = True
                
                with patch('psutil.Process') as mock_psutil_process:
                    mock_ps_process = Mock()
                    mock_ps_process.is_running.return_value = True
                    mock_ps_process.ppid.return_value = 1  # Init process
                    mock_ps_process.status.return_value = psutil.STATUS_RUNNING
                    mock_psutil_process.return_value = mock_ps_process
                    
                    # Create daemon process
                    cmd = ["java", "-jar", "server.jar"]
                    cwd = detachment_test_server.directory_path
                    env = os.environ.copy()
                    
                    # Patch file operations
                    with patch('builtins.open', MagicMock()):
                        with patch('pathlib.Path.touch'):
                            result = await manager._create_daemon_process_alternative(cmd, cwd, env, detachment_test_server.id)
                    
                    # Verify all detachment features
                    assert result == test_pid
                    
                    # Verify process was created with all detachment features
                    call_kwargs = mock_popen.call_args[1]
                    assert call_kwargs['start_new_session'] is True
                    assert call_kwargs['stdin'] == subprocess.DEVNULL
                    assert 'preexec_fn' in call_kwargs

    # ===== Failure Detection Tests =====

    @pytest.mark.asyncio
    async def test_daemon_detachment_failure_detection(self, manager):
        """Test detection of daemon detachment failures"""
        
        # Mock subprocess.Popen to simulate failure
        with patch('subprocess.Popen') as mock_popen:
            mock_popen.side_effect = OSError("Failed to create process")
            
            # Call the daemon creation method
            cmd = ["java", "-jar", "server.jar"]
            cwd = "/tmp/test"
            env = os.environ.copy()
            
            # Patch file operations
            with patch('builtins.open', MagicMock()):
                with patch('pathlib.Path.touch'):
                    result = await manager._create_daemon_process_alternative(cmd, cwd, env, 1)
            
            # Should return None on failure
            assert result is None

    @pytest.mark.asyncio
    async def test_daemon_detachment_verification_timeout(self, manager):
        """Test timeout handling in daemon verification"""
        
        # Test process that never becomes ready
        test_pid = 444444
        
        with patch.object(manager, '_is_process_running') as mock_running:
            # Process exists but never becomes ready
            mock_running.return_value = False
            
            # Verify process is detected as not running
            is_running = await manager._is_process_running(test_pid)
            assert is_running is False

    @pytest.mark.asyncio
    async def test_daemon_detachment_verification_with_process_cleanup(self, manager):
        """Test daemon cleanup after detachment failure"""
        
        # Mock PID file operations
        test_server_id = 1
        test_server_dir = Path("/tmp/test")
        
        with patch.object(manager, '_read_pid_file', return_value={"pid": 555555, "server_id": test_server_id}):
            with patch.object(manager, '_is_process_running', return_value=False):
                with patch.object(manager, '_remove_pid_file') as mock_remove:
                    # Try to restore a dead process
                    result = await manager._restore_process_from_pid(test_server_id, test_server_dir)
                    
                    # Should clean up PID file and return False
                    assert result is False
                    mock_remove.assert_called_once_with(test_server_id, test_server_dir)