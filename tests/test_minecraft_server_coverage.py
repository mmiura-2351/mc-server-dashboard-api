import pytest
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
from datetime import datetime

from app.services.minecraft_server import (
    MinecraftServerManager, 
    minecraft_server_manager,
    ServerProcess
)
from app.servers.models import ServerStatus


class TestMinecraftServerManagerBasic:
    """Basic tests to improve MinecraftServerManager coverage"""

    def test_init(self):
        """Test MinecraftServerManager initialization"""
        manager = MinecraftServerManager()
        assert manager.processes == {}
        assert manager.base_directory == Path("servers")
        assert isinstance(manager.base_directory, Path)

    def test_singleton_instance(self):
        """Test that minecraft_server_manager is available"""
        assert minecraft_server_manager is not None
        assert isinstance(minecraft_server_manager, MinecraftServerManager)

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

    def test_get_server_info_not_found(self):
        """Test get_server_info when server not found"""
        manager = MinecraftServerManager()
        
        info = manager.get_server_info(999)
        assert info is None

    def test_get_server_info_with_process(self):
        """Test get_server_info with existing process"""
        manager = MinecraftServerManager()
        
        started_time = datetime.now()
        mock_process = ServerProcess(
            server_id=123,
            process=Mock(),
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=started_time,
            pid=12345
        )
        manager.processes[123] = mock_process
        
        info = manager.get_server_info(123)
        assert info is not None
        assert info["server_id"] == 123
        assert info["pid"] == 12345
        assert info["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_server_logs_no_process(self):
        """Test get_server_logs when no process exists"""
        manager = MinecraftServerManager()
        
        result = await manager.get_server_logs(999)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_server_logs_with_process(self):
        """Test get_server_logs with existing process"""
        manager = MinecraftServerManager()
        
        # Create mock queue with logs
        import asyncio
        mock_queue = asyncio.Queue()
        await mock_queue.put("log line 1")
        await mock_queue.put("log line 2")
        
        mock_process = ServerProcess(
            server_id=123,
            process=Mock(),
            log_queue=mock_queue,
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        manager.processes[123] = mock_process
        
        result = await manager.get_server_logs(123, lines=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_send_command_no_process(self):
        """Test send_command when no process exists"""
        manager = MinecraftServerManager()
        
        result = await manager.send_command(999, "test command")
        assert result is False

    def test_list_running_servers_empty(self):
        """Test list_running_servers with no servers"""
        manager = MinecraftServerManager()
        
        servers = manager.list_running_servers()
        assert servers == []

    def test_list_running_servers_with_servers(self):
        """Test list_running_servers with active servers"""
        manager = MinecraftServerManager()
        
        mock_process1 = ServerProcess(
            server_id=123,
            process=Mock(),
            log_queue=Mock(),
            status=ServerStatus.running,
            started_at=datetime.now()
        )
        mock_process2 = ServerProcess(
            server_id=456,
            process=Mock(),
            log_queue=Mock(),
            status=ServerStatus.starting,
            started_at=datetime.now()
        )
        manager.processes[123] = mock_process1
        manager.processes[456] = mock_process2
        
        servers = manager.list_running_servers()
        assert set(servers) == {123, 456}

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


class TestServerProcessDataclass:
    """Test ServerProcess dataclass"""

    def test_server_process_creation(self):
        """Test ServerProcess creation"""
        mock_process = Mock()
        mock_queue = Mock()
        started_time = datetime.now()
        
        server_process = ServerProcess(
            server_id=123,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.starting,
            started_at=started_time,
            pid=12345
        )
        
        assert server_process.server_id == 123
        assert server_process.process == mock_process
        assert server_process.log_queue == mock_queue
        assert server_process.status == ServerStatus.starting
        assert server_process.started_at == started_time
        assert server_process.pid == 12345

    def test_server_process_no_pid(self):
        """Test ServerProcess creation without PID"""
        mock_process = Mock()
        mock_queue = Mock()
        started_time = datetime.now()
        
        server_process = ServerProcess(
            server_id=456,
            process=mock_process,
            log_queue=mock_queue,
            status=ServerStatus.stopped,
            started_at=started_time
        )
        
        assert server_process.pid is None