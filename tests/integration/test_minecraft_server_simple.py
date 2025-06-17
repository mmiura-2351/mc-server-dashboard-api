"""
Simple integration tests for MinecraftServerManager
Focus on testing actual uncovered lines with minimal complexity
"""

import asyncio
import os
import socket
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.orm import Session

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess
from app.services.java_compatibility import JavaVersionInfo


class MockJavaService:
    """Simple mock Java service for testing"""
    
    def __init__(self):
        self.java_version = JavaVersionInfo(17, 0, 1, "OpenJDK", "17.0.1+12", "/usr/bin/java")
        self.installations = {17: self.java_version}
        self.compatible = True
    
    async def discover_java_installations(self):
        return self.installations
    
    async def get_java_for_minecraft(self, minecraft_version: str):
        return self.java_version if self.compatible else None
    
    def get_required_java_version(self, minecraft_version: str):
        return "17"
    
    def validate_java_compatibility(self, minecraft_version: str, java_version: JavaVersionInfo):
        return self.compatible, "Compatible"


class TestMinecraftServerManagerSimpleIntegration:
    """Simple integration tests targeting specific uncovered lines"""
    
    @pytest.fixture
    def manager(self):
        return MinecraftServerManager(log_queue_size=10)
    
    @pytest.fixture
    def simple_server(self, tmp_path):
        """Create a basic server for testing"""
        server_dir = tmp_path / "simple-server"
        server_dir.mkdir()
        
        # Create server.jar
        jar_path = server_dir / "server.jar"
        jar_path.write_text("# Mock JAR")
        
        # Get available port
        sock = socket.socket()
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        
        return Server(
            id=1,
            name="simple-test",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=512,
            directory_path=str(server_dir),
            port=port
        )
    
    @pytest.fixture
    def mock_java_service(self):
        return MockJavaService()
    
    @pytest.fixture
    def mock_db_session(self):
        session = Mock(spec=Session)
        session.query.return_value.filter.return_value.first.return_value = None
        return session
    
    # ===== Test Java Compatibility Error Paths =====
    
    @pytest.mark.asyncio
    async def test_java_compatibility_no_installations(self, manager, mock_java_service):
        """Test lines 99-112: No Java installations found"""
        mock_java_service.installations = {}
        mock_java_service.compatible = False
        
        # Patch at the module level where it's imported
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            compatible, message, executable = await manager._check_java_compatibility("1.20.1")
            
            assert compatible is False
            assert "No Java installations found" in message
            assert "Please install OpenJDK" in message
            assert executable is None
    
    @pytest.mark.asyncio
    async def test_java_compatibility_incompatible_version(self, manager, mock_java_service):
        """Test lines 113-128: Incompatible Java version"""
        # Make Java incompatible
        mock_java_service.compatible = False
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            compatible, message, executable = await manager._check_java_compatibility("1.20.1")
            
            assert compatible is False
            assert "Minecraft 1.20.1 requires Java 17" in message
            assert "but only Java [17] are available" in message
            assert executable is None
    
    @pytest.mark.asyncio
    async def test_java_compatibility_success(self, manager, mock_java_service):
        """Test lines 130-143: Successful Java compatibility"""
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                compatible, message, executable = await manager._check_java_compatibility("1.20.1")
                
                assert compatible is True
                assert "compatible" in message.lower()
                assert executable == "/usr/bin/java"
                
                # Verify logging
                mock_logger.info.assert_called_with(
                    "Selected Java 17 (17.0.1) at /usr/bin/java [OpenJDK]"
                )
    
    @pytest.mark.asyncio
    async def test_java_compatibility_exception_handling(self, manager):
        """Test lines 145-148: Exception handling in Java compatibility"""
        mock_java_service = Mock()
        mock_java_service.get_java_for_minecraft = AsyncMock(side_effect=Exception("Java service failed"))
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                compatible, message, executable = await manager._check_java_compatibility("1.20.1")
                
                assert compatible is False
                assert "Java compatibility check failed" in message
                assert "Exception: Java service failed" in message
                assert executable is None
                
                mock_logger.error.assert_called()
    
    # ===== Test File Validation Error Paths =====
    
    @pytest.mark.asyncio
    async def test_validate_server_files_jar_not_readable(self, manager, simple_server):
        """Test lines 179-180: JAR file not readable"""
        server_dir = Path(simple_server.directory_path)
        jar_path = server_dir / "server.jar"
        
        # Make JAR not readable
        try:
            jar_path.chmod(0o000)
            valid, message = await manager._validate_server_files(server_dir)
            
            assert valid is False
            assert "Server JAR is not readable" in message
        finally:
            jar_path.chmod(0o644)
    
    @pytest.mark.asyncio
    async def test_validate_server_files_directory_not_writable(self, manager, simple_server):
        """Test lines 183-184: Directory not writable"""
        server_dir = Path(simple_server.directory_path)
        
        # Make directory not writable
        try:
            server_dir.chmod(0o444)
            valid, message = await manager._validate_server_files(server_dir)
            
            assert valid is False
            # The error might be about the directory or about files within it
            assert "Permission denied" in message or "not writable" in message
        finally:
            server_dir.chmod(0o755)
    
    # ===== Test Status Change Callback =====
    
    @pytest.mark.asyncio
    async def test_status_change_callback_exception(self, manager):
        """Test lines 48-51: Status callback exception handling"""
        callback = Mock(side_effect=Exception("Database connection failed"))
        manager.set_status_update_callback(callback)
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            manager._notify_status_change(1, ServerStatus.running)
            
            callback.assert_called_once_with(1, ServerStatus.running)
            mock_logger.error.assert_called_once()
            assert "Failed to update database status for server 1" in str(mock_logger.error.call_args)
    
    # ===== Test Server Already Running =====
    
    @pytest.mark.asyncio
    async def test_start_server_already_running(self, manager, simple_server, mock_db_session):
        """Test lines 253-255: Server already running"""
        # Add server to processes dict
        mock_process = Mock()
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
            result = await manager.start_server(simple_server, mock_db_session)
            
            assert result is False
            mock_logger.warning.assert_called_with("Server 1 is already running")
    
    # ===== Test Command Sending =====
    
    @pytest.mark.asyncio
    async def test_send_command_server_not_running(self, manager):
        """Test lines 503-504: Command to non-running server"""
        result = await manager.send_command(999, "test command")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_command_no_stdin(self, manager):
        """Test lines 507, 512: Command when stdin not available"""
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
    async def test_send_command_success(self, manager):
        """Test lines 508-511: Successful command sending"""
        mock_process = Mock()
        mock_stdin = Mock()
        # Make write and drain regular methods, not async
        mock_stdin.write = Mock()
        mock_stdin.drain = AsyncMock()
        mock_process.stdin = mock_stdin
        
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
        
        assert result is True
        mock_stdin.write.assert_called_once_with(b"test command\n")
        mock_stdin.drain.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_command_exception(self, manager):
        """Test lines 514-516: Command sending exception"""
        mock_process = Mock()
        mock_stdin = Mock()
        mock_stdin.write = Mock(side_effect=Exception("Write failed"))
        mock_process.stdin = mock_stdin
        
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
            assert "Failed to send command to server 1" in str(mock_logger.error.call_args)
    
    # ===== Test Log Retrieval =====
    
    @pytest.mark.asyncio
    async def test_get_server_logs_success(self, manager):
        """Test lines 545-556: Get server logs"""
        log_queue = asyncio.Queue()
        
        # Add some test logs
        test_logs = ["Log 1", "Log 2", "Log 3"]
        for log in test_logs:
            await log_queue.put(log)
        
        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        logs = await manager.get_server_logs(1, lines=2)
        
        assert len(logs) == 2
        assert logs[0] == "Log 1"
        assert logs[1] == "Log 2"
    
    @pytest.mark.asyncio
    async def test_get_server_logs_server_not_running(self, manager):
        """Test lines 542-543: Get logs from non-running server"""
        logs = await manager.get_server_logs(999)
        assert logs == []
    
    # ===== Test Server Status =====
    
    @pytest.mark.asyncio
    async def test_get_server_status_running(self, manager):
        """Test lines 521: Get status of running server"""
        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        status = manager.get_server_status(1)
        assert status == ServerStatus.running
    
    @pytest.mark.asyncio
    async def test_get_server_status_not_running(self, manager):
        """Test server status when not running"""
        status = manager.get_server_status(999)
        assert status == ServerStatus.stopped
    
    # ===== Test Cleanup Error Handling =====
    
    @pytest.mark.asyncio
    async def test_cleanup_server_process_queue_exception(self, manager):
        """Test lines 67-68: Cleanup with queue exception"""
        # Create queue that will cause exception
        log_queue = asyncio.Queue()
        await log_queue.put("test log")
        
        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345
        )
        manager.processes[1] = server_process
        
        # Force exception by patching qsize
        with patch.object(log_queue, 'qsize', side_effect=Exception("Queue error")):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                await manager._cleanup_server_process(1)
                
                mock_logger.error.assert_called()
                assert "Error during cleanup for server 1" in str(mock_logger.error.call_args)