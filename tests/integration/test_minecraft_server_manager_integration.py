"""
Comprehensive integration tests for MinecraftServerManager
Tests real file system operations, process management, and server lifecycle
"""

import asyncio
import os
import socket
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess
from app.services.java_compatibility import JavaVersionInfo


class MockJavaCompatibilityService:
    """Mock Java compatibility service for controlled testing"""
    
    def __init__(self):
        self.java_installations = {}
        self.java_for_minecraft = None
        self.compatibility_result = (True, "Compatible")
    
    def set_java_installations(self, installations):
        """Set mock Java installations"""
        self.java_installations = installations
    
    def set_java_for_minecraft(self, java_version: Optional[JavaVersionInfo]):
        """Set mock Java version for Minecraft"""
        self.java_for_minecraft = java_version
    
    def set_compatibility_result(self, is_compatible: bool, message: str):
        """Set mock compatibility result"""
        self.compatibility_result = (is_compatible, message)
    
    async def discover_java_installations(self):
        """Mock Java discovery"""
        return self.java_installations
    
    async def get_java_for_minecraft(self, minecraft_version: str):
        """Mock Java selection for Minecraft version"""
        return self.java_for_minecraft
    
    def get_required_java_version(self, minecraft_version: str):
        """Mock required Java version"""
        # Minecraft 1.18+ requires Java 17
        if minecraft_version.startswith(("1.18", "1.19", "1.20", "1.21")):
            return "17"
        return "8"
    
    def validate_java_compatibility(self, minecraft_version: str, java_version: JavaVersionInfo):
        """Mock Java compatibility validation"""
        return self.compatibility_result


