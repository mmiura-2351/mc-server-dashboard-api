"""
Comprehensive test coverage for MinecraftServerManager
Consolidates all minecraft server related tests for better organization
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


class TestMinecraftServerManager:
    """Comprehensive tests for MinecraftServerManager"""

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
            directory_path="/test/server/path",
        )

    # ===== Basic Functionality Tests =====

    def test_init(self):
        """Test MinecraftServerManager initialization"""
        manager = MinecraftServerManager()
        assert manager.processes == {}
        assert isinstance(manager.base_directory, Path)
        assert manager._status_update_callback is None

    def test_singleton_instance(self):
        """Test that minecraft_server_manager is available"""
        from app.services.minecraft_server import minecraft_server_manager
        assert minecraft_server_manager is not None
        assert isinstance(minecraft_server_manager, MinecraftServerManager)

    def test_set_status_update_callback(self):
        """Test setting status update callback"""
        manager = MinecraftServerManager()
        callback = Mock()
        
        manager.set_status_update_callback(callback)
        assert manager._status_update_callback == callback

    def test_notify_status_change_no_callback(self):
        """Test _notify_status_change with no callback set"""
        manager = MinecraftServerManager()
        
        # Should not raise exception
        manager._notify_status_change(123, ServerStatus.running)

    def test_notify_status_change_with_callback(self):
        """Test _notify_status_change with callback"""
        manager = MinecraftServerManager()
        callback = Mock()
        manager.set_status_update_callback(callback)
        
        manager._notify_status_change(123, ServerStatus.running)
        callback.assert_called_once_with(123, ServerStatus.running)

    def test_notify_status_change_callback_exception(self):
        """Test _notify_status_change when callback raises exception"""
        manager = MinecraftServerManager()
        callback = Mock(side_effect=Exception("Database error"))
        manager.set_status_update_callback(callback)

        with patch("app.services.minecraft_server.logger") as mock_logger:
            manager._notify_status_change(1, ServerStatus.running)

            callback.assert_called_once_with(1, ServerStatus.running)
            mock_logger.error.assert_called()

    def test_get_server_status_not_running(self):
        """Test get_server_status when server is not running"""
        manager = MinecraftServerManager()
        
        # Server not in processes dict
        status = manager.get_server_status(999)
        assert status == ServerStatus.stopped

    def test_get_server_status_with_process(self):
        """Test get_server_status with ServerProcess object"""
        manager = MinecraftServerManager()
        
        # Create ServerProcess
        mock_process = ServerProcess(
            server_id=456,
            process=Mock(),
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[456] = mock_process
        
        status = manager.get_server_status(456)
        assert status == ServerStatus.running

    def test_get_server_info_with_process(self):
        """Test getting server info when process exists"""
        manager = MinecraftServerManager()
        mock_process = Mock()
        mock_process.pid = 12345

        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345,
        )
        manager.processes[1] = server_process

        info = manager.get_server_info(1)
        assert info is not None
        assert info["pid"] == 12345
        assert info["status"] == "running"

    def test_get_server_info_not_found(self):
        """Test getting server info for non-existent server"""
        manager = MinecraftServerManager()
        info = manager.get_server_info(999)
        assert info is None

    def test_list_running_servers_multiple(self):
        """Test listing multiple running servers"""
        manager = MinecraftServerManager()
        
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
                pid=1000 + i,
            )
            manager.processes[i] = server_process

        running_servers = manager.list_running_servers()
        assert len(running_servers) == 3
        assert all(isinstance(server_id, int) for server_id in running_servers)
        assert set(running_servers) == {1, 2, 3}

    def test_list_running_servers_empty(self):
        """Test listing running servers when none are running"""
        manager = MinecraftServerManager()
        running_servers = manager.list_running_servers()
        assert running_servers == []

    # ===== EULA Handling Tests =====

    @pytest.mark.asyncio
    async def test_ensure_eula_accepted_file_creation(self, manager):
        """Test EULA file creation when file doesn't exist"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            eula_path = server_dir / "eula.txt"

            # Ensure file doesn't exist
            assert not eula_path.exists()

            with patch("app.services.minecraft_server.logger") as mock_logger:
                result = await manager._ensure_eula_accepted(server_dir)

                assert result is True
                assert eula_path.exists()

                # Verify the creation log message
                mock_logger.info.assert_called_with(
                    f"Creating EULA acceptance file: {eula_path}"
                )

                # Verify file content
                with open(eula_path, "r") as f:
                    content = f.read()
                    assert "eula=true" in content

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
            with patch("app.services.minecraft_server.logger") as mock_logger:
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
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    result = await manager._ensure_eula_accepted(server_dir)

                    assert result is False
                    mock_logger.error.assert_called_with(
                        "Failed to ensure EULA acceptance: Permission denied"
                    )

    # ===== File Validation Tests =====

    @pytest.mark.asyncio
    async def test_validate_server_files_success_path(self, manager):
        """Test _validate_server_files success path with real directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            # Create a server.jar file
            jar_path = server_dir / "server.jar"
            jar_path.touch()

            valid, message = await manager._validate_server_files(server_dir)
            assert valid is True
            assert "All files validated successfully" in message

    @pytest.mark.asyncio
    async def test_validate_server_files_directory_not_writable(self, manager):
        """Test validation when server directory is not writable"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            jar_path = server_dir / "server.jar"

            # Create the jar file
            jar_path.touch()

            # Mock os.access to return False for write access on directory
            with patch("os.access") as mock_access:

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
            with patch("os.access") as mock_access:

                def access_side_effect(path, mode):
                    if mode == os.R_OK and str(path) == str(jar_path):
                        return False  # JAR not readable
                    return True  # Everything else is accessible

                mock_access.side_effect = access_side_effect

                valid, message = await manager._validate_server_files(server_dir)
                assert valid is False
                assert "Server JAR is not readable" in message

    @pytest.mark.asyncio
    async def test_validate_server_files_exception(self, manager):
        """Test _validate_server_files when exception occurs"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)

            # Create a server.jar file so we get past the file existence check
            jar_path = server_dir / "server.jar"
            jar_path.touch()

            # Mock os.access to raise an exception
            with patch("os.access", side_effect=Exception("Access check failed")):
                valid, message = await manager._validate_server_files(server_dir)
                assert valid is False
                assert "File validation failed: Access check failed" in message

    # ===== Java Compatibility Tests =====

    @pytest.mark.asyncio
    async def test_check_java_compatibility_success(self, manager):
        """Test successful Java compatibility check"""
        from app.services.java_compatibility import JavaVersionInfo

        mock_java_info = JavaVersionInfo(17, 0, 1, "OpenJDK", "", "/usr/bin/java")

        with patch(
            "app.services.minecraft_server.java_compatibility_service"
        ) as mock_service:
            mock_service.get_java_for_minecraft = AsyncMock(return_value=mock_java_info)
            mock_service.validate_java_compatibility.return_value = (True, "Compatible")

            compatible, message, executable = await manager._check_java_compatibility(
                "1.18.0"
            )

            assert compatible is True
            assert "Compatible" in message
            assert executable == "/usr/bin/java"

    @pytest.mark.asyncio
    async def test_check_java_compatibility_no_java_found(self, manager):
        """Test Java compatibility check when no Java found"""
        with patch(
            "app.services.minecraft_server.java_compatibility_service"
        ) as mock_service:
            mock_service.get_java_for_minecraft = AsyncMock(return_value=None)
            mock_service.discover_java_installations = AsyncMock(return_value={})

            compatible, message, executable = await manager._check_java_compatibility(
                "1.18.0"
            )

            assert compatible is False
            assert "No Java installations found" in message
            assert executable is None

    @pytest.mark.asyncio
    async def test_check_java_compatibility_incompatible_version(self, manager):
        """Test Java compatibility check with incompatible version"""
        with patch(
            "app.services.minecraft_server.java_compatibility_service"
        ) as mock_service:
            mock_service.get_java_for_minecraft = AsyncMock(return_value=None)
            mock_service.discover_java_installations = AsyncMock(
                return_value={8: "java8_info"}
            )
            mock_service.get_required_java_version.return_value = 21

            compatible, message, executable = await manager._check_java_compatibility(
                "1.21.0"
            )

            assert compatible is False
            assert "requires Java 21" in message
            assert executable is None

    @pytest.mark.asyncio
    async def test_check_java_compatibility_exception(self, manager):
        """Test Java compatibility check exception handling"""
        with patch(
            "app.services.minecraft_server.java_compatibility_service"
        ) as mock_service:
            mock_service.get_java_for_minecraft.side_effect = Exception("Service error")

            compatible, message, executable = await manager._check_java_compatibility(
                "1.18.0"
            )

            assert compatible is False
            assert "Java compatibility check failed" in message
            assert executable is None

    @pytest.mark.asyncio
    async def test_check_java_compatibility_debug_logging(self, manager):
        """Test Java availability debug logging"""
        from app.services.java_compatibility import JavaVersionInfo

        mock_java_info = JavaVersionInfo(17, 0, 1, "OpenJDK", "", "/usr/bin/java")

        with patch(
            "app.services.minecraft_server.java_compatibility_service"
        ) as mock_service:
            mock_service.get_java_for_minecraft = AsyncMock(return_value=mock_java_info)
            mock_service.validate_java_compatibility.return_value = (True, "Compatible")

            with patch("app.services.minecraft_server.logger") as mock_logger:
                compatible, message, executable = await manager._check_java_compatibility(
                    "1.18.0"
                )

                assert compatible is True
                # Verify info logging happens
                mock_logger.info.assert_called()

    # ===== Server Startup Tests =====

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
            started_at=datetime.now(),
        )
        manager.processes[mock_server.id] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            result = await manager.start_server(mock_server)

            assert result is False
            mock_logger.warning.assert_called_with(
                f"Server {mock_server.id} is already running"
            )

    @pytest.mark.asyncio
    async def test_start_server_java_not_available(self, manager, mock_server):
        """Test server start when Java is not available"""
        with patch.object(
            manager,
            "_check_java_compatibility",
            return_value=(False, "Java not found", None),
        ):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                result = await manager.start_server(mock_server)

                assert result is False
                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_eula_acceptance_fails(self, manager, mock_server):
        """Test server start when EULA acceptance fails"""
        with patch.object(
            manager,
            "_check_java_compatibility",
            return_value=(True, "Java compatible", "/usr/bin/java"),
        ):
            with patch.object(
                manager, "_validate_server_files", return_value=(True, "Files valid")
            ):
                with patch.object(manager, "_ensure_eula_accepted", return_value=False):
                    with patch("app.services.minecraft_server.logger") as mock_logger:
                        result = await manager.start_server(mock_server)

                        assert result is False
                        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_file_validation_fails(self, manager, mock_server):
        """Test server start when file validation fails"""
        with patch.object(
            manager,
            "_check_java_compatibility",
            return_value=(True, "Java compatible", "/usr/bin/java"),
        ):
            with patch.object(manager, "_ensure_eula_accepted", return_value=True):
                with patch.object(
                    manager,
                    "_validate_server_files",
                    return_value=(False, "Files invalid"),
                ):
                    with patch("app.services.minecraft_server.logger") as mock_logger:
                        result = await manager.start_server(mock_server)

                        assert result is False
                        mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_subprocess_creation_oserror(self, manager, mock_server):
        """Test server start when subprocess creation raises OSError"""
        with patch.object(
            manager,
            "_check_java_compatibility",
            return_value=(True, "Java compatible", "/usr/bin/java"),
        ):
            with patch.object(manager, "_ensure_eula_accepted", return_value=True):
                with patch.object(
                    manager, "_validate_server_files", return_value=(True, "Valid")
                ):
                    with patch(
                        "asyncio.create_subprocess_exec",
                        side_effect=OSError("Failed to create process"),
                    ):
                        with patch("app.services.minecraft_server.logger") as mock_logger:
                            result = await manager.start_server(mock_server)

                            assert result is False
                            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_subprocess_creation_general_error(
        self, manager, mock_server
    ):
        """Test server start when subprocess creation raises general exception"""
        with patch.object(
            manager,
            "_check_java_compatibility",
            return_value=(True, "Java compatible", "/usr/bin/java"),
        ):
            with patch.object(manager, "_ensure_eula_accepted", return_value=True):
                with patch.object(
                    manager, "_validate_server_files", return_value=(True, "Valid")
                ):
                    with patch(
                        "asyncio.create_subprocess_exec",
                        side_effect=RuntimeError("Unexpected error"),
                    ):
                        with patch("app.services.minecraft_server.logger") as mock_logger:
                            result = await manager.start_server(mock_server)

                            assert result is False
                            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_process_none(self, manager, mock_server):
        """Test server start when subprocess creation returns None"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_server.directory_path = str(temp_path)

            with patch.object(
                manager,
                "_validate_port_availability",
                return_value=(True, "Port available"),
            ):
                with patch.object(
                    manager,
                    "_check_java_compatibility",
                    return_value=(True, "Java compatible", "/usr/bin/java"),
                ):
                    with patch.object(
                        manager, "_ensure_eula_accepted", return_value=True
                    ):
                        with patch.object(
                            manager,
                            "_validate_server_files",
                            return_value=(True, "Valid"),
                        ):
                            with patch(
                                "asyncio.create_subprocess_exec", return_value=None
                            ):
                                with patch(
                                    "app.services.minecraft_server.logger"
                                ) as mock_logger:
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

        with patch.object(
            manager,
            "_check_java_compatibility",
            return_value=(True, "Java compatible", "/usr/bin/java"),
        ):
            with patch.object(manager, "_ensure_eula_accepted", return_value=True):
                with patch.object(
                    manager, "_validate_server_files", return_value=(True, "Valid")
                ):
                    with patch(
                        "asyncio.create_subprocess_exec", return_value=mock_process
                    ):
                        with patch("app.services.minecraft_server.logger") as mock_logger:
                            result = await manager.start_server(mock_server)

                            assert result is False
                            mock_logger.error.assert_called()

    # ===== Server Stopping Tests =====

    @pytest.mark.asyncio
    async def test_stop_server_not_found(self, manager):
        """Test stopping a server that doesn't exist"""
        result = await manager.stop_server(999)
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_server_process_already_terminated(self, manager):
        """Test stopping server when process already terminated"""
        mock_process = Mock()
        mock_process.returncode = 0  # Process already terminated

        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            result = await manager.stop_server(1)

            assert result is True
            # Verify the specific log message
            mock_logger.info.assert_called_with("Server 1 process already terminated")
            # Verify process was cleaned up
            assert 1 not in manager.processes

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
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
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
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            result = await manager.stop_server(1, force=False)

            # Should fall back to terminate when stdin write fails
            mock_process.terminate.assert_called_once()
            mock_logger.warning.assert_called()

    # ===== Command Sending Tests =====

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
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        result = await manager.send_command(1, "help")

        # Should return False when stdin is None
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
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            result = await manager.send_command(1, "help")

            assert result is False
            mock_logger.error.assert_called()

    # ===== Log Management Tests =====

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

    @pytest.mark.asyncio
    async def test_stream_server_logs(self, manager):
        """Test stream_server_logs method"""
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
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        # Get one log line and break
        async for log in manager.stream_server_logs(1):
            assert log == "Test log line"
            # Remove from processes to break the loop
            del manager.processes[1]
            break

    @pytest.mark.asyncio
    async def test_read_server_logs_server_ready_detection(self, manager):
        """Test _read_server_logs detecting server ready status"""
        # Create a mock server process
        mock_process = AsyncMock()

        # Server ready message
        ready_message = (
            b'[12:34:56] [Server thread/INFO]: Done (1.234s)! For help, type "help"\n'
        )

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
            started_at=datetime.now(),
        )

        # Set up manager to track status changes
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            await manager._read_server_logs(server_process)

            # Verify status was updated to running
            assert server_process.status == ServerStatus.running
            mock_logger.info.assert_called_with("Server 1 is now running")

    @pytest.mark.asyncio
    async def test_read_server_logs_exception(self, manager):
        """Test _read_server_logs when exception occurs"""
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
            started_at=datetime.now(),
        )

        with patch("app.services.minecraft_server.logger") as mock_logger:
            await manager._read_server_logs(server_process)

            # Should log the error
            mock_logger.error.assert_called()

    # ===== Shutdown and Cleanup Tests =====

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
            started_at=datetime.now(),
        )

        server_process2 = ServerProcess(
            server_id=2,
            process=mock_process2,
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now(),
        )

        manager.processes[1] = server_process1
        manager.processes[2] = server_process2

        with patch("app.services.minecraft_server.logger") as mock_logger:
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
            started_at=datetime.now(),
        )
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            await manager.shutdown_all()

            # Should try terminate first, then kill on timeout
            mock_process.terminate.assert_called_once()
            mock_process.kill.assert_called_once()
            mock_logger.warning.assert_called()


class TestServerProcess:
    """Tests for ServerProcess dataclass"""

    def test_server_process_creation(self):
        """Test ServerProcess object creation"""
        mock_process = Mock()
        mock_queue = Mock()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        
        assert server_process.server_id == 1
        assert server_process.process == mock_process
        assert server_process.log_queue == mock_queue
        assert server_process.status == ServerStatus.running
        assert isinstance(server_process.started_at, datetime)

    def test_server_process_with_optional_fields(self):
        """Test ServerProcess with optional fields"""
        mock_process = Mock()
        mock_queue = Mock()
        start_time = datetime.now()
        
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=start_time,
            pid=12345
        )
        
        assert server_process.pid == 12345