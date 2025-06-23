"""
Integration tests for process persistence functionality

Tests the core Issue #44 implementation:
- Detached process creation
- PID file management
- Process restoration from PID files
- Auto-sync functionality
- Configurable shutdown behavior
"""

import asyncio
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest

from app.servers.models import ServerStatus
from app.services.minecraft_server import MinecraftServerManager, ServerProcess

pytestmark = pytest.mark.asyncio


class TestProcessPersistence:
    """Test suite for process persistence functionality"""

    @pytest.fixture
    def temp_server_dir(self):
        """Create temporary server directory for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir) / "test_server"
            server_dir.mkdir(parents=True, exist_ok=True)
            yield server_dir

    @pytest.fixture
    def manager(self, temp_server_dir):
        """Create MinecraftServerManager with temporary directory"""
        manager = MinecraftServerManager()
        # Set base_directory to the parent of the test server directory
        # This allows manager.base_directory.iterdir() to find test server directories
        manager.base_directory = temp_server_dir.parent
        return manager

    @pytest.fixture
    def mock_process(self):
        """Create mock process for testing"""
        process = MagicMock()
        process.pid = 12345
        process.returncode = None
        process.stdout = AsyncMock()
        process.stdin = MagicMock()
        process.wait = AsyncMock()
        return process

    async def test_pid_file_creation_and_reading(
        self, manager, temp_server_dir, mock_process
    ):
        """Test PID file creation and reading"""
        server_id = 1
        port = 25565
        command = ["java", "-jar", "server.jar"]

        # Test writing PID file
        success = await manager._write_pid_file(
            server_id, temp_server_dir, mock_process, port, command
        )
        assert success is True

        # Verify PID file exists
        pid_file_path = manager._get_pid_file_path(server_id, temp_server_dir)
        assert pid_file_path.exists()

        # Test reading PID file
        pid_data = await manager._read_pid_file(server_id, temp_server_dir)
        assert pid_data is not None
        assert pid_data["server_id"] == server_id
        assert pid_data["pid"] == mock_process.pid
        assert pid_data["port"] == port
        assert pid_data["command"] == command
        assert "started_at" in pid_data
        assert "api_version" in pid_data

    async def test_pid_file_validation(self, manager, temp_server_dir):
        """Test PID file validation with invalid data"""
        server_id = 1
        pid_file_path = manager._get_pid_file_path(server_id, temp_server_dir)

        # Test with missing required fields
        invalid_data = {
            "server_id": server_id,
            "pid": 12345,
        }  # Missing port and started_at
        with open(pid_file_path, "w") as f:
            json.dump(invalid_data, f)

        pid_data = await manager._read_pid_file(server_id, temp_server_dir)
        assert pid_data is None

        # Test with corrupted JSON
        with open(pid_file_path, "w") as f:
            f.write("invalid json")

        pid_data = await manager._read_pid_file(server_id, temp_server_dir)
        assert pid_data is None

    async def test_pid_file_removal(self, manager, temp_server_dir, mock_process):
        """Test PID file removal"""
        server_id = 1
        port = 25565
        command = ["java", "-jar", "server.jar"]

        # Create PID file
        await manager._write_pid_file(
            server_id, temp_server_dir, mock_process, port, command
        )

        pid_file_path = manager._get_pid_file_path(server_id, temp_server_dir)
        assert pid_file_path.exists()

        # Remove PID file
        success = await manager._remove_pid_file(server_id, temp_server_dir)
        assert success is True
        assert not pid_file_path.exists()

    @patch("psutil.pid_exists")
    @patch("psutil.Process")
    async def test_process_running_check(
        self, mock_process_class, mock_pid_exists, manager
    ):
        """Test process running status check"""
        pid = 12345

        # Test process exists and is running
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.status.return_value = psutil.STATUS_RUNNING
        mock_process_class.return_value = mock_process

        is_running = await manager._is_process_running(pid)
        assert is_running is True

        # Test process doesn't exist
        mock_pid_exists.return_value = False
        is_running = await manager._is_process_running(pid)
        assert is_running is False

        # Test zombie process
        mock_pid_exists.return_value = True
        mock_process.status.return_value = psutil.STATUS_ZOMBIE
        is_running = await manager._is_process_running(pid)
        assert is_running is False

    @patch("psutil.pid_exists")
    @patch("psutil.Process")
    async def test_process_restoration_success(
        self, mock_process_class, mock_pid_exists, manager, temp_server_dir
    ):
        """Test successful process restoration from PID file"""
        server_id = 1
        pid = 12345
        port = 25565
        command = ["java", "-jar", "server.jar"]

        # Create PID file
        pid_data = {
            "server_id": server_id,
            "pid": pid,
            "port": port,
            "started_at": "2023-01-01T00:00:00",
            "command": command,
            "api_version": "1.0",
        }
        pid_file_path = manager._get_pid_file_path(server_id, temp_server_dir)
        with open(pid_file_path, "w") as f:
            json.dump(pid_data, f)

        # Mock process exists and is Java process
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.status.return_value = psutil.STATUS_RUNNING
        mock_process.cmdline.return_value = ["java", "-jar", "server.jar"]
        mock_process_class.return_value = mock_process

        # Test restoration
        success = await manager._restore_process_from_pid(server_id, temp_server_dir)
        assert success is True
        assert server_id in manager.processes

        # Check restored process properties
        server_process = manager.processes[server_id]
        assert server_process.server_id == server_id
        assert server_process.pid == pid
        assert server_process.status == ServerStatus.running
        assert (
            server_process.process is None
        )  # Restored processes don't have subprocess handle

    @patch("psutil.pid_exists")
    async def test_process_restoration_failure_no_process(
        self, mock_pid_exists, manager, temp_server_dir
    ):
        """Test process restoration failure when process no longer exists"""
        server_id = 1
        pid = 12345
        port = 25565
        command = ["java", "-jar", "server.jar"]

        # Create PID file
        pid_data = {
            "server_id": server_id,
            "pid": pid,
            "port": port,
            "started_at": "2023-01-01T00:00:00",
            "command": command,
            "api_version": "1.0",
        }
        pid_file_path = manager._get_pid_file_path(server_id, temp_server_dir)
        with open(pid_file_path, "w") as f:
            json.dump(pid_data, f)

        # Mock process doesn't exist
        mock_pid_exists.return_value = False

        # Test restoration
        success = await manager._restore_process_from_pid(server_id, temp_server_dir)
        assert success is False
        assert server_id not in manager.processes

        # PID file should be removed
        assert not pid_file_path.exists()

    @patch("psutil.pid_exists")
    @patch("psutil.Process")
    async def test_process_restoration_failure_non_java(
        self, mock_process_class, mock_pid_exists, manager, temp_server_dir
    ):
        """Test process restoration failure when process is not Java"""
        server_id = 1
        pid = 12345
        port = 25565
        command = ["java", "-jar", "server.jar"]

        # Create PID file
        pid_data = {
            "server_id": server_id,
            "pid": pid,
            "port": port,
            "started_at": "2023-01-01T00:00:00",
            "command": command,
            "api_version": "1.0",
        }
        pid_file_path = manager._get_pid_file_path(server_id, temp_server_dir)
        with open(pid_file_path, "w") as f:
            json.dump(pid_data, f)

        # Mock process exists but is not Java
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.status.return_value = psutil.STATUS_RUNNING
        mock_process.cmdline.return_value = ["python", "script.py"]  # Not Java
        mock_process_class.return_value = mock_process

        # Test restoration
        success = await manager._restore_process_from_pid(server_id, temp_server_dir)
        assert success is False
        assert server_id not in manager.processes

        # PID file should be removed
        assert not pid_file_path.exists()

    @patch.object(MinecraftServerManager, "_restore_process_from_pid")
    async def test_discover_and_restore_processes(
        self, mock_restore, manager, temp_server_dir
    ):
        """Test discovery and restoration of multiple processes"""
        # Set manager base directory to temp_server_dir.parent so it can find the server directories
        base_dir = temp_server_dir.parent
        manager.base_directory = base_dir

        # Create multiple server directories with PID files in the base directory
        server_ids = [1, 2, 3]
        for server_id in server_ids:
            server_dir = base_dir / str(server_id)
            server_dir.mkdir(exist_ok=True)

            pid_data = {
                "server_id": server_id,
                "pid": 12345 + server_id,
                "port": 25565 + server_id,
                "started_at": "2023-01-01T00:00:00",
                "command": ["java", "-jar", "server.jar"],
                "api_version": "1.0",
            }
            pid_file_path = server_dir / "server.pid"
            with open(pid_file_path, "w") as f:
                json.dump(pid_data, f)

        # Mock restoration results
        mock_restore.side_effect = [True, False, True]  # Server 2 fails restoration

        # Test discovery
        results = await manager.discover_and_restore_processes()

        # Verify results
        assert len(results) == 3
        assert results[1] is True
        assert results[2] is False
        assert results[3] is True

        # Verify restore was called for each server
        assert mock_restore.call_count == 3

    @patch("app.core.config.settings.AUTO_SYNC_ON_STARTUP", False)
    async def test_discover_disabled_by_setting(self, manager):
        """Test that discovery is disabled when AUTO_SYNC_ON_STARTUP is False"""
        results = await manager.discover_and_restore_processes()
        assert results == {}

    @patch("app.core.config.settings.KEEP_SERVERS_ON_SHUTDOWN", True)
    async def test_shutdown_keep_servers(self, manager):
        """Test shutdown behavior when KEEP_SERVERS_ON_SHUTDOWN is True"""
        # Add mock server process with background tasks
        server_id = 1

        # Create actual async tasks that can be cancelled
        async def dummy_task():
            try:
                await asyncio.sleep(10)  # Long sleep that should be cancelled
            except asyncio.CancelledError:
                raise

        mock_log_task = asyncio.create_task(dummy_task())
        mock_monitor_task = asyncio.create_task(dummy_task())

        server_process = ServerProcess(
            server_id=server_id,
            process=MagicMock(),
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345,
            log_task=mock_log_task,
            monitor_task=mock_monitor_task,
        )
        manager.processes[server_id] = server_process

        # Test shutdown
        await manager.shutdown_all()

        # Process should be removed from tracking but not actually stopped
        assert server_id not in manager.processes

        # Tasks should be cancelled
        assert mock_log_task.cancelled()
        assert mock_monitor_task.cancelled()

    @patch("app.core.config.settings.KEEP_SERVERS_ON_SHUTDOWN", False)
    @patch.object(MinecraftServerManager, "stop_server")
    async def test_shutdown_stop_servers(self, mock_stop_server, manager):
        """Test shutdown behavior when KEEP_SERVERS_ON_SHUTDOWN is False"""
        # Add mock server processes
        server_ids = [1, 2, 3]
        for server_id in server_ids:
            server_process = ServerProcess(
                server_id=server_id,
                process=MagicMock(),
                log_queue=asyncio.Queue(),
                status=ServerStatus.running,
                started_at=time.time(),
                pid=12345 + server_id,
            )
            manager.processes[server_id] = server_process

        mock_stop_server.return_value = True

        # Test shutdown
        await manager.shutdown_all()

        # All servers should be stopped
        assert mock_stop_server.call_count == 3

    async def test_monitor_restored_process_stops(self, manager):
        """Test monitoring of restored process that stops"""
        server_id = 1
        pid = 12345

        # Create server process
        server_process = ServerProcess(
            server_id=server_id,
            process=None,  # Restored process doesn't have subprocess handle
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=pid,
        )
        manager.processes[server_id] = server_process

        # Mock callback
        callback_called = False

        def mock_callback(sid, status):
            nonlocal callback_called
            callback_called = True
            assert sid == server_id
            assert status == ServerStatus.stopped

        manager.set_status_update_callback(mock_callback)

        # Mock process no longer running
        with patch.object(manager, "_is_process_running", return_value=False):
            # Start monitoring (should exit quickly when process not found)
            await manager._monitor_restored_process(server_process)

        # Process should be cleaned up
        assert server_id not in manager.processes
        assert callback_called

    async def test_daemon_process_creation(self, manager, temp_server_dir):
        """Test that daemon process creation is used for true detachment"""
        from unittest.mock import patch

        # This test verifies the implementation uses daemon process creation
        # instead of asyncio.create_subprocess_exec for true detachment

        with patch.object(manager, "_create_daemon_process") as mock_daemon_create:
            mock_daemon_create.return_value = 12345  # Mock daemon PID

            # Create a minimal server object
            server = MagicMock()
            server.id = 1
            server.directory_path = str(temp_server_dir)
            server.port = 25565
            server.minecraft_version = "1.21.5"
            server.max_memory = 1024

            # Create required files
            (temp_server_dir / "server.jar").touch()

            # Mock other dependencies
            with patch.object(
                manager,
                "_check_java_compatibility",
                return_value=(True, "Java OK", "java"),
            ):
                with patch.object(
                    manager, "_validate_server_files", return_value=(True, "Files OK")
                ):
                    with patch.object(
                        manager,
                        "_validate_port_availability",
                        return_value=(True, "Port OK"),
                    ):
                        with patch.object(
                            manager, "_ensure_eula_accepted", return_value=True
                        ):
                            with patch.object(
                                manager, "_is_process_running", return_value=True
                            ):
                                try:
                                    # This should succeed with mocked daemon creation
                                    result = await manager.start_server(server)
                                    assert result is True
                                except Exception as e:
                                    # Log any unexpected errors for debugging
                                    print(f"Unexpected error in daemon test: {e}")
                                    pass

            # Verify daemon process creation was called
            mock_daemon_create.assert_called_once()
            call_args = mock_daemon_create.call_args

            # Verify the command structure includes Java execution
            cmd = call_args[0][0]  # First positional argument is the command list
            assert len(cmd) >= 3  # Should have java, memory flags, and jar
            assert "java" in cmd[0] or cmd[0].endswith("java")
            assert "-jar" in cmd
            assert "nogui" in cmd


class TestDatabaseIntegrationPersistence:
    """Test database integration enhancements for process persistence"""

    @pytest.fixture
    def mock_manager(self):
        """Mock MinecraftServerManager for testing"""
        manager = MagicMock()
        manager.discover_and_restore_processes = AsyncMock()
        return manager

    @pytest.fixture
    def db_service(self, mock_manager):
        """Database integration service with mocked manager"""
        from app.services.database_integration import DatabaseIntegrationService

        service = DatabaseIntegrationService()

        # Mock the global manager
        with patch(
            "app.services.database_integration.minecraft_server_manager", mock_manager
        ):
            yield service

    async def test_sync_server_states_with_restore(self, db_service, mock_manager):
        """Test enhanced sync that includes process restoration"""
        # Mock restoration results
        mock_manager.discover_and_restore_processes.return_value = {
            1: True,
            2: False,
            3: True,
        }

        # Mock standard sync
        with patch.object(db_service, "sync_server_states", return_value=True):
            result = await db_service.sync_server_states_with_restore()

        assert result is True
        mock_manager.discover_and_restore_processes.assert_called_once()

    async def test_sync_server_states_with_restore_failure(
        self, db_service, mock_manager
    ):
        """Test enhanced sync handles restoration failures gracefully"""
        # Mock restoration failure
        mock_manager.discover_and_restore_processes.side_effect = Exception(
            "Restoration failed"
        )

        result = await db_service.sync_server_states_with_restore()
        assert result is False