class TestMinecraftServerManagerIntegration:
    """Integration tests for MinecraftServerManager with real file system and process operations"""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh manager instance for integration testing"""
        return MinecraftServerManager(log_queue_size=100)
    
    @pytest.fixture
    def mock_java_service(self):
        """Provide mock Java compatibility service"""
        return MockJavaCompatibilityService()
    
    @pytest.fixture
    def integration_server(self, tmp_path):
        """Create a server with real file system structure"""
        server_dir = tmp_path / "test-server"
        server_dir.mkdir()
        
        # Create a mock server.jar file
        jar_path = server_dir / "server.jar"
        jar_path.write_text("# Mock Minecraft Server JAR")
        
        # Find an available port for testing
        sock = socket.socket()
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        
        return Server(
            id=1,
            name="integration-test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=1024,
            directory_path=str(server_dir),
            port=port
        )
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session for port validation"""
        session = Mock(spec=Session)
        session.query.return_value.filter.return_value.first.return_value = None
        return session
    
    @pytest_asyncio.fixture
    async def mock_process_command(self, tmp_path):
        """Create a mock command that simulates a Minecraft server process"""
        # Create a Python script that acts like a Minecraft server
        mock_server_script = tmp_path / "mock_minecraft_server.py"
        mock_server_script.write_text("""
import sys
import time
import signal

def signal_handler(signum, frame):
    print("Server shutting down...")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)

print("[12:34:56] [Server thread/INFO]: Starting minecraft server version 1.20.1")
time.sleep(0.5)
print("[12:34:57] [Server thread/INFO]: Loading properties")
time.sleep(0.5)
print("[12:34:58] [Server thread/INFO]: Done (1.234s)! For help, type \\"help\\"")

# Keep server running and responding to commands
try:
    while True:
        line = input()
        if line.strip() == "stop":
            print("[12:34:59] [Server thread/INFO]: Stopping server")
            break
        else:
            print(f"[12:35:00] [Server thread/INFO]: Command executed: {line}")
except EOFError:
    pass

print("[12:35:01] [Server thread/INFO]: Server stopped")
""")
        
        return ["python", str(mock_server_script)]

    # ===== Java Compatibility Integration Tests =====

    @pytest.mark.asyncio
    async def test_java_compatibility_no_installations_found(self, manager, integration_server, mock_java_service):
        """Test lines 99-112: Handle no Java installations scenario"""
        # Setup: No Java installations available
        mock_java_service.set_java_installations({})
        mock_java_service.set_java_for_minecraft(None)
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            compatible, message, executable = await manager._check_java_compatibility("1.20.1")
            
            assert compatible is False
            assert "No Java installations found" in message
            assert "Please install OpenJDK and ensure it's accessible" in message
            assert executable is None

    @pytest.mark.asyncio
    async def test_java_compatibility_incompatible_version(self, manager, integration_server, mock_java_service):
        """Test lines 113-128: Handle incompatible Java version scenario"""
        # Setup: Java 8 available but Minecraft 1.20.1 requires Java 17
        java8 = JavaVersionInfo(8, 0, 292, "OpenJDK", "", "/usr/bin/java")
        mock_java_service.set_java_installations({8: java8})
        mock_java_service.set_java_for_minecraft(None)  # No compatible Java
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            compatible, message, executable = await manager._check_java_compatibility("1.20.1")
            
            assert compatible is False
            assert "Minecraft 1.20.1 requires Java 17" in message
            assert "but only Java [8] are available" in message
            assert "Please install Java 17" in message
            assert executable is None

    @pytest.mark.asyncio
    async def test_java_compatibility_success_with_logging(self, manager, integration_server, mock_java_service):
        """Test lines 130-143: Successful Java compatibility with logging"""
        # Setup: Compatible Java 17 available
        java17 = JavaVersionInfo(17, 0, 1, "OpenJDK", "17.0.1+12", "/usr/bin/java17")
        mock_java_service.set_java_for_minecraft(java17)
        mock_java_service.set_compatibility_result(True, "Java 17 is compatible with Minecraft 1.20.1")
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                compatible, message, executable = await manager._check_java_compatibility("1.20.1")
                
                assert compatible is True
                assert "Java 17 is compatible with Minecraft 1.20.1" in message
                assert executable == "/usr/bin/java17"
                
                # Verify logging (lines 130-134)
                mock_logger.info.assert_called_with(
                    "Selected Java 17 (17.0.1) at /usr/bin/java17 [OpenJDK]"
                )

    # ===== File System Validation Integration Tests =====

    @pytest.mark.asyncio
    async def test_ensure_eula_creation(self, manager, integration_server):
        """Test lines 157: EULA file creation when not exists"""
        server_dir = Path(integration_server.directory_path)
        eula_path = server_dir / "eula.txt"
        
        # Ensure EULA file doesn't exist initially
        if eula_path.exists():
            eula_path.unlink()
        
        result = await manager._ensure_eula_accepted(server_dir)
        
        assert result is True
        assert eula_path.exists()
        content = eula_path.read_text()
        assert "eula=true" in content

    @pytest.mark.asyncio
    async def test_ensure_eula_update_existing(self, manager, integration_server):
        """Test lines 162-166: EULA file update when already exists but not accepted"""
        server_dir = Path(integration_server.directory_path)
        eula_path = server_dir / "eula.txt"
        
        # Create EULA file with eula=false
        eula_path.write_text("eula=false\nother_content=true\n")
        
        result = await manager._ensure_eula_accepted(server_dir)
        
        assert result is True
        content = eula_path.read_text()
        assert "eula=true" in content

    @pytest.mark.asyncio
    async def test_validate_server_files_success(self, manager, integration_server):
        """Test lines 179-186: Successful file validation"""
        server_dir = Path(integration_server.directory_path)
        
        valid, message = await manager._validate_server_files(server_dir)
        
        assert valid is True
        assert "All files validated successfully" in message

    @pytest.mark.asyncio
    async def test_validate_server_files_jar_not_readable(self, manager, integration_server):
        """Test lines 179-180: JAR file not readable"""
        server_dir = Path(integration_server.directory_path)
        jar_path = server_dir / "server.jar"
        
        # Make JAR file not readable (if possible in test environment)
        try:
            jar_path.chmod(0o000)
            valid, message = await manager._validate_server_files(server_dir)
            
            assert valid is False
            assert "Server JAR is not readable" in message
        finally:
            # Restore permissions for cleanup
            jar_path.chmod(0o644)

    @pytest.mark.asyncio
    async def test_validate_server_files_directory_not_writable(self, manager, integration_server):
        """Test lines 183-184: Directory not writable"""
        server_dir = Path(integration_server.directory_path)
        
        # Make directory not writable (if possible in test environment)
        try:
            server_dir.chmod(0o444)
            valid, message = await manager._validate_server_files(server_dir)
            
            assert valid is False
            # The error might be about the directory or about files within it
            assert "Permission denied" in message or "not writable" in message
        finally:
            # Restore permissions for cleanup
            server_dir.chmod(0o755)

    # ===== Port Validation Integration Tests =====

    @pytest.mark.asyncio
    async def test_validate_port_availability_success(self, manager, integration_server, mock_db_session):
        """Test port validation success path with real socket operations"""
        available, message = await manager._validate_port_availability(integration_server, mock_db_session)
        
        assert available is True
        assert f"Port {integration_server.port} is available" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_database_conflict(self, manager, integration_server, mock_db_session):
        """Test port validation with database conflict"""
        # Mock database to return a conflicting server
        conflicting_server = Mock()
        conflicting_server.name = "existing-server"
        conflicting_server.status = ServerStatus.running
        mock_db_session.query.return_value.filter.return_value.first.return_value = conflicting_server
        
        available, message = await manager._validate_port_availability(integration_server, mock_db_session)
        
        assert available is False
        assert f"Port {integration_server.port} is already in use by running server 'existing-server'" in message

    @pytest.mark.asyncio
    async def test_validate_port_availability_system_conflict(self, manager, integration_server, mock_db_session):
        """Test port validation with system-level port conflict"""
        # Create a real socket binding to cause conflict
        conflict_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            conflict_socket.bind(("localhost", integration_server.port))
            conflict_socket.listen(1)
            
            available, message = await manager._validate_port_availability(integration_server, mock_db_session)
            
            assert available is False
            assert f"Port {integration_server.port} is already in use by another process" in message
        finally:
            conflict_socket.close()

    # ===== Exception Handling Integration Tests =====

    @pytest.mark.asyncio
    async def test_notify_status_change_callback_exception(self, manager):
        """Test lines 48-51: Status callback exception handling"""
        callback = Mock(side_effect=Exception("Database connection failed"))
        manager.set_status_update_callback(callback)
        
        with patch("app.services.minecraft_server.logger") as mock_logger:
            # This should not raise exception even though callback fails
            manager._notify_status_change(1, ServerStatus.running)
            
            callback.assert_called_once_with(1, ServerStatus.running)
            mock_logger.error.assert_called_once()
            assert "Failed to update database status for server 1" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_cleanup_server_process_queue_exception(self, manager):
        """Test lines 67-68: Queue cleanup exception handling in real scenario"""
        # Create a real queue but force exception during cleanup
        log_queue = asyncio.Queue()
        await log_queue.put("test log")
        
        # Create mock process
        mock_process = Mock()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[1] = server_process
        
        # Force exception by patching qsize method
        with patch.object(log_queue, 'qsize', side_effect=Exception("Queue error")):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                await manager._cleanup_server_process(1)
                
                mock_logger.error.assert_called()
                assert "Error during cleanup for server 1" in str(mock_logger.error.call_args)

    # ===== Server Process Integration Tests =====

    @pytest.mark.asyncio
    async def test_get_server_info_with_real_process_data(self, manager):
        """Test lines 521: Get server info for running server"""
        # Create a server process with real data
        mock_process = Mock()
        mock_process.pid = 12345
        
        start_time = datetime.now()
        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
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
        assert "uptime_seconds" in info
        assert info["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_list_running_servers_integration(self, manager):
        """Test server listing with multiple processes"""
        # Add multiple server processes
        for server_id in [1, 2, 3]:
            mock_process = Mock()
            mock_process.pid = 1000 + server_id
            server_process = ServerProcess(
                server_id=server_id,
                process=mock_process,
                log_queue=asyncio.Queue(),
                status=ServerStatus.running,
                started_at=datetime.now(),
                pid=1000 + server_id
            )
            manager.processes[server_id] = server_process
        
        running_servers = manager.list_running_servers()
        
        assert set(running_servers) == {1, 2, 3}
        assert len(running_servers) == 3

    @pytest.mark.asyncio
    async def test_shutdown_all_integration(self, manager):
        """Test bulk server shutdown coordination (lines 675-676, 680)"""
        # Create multiple server processes
        server_processes = {}
        for server_id in [1, 2, 3]:
            mock_process = Mock()
            mock_process.returncode = None
            mock_process.terminate = Mock()
            mock_process.wait = AsyncMock(return_value=0)
            
            server_process = ServerProcess(
                server_id=server_id,
                process=mock_process,
                log_queue=asyncio.Queue(),
                status=ServerStatus.running,
                started_at=datetime.now()
            )
            server_processes[server_id] = server_process
            manager.processes[server_id] = server_process
        
        # Mock the stop_server method to avoid complex shutdown logic
        with patch.object(manager, 'stop_server', new_callable=AsyncMock) as mock_stop:
            mock_stop.return_value = True
            await manager.shutdown_all()
            
            # Verify stop_server was called for all servers
            assert mock_stop.call_count == 3
            for server_id in [1, 2, 3]:
                mock_stop.assert_any_call(server_id)


class TestMinecraftServerManagerComplexIntegration:
    """More complex integration scenarios"""
    
    @pytest.fixture
    def manager(self):
        return MinecraftServerManager(log_queue_size=50)
    
    @pytest.mark.asyncio
    async def test_concurrent_server_operations(self, manager, tmp_path):
        """Test concurrent server management operations"""
        # This tests the robustness of the manager under concurrent load
        servers = []
        
        for i in range(3):
            server_dir = tmp_path / f"server-{i}"
            server_dir.mkdir()
            (server_dir / "server.jar").write_text("mock jar")
            
            # Get available port
            sock = socket.socket()
            sock.bind(('localhost', 0))
            port = sock.getsockname()[1]
            sock.close()
            
            servers.append(Server(
                id=i + 1,
                name=f"test-server-{i}",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                max_memory=512,
                directory_path=str(server_dir),
                port=port
            ))
        
        # Test concurrent operations don't interfere with each other
        tasks = []
        for server in servers:
            # Test concurrent file validation
            task = asyncio.create_task(manager._validate_server_files(Path(server.directory_path)))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # All validations should succeed
        for valid, message in results:
            assert valid is True
            assert "All files validated successfully" in message

    @pytest.mark.asyncio
    async def test_resource_cleanup_under_stress(self, manager):
        """Test resource cleanup under stress conditions"""
        # Create many server processes and clean them up rapidly
        server_processes = []
        
        for i in range(10):
            mock_process = Mock()
            mock_process.pid = 2000 + i
            log_queue = asyncio.Queue()
            
            # Add some logs to the queue
            for j in range(5):
                await log_queue.put(f"Log {j} from server {i}")
            
            server_process = ServerProcess(
                server_id=i + 1,
                process=mock_process,
                log_queue=log_queue,
                status=ServerStatus.running,
                started_at=datetime.now(),
                pid=2000 + i
            )
            server_processes.append(server_process)
            manager.processes[i + 1] = server_process
        
        # Cleanup all processes concurrently
        cleanup_tasks = []
        for i in range(10):
            task = asyncio.create_task(manager._cleanup_server_process(i + 1))
            cleanup_tasks.append(task)
        
        await asyncio.gather(*cleanup_tasks)
        
        # Verify all processes were cleaned up
        assert len(manager.processes) == 0
        
        # Verify queues were emptied
        for server_process in server_processes:
            assert server_process.log_queue.qsize() == 0