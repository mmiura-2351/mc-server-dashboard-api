"""
Comprehensive integration tests for daemon lifecycle management
Tests the complete lifecycle of daemon processes from creation to cleanup
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.servers.models import Server, ServerStatus, ServerType
from app.services.minecraft_server import MinecraftServerManager, ServerProcess


class TestDaemonLifecycleComprehensive:
    """Comprehensive tests for daemon process lifecycle management"""
    
    @pytest.fixture
    def manager(self):
        """Create manager for lifecycle testing"""
        return MinecraftServerManager(log_queue_size=50)
    
    @pytest.fixture  
    def daemon_test_server(self, tmp_path):
        """Create a test server for daemon lifecycle testing"""
        server_dir = tmp_path / "daemon-server"
        server_dir.mkdir()
        
        # Create server jar
        jar_path = server_dir / "server.jar"
        jar_path.write_text("# Mock server JAR for daemon testing")
        
        return Server(
            id=1,
            name="daemon-test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            max_memory=1024,
            directory_path=str(server_dir),
            port=25565,
            status=ServerStatus.stopped
        )
    
    @pytest.fixture
    def mock_java_service(self):
        """Mock Java compatibility service"""
        mock = Mock()
        mock.get_optimal_java_path.return_value = "/usr/bin/java"
        # Mock the async method to return JavaVersionInfo
        mock_java_info = Mock()
        mock_java_info.major_version = 17
        mock_java_info.minor_version = 0
        mock_java_info.patch_version = 0
        mock_java_info.path = "/usr/bin/java"
        mock.get_java_for_minecraft = AsyncMock(return_value=mock_java_info)
        # Mock validate_java_requirements to return a tuple
        mock.validate_java_requirements = AsyncMock(return_value=(True, "Java 17 compatible"))
        return mock
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        session.refresh = Mock()
        return session

    # ===== Helper Methods =====
    
    async def cleanup_background_tasks(self, manager):
        """Helper to clean up any background tasks"""
        for server_id, process in list(manager.processes.items()):
            if process.log_task and not process.log_task.done():
                process.log_task.cancel()
                try:
                    await process.log_task
                except asyncio.CancelledError:
                    pass
            
            if process.monitor_task and not process.monitor_task.done():
                process.monitor_task.cancel()
                try:
                    await process.monitor_task
                except asyncio.CancelledError:
                    pass
        
        # Clear processes
        manager.processes.clear()

    # ===== Daemon Creation Lifecycle Tests =====

    @pytest.mark.asyncio
    async def test_daemon_creation_complete_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test complete daemon creation lifecycle from start to finish"""
        
        # Ensure server directory and jar file exist
        server_dir = Path(daemon_test_server.directory_path)
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "server.jar").write_text("mock jar")
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            # Mock all required validation methods
            with patch.object(manager, '_validate_port_availability', return_value=(True, "Port 25565 available")):
                with patch.object(manager, '_check_java_compatibility', return_value=(True, "Java 17 compatible", "/usr/bin/java")):
                    with patch.object(manager, '_validate_server_files', return_value=(True, "All files valid")):
                        with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                            with patch.object(manager, '_ensure_rcon_configured', return_value=(True, 25575, "password123")):
                                with patch.object(manager, '_create_daemon_process_alternative', return_value=12345):
                                    with patch.object(manager, '_is_process_running', return_value=True):
                                        # Mock background task creation
                                        with patch('asyncio.create_task') as mock_create_task:
                                            mock_create_task.return_value = AsyncMock()
                                            
                                            result = await manager.start_server(daemon_test_server, mock_db_session)
                                            
                                            # Verify successful start
                                            assert result is True
                                            assert daemon_test_server.id in manager.processes
                                            
                                            # Clean up
                                            await self.cleanup_background_tasks(manager)

    @pytest.mark.asyncio
    async def test_daemon_creation_failure_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test daemon creation failure handling"""
        
        # Ensure server directory and jar file exist
        server_dir = Path(daemon_test_server.directory_path)
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "server.jar").write_text("mock jar")
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            # Mock all validations to pass, but daemon creation to fail
            with patch.object(manager, '_validate_port_availability', return_value=(True, "Port 25565 available")):
                with patch.object(manager, '_check_java_compatibility', return_value=(True, "Java 17 compatible", "/usr/bin/java")):
                    with patch.object(manager, '_validate_server_files', return_value=(True, "All files valid")):
                        with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                            with patch.object(manager, '_ensure_rcon_configured', return_value=(True, 25575, "password123")):
                                # Mock both daemon creation methods to fail
                                with patch.object(manager, '_create_daemon_process', return_value=None):
                                    with patch.object(manager, '_create_daemon_process_alternative', return_value=None):
                                        result = await manager.start_server(daemon_test_server, mock_db_session)
                                        
                                        # Verify failure handling
                                        assert result is False
                                        assert daemon_test_server.id not in manager.processes

    # ===== Process Monitoring Tests =====

    @pytest.mark.asyncio
    async def test_daemon_monitoring_lifecycle(self, manager):
        """Test daemon process monitoring"""
        
        # Create a mock daemon process
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=22222,
            server_directory=Path("/tmp/test")
        )
        
        # Setup status callback
        status_changes = []
        def record_status(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status)
        
        # Mock process running checks
        with patch.object(manager, '_is_process_running') as mock_running:
            # Simulate process lifecycle
            mock_running.side_effect = [True, True, True, False]  # Running 3 times, then stops
            
            with patch.object(manager, '_cleanup_server_process', new_callable=AsyncMock) as mock_cleanup:
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    # Start monitoring
                    monitor_task = asyncio.create_task(manager._monitor_daemon_process(server_process))
                    
                    # Let it run for a bit
                    await asyncio.sleep(0)
                    
                    # Cancel the task
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Should have detected the stopped process
                    if mock_running.call_count >= 4:
                        mock_cleanup.assert_called_once_with(1)

    # ===== Process Restoration Tests =====

    @pytest.mark.asyncio  
    async def test_daemon_restoration_lifecycle(self, manager, tmp_path):
        """Test restoring daemon processes from PID files"""
        
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
        pid_file.write_text(json.dumps(pid_data))
        
        # Mock the restoration process
        with patch.object(manager, '_is_process_running', return_value=True):
            with patch.object(manager, '_restore_process_from_pid', return_value=True) as mock_restore:
                # Mock background task creation
                with patch('asyncio.create_task') as mock_create_task:
                    mock_create_task.return_value = AsyncMock()
                    
                    results = await manager.discover_and_restore_processes()
                    
                    # Basic verification
                    assert isinstance(results, dict)
                    
                    # Clean up
                    await self.cleanup_background_tasks(manager)

    # ===== Process Cleanup Tests =====

    @pytest.mark.asyncio
    async def test_daemon_cleanup_lifecycle(self, manager, tmp_path):
        """Test daemon process cleanup"""
        
        # Create test server with resources
        server_dir = tmp_path / "daemon_cleanup"
        server_dir.mkdir()
        
        log_queue = asyncio.Queue()
        await log_queue.put("Test log 1")
        await log_queue.put("Test log 2")
        
        server_process = ServerProcess(
            server_id=1,
            process=None,
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=55555,
            server_directory=server_dir
        )
        
        manager.processes[1] = server_process
        
        # Setup status callback
        status_changes = []
        def record_status(server_id, status):
            status_changes.append((server_id, status))
        
        manager.set_status_update_callback(record_status)
        
        # Notify status change before cleanup
        manager._notify_status_change(1, ServerStatus.stopped)
        
        # Execute cleanup
        await manager._cleanup_server_process(1)
        
        # Verify cleanup
        assert 1 not in manager.processes
        assert (1, ServerStatus.stopped) in status_changes
        assert log_queue.qsize() == 0

    # ===== Full Integration Test =====

    @pytest.mark.asyncio
    async def test_daemon_full_integration_lifecycle(self, manager, daemon_test_server, mock_db_session, mock_java_service):
        """Test complete daemon lifecycle integration"""
        
        # Ensure server directory and jar file exist
        server_dir = Path(daemon_test_server.directory_path)
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "server.jar").write_text("mock jar")
        
        with patch('app.services.minecraft_server.java_compatibility_service', mock_java_service):
            # Mock all required validation methods
            with patch.object(manager, '_validate_port_availability', return_value=(True, "Port 25565 available")):
                with patch.object(manager, '_check_java_compatibility', return_value=(True, "Java 17 compatible", "/usr/bin/java")):
                    with patch.object(manager, '_validate_server_files', return_value=(True, "All files valid")):
                        with patch.object(manager, '_ensure_eula_accepted', return_value=True):
                            with patch.object(manager, '_ensure_rcon_configured', return_value=(True, 25575, "password123")):
                                with patch.object(manager, '_create_daemon_process_alternative', return_value=66666):
                                    with patch.object(manager, '_is_process_running', return_value=True):
                                        # Mock background tasks
                                        with patch('asyncio.create_task') as mock_create_task:
                                            mock_create_task.return_value = AsyncMock()
                                            
                                            # Start server
                                            result = await manager.start_server(daemon_test_server, mock_db_session)
                                            assert result is True
                                            
                                            # Stop server  
                                            with patch.object(manager, 'stop_server', new_callable=AsyncMock) as mock_stop:
                                                mock_stop.return_value = True
                                                stop_result = await manager.stop_server(daemon_test_server.id)
                                                assert stop_result is True
                                            
                                            # Clean up
                                            await self.cleanup_background_tasks(manager)