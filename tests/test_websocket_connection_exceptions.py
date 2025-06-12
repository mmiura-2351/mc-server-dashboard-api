import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from app.services.websocket_service import ConnectionManager
from app.users.models import User


class TestConnectionManagerExceptions:
    """Test exception handling in ConnectionManager."""

    @pytest.fixture
    def connection_manager(self):
        """Create a ConnectionManager instance."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket connection."""
        websocket = Mock(spec=WebSocket)
        websocket.accept = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.close = AsyncMock()
        return websocket

    @pytest.fixture
    def mock_user(self):
        """Create a mock user."""
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        return user

    # Test WebSocket connection failures
    @pytest.mark.asyncio
    async def test_connect_websocket_disconnect_during_accept(self, connection_manager, mock_websocket, mock_user):
        """Test connecting when WebSocket disconnects during accept."""
        mock_websocket.accept.side_effect = WebSocketDisconnect(code=1000)
        
        with pytest.raises(WebSocketDisconnect):
            await connection_manager.connect(mock_websocket, 1, mock_user)
        
        # Connection should not be added to active connections
        assert 1 not in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_connect_connection_error(self, connection_manager, mock_websocket, mock_user):
        """Test connecting with general connection error."""
        mock_websocket.accept.side_effect = ConnectionError("Connection failed")
        
        with pytest.raises(ConnectionError):
            await connection_manager.connect(mock_websocket, 1, mock_user)
        
        assert 1 not in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_connect_runtime_error(self, connection_manager, mock_websocket, mock_user):
        """Test connecting with runtime error."""
        mock_websocket.accept.side_effect = RuntimeError("WebSocket error")
        
        with pytest.raises(RuntimeError):
            await connection_manager.connect(mock_websocket, 1, mock_user)
        
        assert 1 not in connection_manager.active_connections

    # Test broadcast message failures
    @pytest.mark.asyncio
    async def test_broadcast_partial_failures(self, connection_manager, mock_user):
        """Test broadcast when some connections fail."""
        # Create multiple mock websockets
        mock_ws1 = Mock(spec=WebSocket)
        mock_ws1.send_text = AsyncMock()
        mock_ws2 = Mock(spec=WebSocket)
        mock_ws2.send_text = AsyncMock(side_effect=WebSocketDisconnect(code=1000))
        mock_ws3 = Mock(spec=WebSocket)
        mock_ws3.send_text = AsyncMock()
        
        # Add connections manually
        connection_manager.active_connections[1] = {mock_ws1, mock_ws2, mock_ws3}
        connection_manager.user_connections[mock_ws1] = mock_user
        connection_manager.user_connections[mock_ws2] = mock_user
        connection_manager.user_connections[mock_ws3] = mock_user
        
        # Broadcast message should handle partial failures gracefully
        await connection_manager.send_to_server_connections(1, {"message": "test message"})
        
        # Failed connection should be cleaned up
        assert mock_ws2 not in connection_manager.active_connections[1]
        assert mock_ws1 in connection_manager.active_connections[1]
        assert mock_ws3 in connection_manager.active_connections[1]

    @pytest.mark.asyncio
    async def test_broadcast_all_connections_fail(self, connection_manager, mock_user):
        """Test broadcast when all connections fail."""
        mock_ws1 = Mock(spec=WebSocket)
        mock_ws1.send_text = AsyncMock(side_effect=ConnectionError("Failed"))
        mock_ws2 = Mock(spec=WebSocket)
        mock_ws2.send_text = AsyncMock(side_effect=WebSocketDisconnect(code=1000))
        
        connection_manager.active_connections[1] = {mock_ws1, mock_ws2}
        connection_manager.user_connections[mock_ws1] = mock_user
        connection_manager.user_connections[mock_ws2] = mock_user
        
        await connection_manager.send_to_server_connections(1, {"message": "test message"})
        
        # All connections should be removed
        assert len(connection_manager.active_connections.get(1, set())) == 0

    # Test log streaming failures
    @pytest.mark.asyncio
    async def test_log_streaming_file_not_found(self, connection_manager):
        """Test log streaming when server log file doesn't exist."""
        # Mock minecraft_server_manager to return non-existent log file
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_manager:
            mock_manager.get_log_file_path.return_value = "/non/existent/file.log"
            
            # Should handle gracefully without crashing
            task = asyncio.create_task(connection_manager._stream_server_logs(1))
            
            # Let it run briefly then cancel
            await asyncio.sleep(0.1)
            task.cancel()
            
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_log_streaming_permission_denied(self, connection_manager):
        """Test log streaming when log file access is denied."""
        # Create a temporary file with no read permissions
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        temp_file.write("test log content\n")
        temp_file.close()
        
        temp_path = Path(temp_file.name)
        temp_path.chmod(0o000)
        
        try:
            with patch('app.services.websocket_service.minecraft_server_manager') as mock_manager:
                mock_manager.get_log_file_path.return_value = str(temp_path)
                
                # Should handle permission error gracefully
                task = asyncio.create_task(connection_manager._stream_server_logs(1))
                
                await asyncio.sleep(0.1)
                task.cancel()
                
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            temp_path.chmod(0o644)
            temp_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_log_streaming_unicode_decode_error(self, connection_manager):
        """Test log streaming with unicode decoding issues."""
        # Create file with invalid UTF-8
        temp_file = tempfile.NamedTemporaryFile(mode='wb', delete=False)
        temp_file.write(b'\xff\xfe\x00\x00invalid utf-8\n')
        temp_file.close()
        
        try:
            with patch('app.services.websocket_service.minecraft_server_manager') as mock_manager:
                mock_manager.get_log_file_path.return_value = temp_file.name
                
                # Should handle unicode errors gracefully
                task = asyncio.create_task(connection_manager._stream_server_logs(1))
                
                await asyncio.sleep(0.1)
                task.cancel()
                
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            Path(temp_file.name).unlink(missing_ok=True)

    # Test disconnect cleanup failures
    def test_disconnect_nonexistent_server(self, connection_manager, mock_websocket):
        """Test disconnecting from server that doesn't exist."""
        # Should handle gracefully without error
        connection_manager.disconnect(mock_websocket, 999)

    def test_disconnect_nonexistent_websocket(self, connection_manager, mock_websocket, mock_user):
        """Test disconnecting websocket that wasn't connected."""
        # Add server but not this specific websocket
        connection_manager.active_connections[1] = set()
        
        # Should handle gracefully
        connection_manager.disconnect(mock_websocket, 1)

    # Test concurrent operations
    @pytest.mark.asyncio
    async def test_concurrent_connect_disconnect(self, connection_manager, mock_user):
        """Test concurrent connect and disconnect operations."""
        mock_ws = Mock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        
        # Start connecting
        connect_task = asyncio.create_task(
            connection_manager.connect(mock_ws, 1, mock_user)
        )
        
        # Immediately try to disconnect
        disconnect_task = asyncio.create_task(
            asyncio.to_thread(connection_manager.disconnect, mock_ws, 1)
        )
        
        await asyncio.gather(connect_task, disconnect_task, return_exceptions=True)
        
        # Should handle race condition gracefully

    # Test memory and resource issues
    @pytest.mark.asyncio
    async def test_broadcast_memory_error(self, connection_manager, mock_user):
        """Test broadcast with memory allocation issues."""
        mock_ws = Mock(spec=WebSocket)
        mock_ws.send_text = AsyncMock(side_effect=MemoryError("Out of memory"))
        
        connection_manager.active_connections[1] = {mock_ws}
        connection_manager.user_connections[mock_ws] = mock_user
        
        await connection_manager.send_to_server_connections(1, {"message": "test message"})
        
        # Should handle gracefully and remove problematic connection
        assert mock_ws not in connection_manager.active_connections.get(1, set())

    @pytest.mark.asyncio
    async def test_send_large_message(self, connection_manager, mock_user):
        """Test sending very large message."""
        mock_ws = Mock(spec=WebSocket)
        large_message = "x" * (10 * 1024 * 1024)  # 10MB message
        mock_ws.send_text = AsyncMock(side_effect=OSError("Message too large"))
        
        connection_manager.active_connections[1] = {mock_ws}
        connection_manager.user_connections[mock_ws] = mock_user
        
        await connection_manager.send_to_server_connections(1, {"message": large_message})
        
        # Should handle gracefully
        assert mock_ws not in connection_manager.active_connections.get(1, set())

    # Test task cancellation scenarios
    @pytest.mark.asyncio
    async def test_log_streaming_task_cancellation(self, connection_manager, mock_user):
        """Test proper cleanup when log streaming task is cancelled."""
        mock_ws = Mock(spec=WebSocket)
        mock_ws.accept = AsyncMock()
        
        # Connect to start log streaming
        await connection_manager.connect(mock_ws, 1, mock_user)
        
        assert 1 in connection_manager.server_log_tasks
        
        # Disconnect should cancel the task
        connection_manager.disconnect(mock_ws, 1)
        
        # Task should be cancelled and removed
        assert 1 not in connection_manager.server_log_tasks

    @pytest.mark.asyncio
    async def test_multiple_server_log_streams(self, connection_manager, mock_user):
        """Test handling multiple server log streams."""
        # Connect to multiple servers
        for server_id in [1, 2, 3]:
            mock_ws = Mock(spec=WebSocket)
            mock_ws.accept = AsyncMock()
            await connection_manager.connect(mock_ws, server_id, mock_user)
        
        assert len(connection_manager.server_log_tasks) == 3
        
        # Get one of the mock websockets from server 2
        mock_ws2 = list(connection_manager.active_connections[2])[0]
        
        # Disconnect from one server
        connection_manager.disconnect(mock_ws2, 2)
        
        # Only that server's task should be cancelled
        assert 1 in connection_manager.server_log_tasks
        assert 2 not in connection_manager.server_log_tasks
        assert 3 in connection_manager.server_log_tasks

    # Test error recovery scenarios
    @pytest.mark.asyncio
    async def test_connection_recovery_after_failure(self, connection_manager, mock_user):
        """Test that manager can recover after connection failures."""
        mock_ws1 = Mock(spec=WebSocket)
        mock_ws1.accept = AsyncMock(side_effect=WebSocketDisconnect(code=1000))
        
        # First connection fails
        with pytest.raises(WebSocketDisconnect):
            await connection_manager.connect(mock_ws1, 1, mock_user)
        
        assert 1 not in connection_manager.active_connections
        
        # Second connection should work normally
        mock_ws2 = Mock(spec=WebSocket)
        mock_ws2.accept = AsyncMock()
        
        await connection_manager.connect(mock_ws2, 1, mock_user)
        
        assert 1 in connection_manager.active_connections
        assert mock_ws2 in connection_manager.active_connections[1]

    # Test JSON serialization failures
    @pytest.mark.asyncio
    async def test_broadcast_json_serialization_error(self, connection_manager, mock_user):
        """Test broadcast with non-serializable data."""
        mock_ws = Mock(spec=WebSocket)
        mock_ws.send_json = AsyncMock(side_effect=TypeError("Object is not JSON serializable"))
        
        connection_manager.active_connections[1] = {mock_ws}
        connection_manager.user_connections[mock_ws] = mock_user
        
        # Create object that can't be JSON serialized
        unserializable_data = {"key": object()}
        
        await connection_manager.send_to_server_connections(1, unserializable_data)
        
        # Should handle gracefully and remove problematic connection
        assert mock_ws not in connection_manager.active_connections.get(1, set())