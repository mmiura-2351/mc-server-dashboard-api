"""Comprehensive tests for WebSocket service with actual functionality testing"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime
from typing import Dict, Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.services.websocket_service import (
    ConnectionManager,
    WebSocketService,
    websocket_service
)
from app.users.models import User, Role
from app.servers.models import Server, ServerStatus


class TestConnectionManagerComprehensive:
    """Comprehensive tests for WebSocket connection management"""
    
    @pytest.fixture
    def connection_manager(self):
        """Create connection manager instance"""
        return ConnectionManager()
    
    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket connection"""
        websocket = Mock(spec=WebSocket)
        websocket.send_text = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        return websocket
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user"""
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.role = Role.user
        return user

    def test_connection_manager_initialization(self, connection_manager):
        """Test connection manager initializes with empty state"""
        assert connection_manager.active_connections == {}
        assert connection_manager.user_connections == {}
        assert connection_manager.server_log_tasks == {}

    @pytest.mark.asyncio
    async def test_connect_user_success(self, connection_manager, mock_websocket, mock_user):
        """Test successful user connection"""
        connection_id = "conn_1"
        
        await connection_manager.connect(connection_id, mock_websocket, mock_user)
        
        # Verify connection is stored
        assert connection_id in connection_manager.active_connections
        assert connection_manager.active_connections[connection_id]["websocket"] == mock_websocket
        assert connection_manager.active_connections[connection_id]["user"] == mock_user
        
        # Verify user mapping
        assert mock_user.id in connection_manager.user_connections
        assert connection_id in connection_manager.user_connections[mock_user.id]
        
        # Verify websocket accept was called
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_multiple_users(self, connection_manager, mock_user):
        """Test connecting multiple users"""
        # First user
        ws1 = Mock(spec=WebSocket)
        ws1.accept = AsyncMock()
        user1 = Mock(spec=User)
        user1.id = 1
        
        # Second user  
        ws2 = Mock(spec=WebSocket)
        ws2.accept = AsyncMock()
        user2 = Mock(spec=User)
        user2.id = 2
        
        await connection_manager.connect("conn_1", ws1, user1)
        await connection_manager.connect("conn_2", ws2, user2)
        
        # Verify both connections exist
        assert len(connection_manager.active_connections) == 2
        assert len(connection_manager.user_connections) == 2
        assert user1.id in connection_manager.user_connections
        assert user2.id in connection_manager.user_connections

    @pytest.mark.asyncio
    async def test_connect_same_user_multiple_connections(self, connection_manager, mock_user):
        """Test same user with multiple connections"""
        ws1 = Mock(spec=WebSocket)
        ws1.accept = AsyncMock()
        ws2 = Mock(spec=WebSocket)
        ws2.accept = AsyncMock()
        
        await connection_manager.connect("conn_1", ws1, mock_user)
        await connection_manager.connect("conn_2", ws2, mock_user)
        
        # Verify both connections for same user
        assert len(connection_manager.active_connections) == 2
        assert len(connection_manager.user_connections[mock_user.id]) == 2
        assert "conn_1" in connection_manager.user_connections[mock_user.id]
        assert "conn_2" in connection_manager.user_connections[mock_user.id]

    def test_disconnect_existing_connection(self, connection_manager, mock_websocket, mock_user):
        """Test disconnecting existing connection"""
        connection_id = "conn_1"
        
        # Setup connection manually for testing
        connection_manager.active_connections[connection_id] = {
            "websocket": mock_websocket,
            "user": mock_user
        }
        connection_manager.user_connections[mock_user.id] = {connection_id}
        
        connection_manager.disconnect(connection_id)
        
        # Verify connection is removed
        assert connection_id not in connection_manager.active_connections
        assert mock_user.id not in connection_manager.user_connections

    def test_disconnect_nonexistent_connection(self, connection_manager):
        """Test disconnecting nonexistent connection doesn't crash"""
        # Should not raise exception
        connection_manager.disconnect("nonexistent")
        
        # State should remain empty
        assert connection_manager.active_connections == {}
        assert connection_manager.user_connections == {}

    def test_disconnect_partial_cleanup_scenario(self, connection_manager):
        """Test disconnect handles partial cleanup scenarios"""
        connection_id = "conn_1"
        user_id = 1
        
        # Setup partial state (connection exists but user mapping doesn't)
        connection_manager.active_connections[connection_id] = {
            "websocket": Mock(),
            "user": Mock(id=user_id)
        }
        # Intentionally don't set user_connections to test robustness
        
        # Should not crash
        connection_manager.disconnect(connection_id)
        
        # Connection should be cleaned up
        assert connection_id not in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_send_personal_message_success(self, connection_manager, mock_websocket, mock_user):
        """Test sending personal message to specific user"""
        connection_id = "conn_1"
        connection_manager.active_connections[connection_id] = {
            "websocket": mock_websocket,
            "user": mock_user
        }
        connection_manager.user_connections[mock_user.id] = {connection_id}
        
        message = {"type": "notification", "content": "Hello"}
        
        await connection_manager.send_personal_message(mock_user.id, message)
        
        # Verify message was sent to user's websocket
        mock_websocket.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_personal_message_multiple_connections(self, connection_manager):
        """Test sending message to user with multiple connections"""
        user_id = 1
        
        # Setup multiple connections for same user
        ws1 = Mock(spec=WebSocket)
        ws1.send_json = AsyncMock()
        ws2 = Mock(spec=WebSocket) 
        ws2.send_json = AsyncMock()
        
        user = Mock(id=user_id)
        
        connection_manager.active_connections["conn_1"] = {"websocket": ws1, "user": user}
        connection_manager.active_connections["conn_2"] = {"websocket": ws2, "user": user}
        connection_manager.user_connections[user_id] = {"conn_1", "conn_2"}
        
        message = {"type": "broadcast", "content": "Hello all"}
        
        await connection_manager.send_personal_message(user_id, message)
        
        # Both websockets should receive the message
        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_personal_message_connection_error(self, connection_manager):
        """Test handling connection errors during message sending"""
        user_id = 1
        connection_id = "conn_1"
        
        # Setup websocket that will fail
        failed_ws = Mock(spec=WebSocket)
        failed_ws.send_json = AsyncMock(side_effect=Exception("Connection lost"))
        
        user = Mock(id=user_id)
        connection_manager.active_connections[connection_id] = {
            "websocket": failed_ws,
            "user": user
        }
        connection_manager.user_connections[user_id] = {connection_id}
        
        message = {"type": "test", "content": "test"}
        
        # Should not raise exception, should handle gracefully
        await connection_manager.send_personal_message(user_id, message)
        
        # Connection should be cleaned up after failure
        assert connection_id not in connection_manager.active_connections
        assert user_id not in connection_manager.user_connections

    @pytest.mark.asyncio
    async def test_send_personal_message_user_not_connected(self, connection_manager):
        """Test sending message to user who is not connected"""
        # Should not raise exception
        await connection_manager.send_personal_message(999, {"test": "message"})
        
        # No changes to connection state
        assert connection_manager.active_connections == {}

    @pytest.mark.asyncio
    async def test_broadcast_message_to_all_users(self, connection_manager):
        """Test broadcasting message to all connected users"""
        # Setup multiple users
        ws1 = Mock(spec=WebSocket)
        ws1.send_json = AsyncMock()
        ws2 = Mock(spec=WebSocket)
        ws2.send_json = AsyncMock()
        
        user1 = Mock(id=1)
        user2 = Mock(id=2)
        
        connection_manager.active_connections["conn_1"] = {"websocket": ws1, "user": user1}
        connection_manager.active_connections["conn_2"] = {"websocket": ws2, "user": user2}
        
        message = {"type": "system", "content": "Server maintenance"}
        
        await connection_manager.broadcast(message)
        
        # All websockets should receive the message
        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_message_with_failed_connections(self, connection_manager):
        """Test broadcast handling some failed connections"""
        # Setup one working and one failing connection
        working_ws = Mock(spec=WebSocket)
        working_ws.send_json = AsyncMock()
        
        failing_ws = Mock(spec=WebSocket)
        failing_ws.send_json = AsyncMock(side_effect=Exception("Connection failed"))
        
        user1 = Mock(id=1)
        user2 = Mock(id=2)
        
        connection_manager.active_connections["conn_1"] = {"websocket": working_ws, "user": user1}
        connection_manager.active_connections["conn_2"] = {"websocket": failing_ws, "user": user2}
        connection_manager.user_connections[1] = {"conn_1"}
        connection_manager.user_connections[2] = {"conn_2"}
        
        message = {"type": "broadcast", "content": "test"}
        
        await connection_manager.broadcast(message)
        
        # Working connection should receive message
        working_ws.send_json.assert_called_once_with(message)
        
        # Failed connection should be cleaned up
        assert "conn_2" not in connection_manager.active_connections
        assert 2 not in connection_manager.user_connections

    def test_determine_log_type_error_messages(self, connection_manager):
        """Test log type determination for error messages"""
        assert connection_manager._determine_log_type("[ERROR] Something failed") == "error"
        assert connection_manager._determine_log_type("[SEVERE] Critical error") == "error"
        assert connection_manager._determine_log_type("ERROR: Database connection lost") == "error"

    def test_determine_log_type_warning_messages(self, connection_manager):
        """Test log type determination for warning messages"""
        assert connection_manager._determine_log_type("[WARN] Low memory") == "warning"
        assert connection_manager._determine_log_type("[WARNING] Deprecated API") == "warning"
        assert connection_manager._determine_log_type("WARN: Performance issue") == "warning"

    def test_determine_log_type_info_messages(self, connection_manager):
        """Test log type determination for info messages"""
        assert connection_manager._determine_log_type("[INFO] Server started") == "info"
        assert connection_manager._determine_log_type("INFO: Configuration loaded") == "info"

    def test_determine_log_type_player_events(self, connection_manager):
        """Test log type determination for player events"""
        assert connection_manager._determine_log_type("Steve joined the game") == "player_join"
        assert connection_manager._determine_log_type("Alex left the game") == "player_leave"
        assert connection_manager._determine_log_type("Player123 left the game") == "player_leave"

    def test_determine_log_type_chat_messages(self, connection_manager):
        """Test log type determination for chat messages"""
        assert connection_manager._determine_log_type("<Player> Hello everyone!") == "chat"
        assert connection_manager._determine_log_type("<Steve> How are you?") == "chat"

    def test_determine_log_type_other_messages(self, connection_manager):
        """Test log type determination for other messages"""
        assert connection_manager._determine_log_type("Random server message") == "other"
        assert connection_manager._determine_log_type("Saving world...") == "other"

    @pytest.mark.asyncio
    async def test_start_server_log_streaming(self, connection_manager):
        """Test starting server log streaming"""
        server_id = 1
        
        with patch('app.services.websocket_service.asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await connection_manager.start_server_log_streaming(server_id)
            
            # Verify task was created and stored
            assert server_id in connection_manager.server_log_tasks
            assert connection_manager.server_log_tasks[server_id] == mock_task
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_server_log_streaming_already_running(self, connection_manager):
        """Test starting log streaming when already running"""
        server_id = 1
        existing_task = Mock()
        existing_task.cancelled.return_value = False
        connection_manager.server_log_tasks[server_id] = existing_task
        
        with patch('app.services.websocket_service.asyncio.create_task') as mock_create_task:
            await connection_manager.start_server_log_streaming(server_id)
            
            # Should not create new task since one exists
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_server_log_streaming(self, connection_manager):
        """Test stopping server log streaming"""
        server_id = 1
        mock_task = Mock()
        mock_task.cancel = Mock()
        connection_manager.server_log_tasks[server_id] = mock_task
        
        await connection_manager.stop_server_log_streaming(server_id)
        
        # Verify task was cancelled and removed
        mock_task.cancel.assert_called_once()
        assert server_id not in connection_manager.server_log_tasks

    @pytest.mark.asyncio
    async def test_stop_server_log_streaming_not_running(self, connection_manager):
        """Test stopping log streaming when not running"""
        # Should not raise exception
        await connection_manager.stop_server_log_streaming(999)
        
        # No change to state
        assert connection_manager.server_log_tasks == {}


class TestWebSocketServiceComprehensive:
    """Comprehensive tests for WebSocket service functionality"""
    
    @pytest.fixture
    def websocket_service(self):
        """Create WebSocket service instance"""
        return WebSocketService()
    
    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session"""
        return Mock(spec=Session)

    def test_websocket_service_initialization(self, websocket_service):
        """Test WebSocket service initialization"""
        assert websocket_service.connection_manager is not None
        assert isinstance(websocket_service.connection_manager, ConnectionManager)
        assert websocket_service._status_monitor_task is None

    @pytest.mark.asyncio
    async def test_start_monitoring_creates_task(self, websocket_service):
        """Test start monitoring creates background task"""
        with patch('app.services.websocket_service.asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await websocket_service.start_monitoring()
            
            # Verify task was created and stored
            assert websocket_service._status_monitor_task == mock_task
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_monitoring_already_running(self, websocket_service):
        """Test start monitoring when already running"""
        existing_task = Mock()
        existing_task.cancelled.return_value = False
        websocket_service._status_monitor_task = existing_task
        
        with patch('app.services.websocket_service.asyncio.create_task') as mock_create_task:
            await websocket_service.start_monitoring()
            
            # Should not create new task
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_monitoring_cancels_task(self, websocket_service):
        """Test stop monitoring cancels existing task"""
        mock_task = Mock()
        mock_task.cancel = Mock()
        websocket_service._status_monitor_task = mock_task
        
        await websocket_service.stop_monitoring()
        
        # Verify task was cancelled and cleared
        mock_task.cancel.assert_called_once()
        assert websocket_service._status_monitor_task is None

    @pytest.mark.asyncio
    async def test_stop_monitoring_no_task(self, websocket_service):
        """Test stop monitoring when no task exists"""
        # Should not raise exception
        await websocket_service.stop_monitoring()
        
        # Should remain None
        assert websocket_service._status_monitor_task is None

    @pytest.mark.asyncio
    async def test_notify_server_status_change(self, websocket_service):
        """Test notifying users of server status changes"""
        server_id = 1
        new_status = ServerStatus.running
        
        with patch.object(websocket_service.connection_manager, 'broadcast') as mock_broadcast:
            await websocket_service.notify_server_status_change(server_id, new_status)
            
            # Verify broadcast was called with correct message
            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args[0][0]
            assert call_args["type"] == "server_status_update"
            assert call_args["server_id"] == server_id
            assert call_args["status"] == new_status.value

    @pytest.mark.asyncio
    async def test_notify_backup_progress(self, websocket_service):
        """Test notifying users of backup progress"""
        backup_id = 1
        progress_data = {"progress": 50, "status": "in_progress"}
        
        with patch.object(websocket_service.connection_manager, 'broadcast') as mock_broadcast:
            await websocket_service.notify_backup_progress(backup_id, progress_data)
            
            # Verify broadcast was called with correct message
            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args[0][0]
            assert call_args["type"] == "backup_progress"
            assert call_args["backup_id"] == backup_id
            assert call_args["progress"] == progress_data

    @pytest.mark.asyncio
    async def test_send_user_notification(self, websocket_service):
        """Test sending notification to specific user"""
        user_id = 1
        notification = {"message": "Server maintenance scheduled"}
        
        with patch.object(websocket_service.connection_manager, 'send_personal_message') as mock_send:
            await websocket_service.send_user_notification(user_id, notification)
            
            # Verify personal message was sent
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == user_id
            message = call_args[0][1]
            assert message["type"] == "notification"
            assert message["data"] == notification

    @pytest.mark.asyncio
    async def test_get_server_metrics_with_valid_server(self, websocket_service, mock_db_session):
        """Test getting server metrics for valid server"""
        server_id = 1
        
        # Mock server exists in database
        mock_server = Mock()
        mock_server.id = server_id
        mock_server.status = ServerStatus.running
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_server
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_manager:
            mock_metrics = {
                "cpu_usage": 25.5,
                "memory_usage": 512,
                "player_count": 3,
                "uptime": 3600
            }
            mock_manager.get_server_info.return_value = mock_metrics
            
            result = await websocket_service.get_server_metrics(server_id, mock_db_session)
            
            # Verify result includes both database and runtime info
            assert result["server_id"] == server_id
            assert result["status"] == ServerStatus.running.value
            assert result["metrics"] == mock_metrics

    @pytest.mark.asyncio
    async def test_get_server_metrics_server_not_found(self, websocket_service, mock_db_session):
        """Test getting metrics for non-existent server"""
        server_id = 999
        
        # Mock server not found
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        result = await websocket_service.get_server_metrics(server_id, mock_db_session)
        
        # Should return None for non-existent server
        assert result is None

    @pytest.mark.asyncio
    async def test_get_server_metrics_runtime_error(self, websocket_service, mock_db_session):
        """Test getting metrics when runtime info fails"""
        server_id = 1
        
        # Mock server exists
        mock_server = Mock()
        mock_server.id = server_id
        mock_server.status = ServerStatus.running
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_server
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_manager:
            mock_manager.get_server_info.side_effect = Exception("Runtime error")
            
            result = await websocket_service.get_server_metrics(server_id, mock_db_session)
            
            # Should return basic info without runtime metrics
            assert result["server_id"] == server_id
            assert result["status"] == ServerStatus.running.value
            assert result["metrics"] is None

    def test_get_connection_stats(self, websocket_service):
        """Test getting connection statistics"""
        # Setup some mock connections
        manager = websocket_service.connection_manager
        manager.active_connections = {
            "conn_1": {"user": Mock(id=1)},
            "conn_2": {"user": Mock(id=2)},
            "conn_3": {"user": Mock(id=1)},  # Same user, different connection
        }
        manager.user_connections = {
            1: {"conn_1", "conn_3"},
            2: {"conn_2"}
        }
        
        stats = websocket_service.get_connection_stats()
        
        # Verify statistics
        assert stats["total_connections"] == 3
        assert stats["unique_users"] == 2
        assert stats["connections_per_user"] == {1: 2, 2: 1}

    def test_get_connection_stats_empty(self, websocket_service):
        """Test getting connection statistics when no connections"""
        stats = websocket_service.get_connection_stats()
        
        # Should return empty stats
        assert stats["total_connections"] == 0
        assert stats["unique_users"] == 0
        assert stats["connections_per_user"] == {}


class TestWebSocketServiceIntegration:
    """Integration tests for WebSocket service"""
    
    def test_global_service_instance_configuration(self):
        """Test global service instance is properly configured"""
        # Verify global instance exists
        assert websocket_service is not None
        assert isinstance(websocket_service, WebSocketService)
        
        # Verify it has connection manager
        assert websocket_service.connection_manager is not None
        assert isinstance(websocket_service.connection_manager, ConnectionManager)

    @pytest.mark.asyncio
    async def test_service_lifecycle_management(self):
        """Test service can be started and stopped properly"""
        service = WebSocketService()
        
        # Start service
        await service.start_monitoring()
        assert service._status_monitor_task is not None
        
        # Stop service
        await service.stop_monitoring()
        assert service._status_monitor_task is None

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test service handles concurrent operations"""
        service = WebSocketService()
        
        # Setup multiple mock operations
        async def mock_operation(delay: float, operation_id: int):
            await asyncio.sleep(delay)
            await service.notify_server_status_change(operation_id, ServerStatus.running)
        
        # Run operations concurrently
        with patch.object(service.connection_manager, 'broadcast') as mock_broadcast:
            operations = [
                mock_operation(0.01, 1),
                mock_operation(0.02, 2),
                mock_operation(0.01, 3),
            ]
            
            await asyncio.gather(*operations)
            
            # All operations should have completed
            assert mock_broadcast.call_count == 3

    @pytest.mark.asyncio
    async def test_error_handling_in_background_tasks(self):
        """Test error handling in background monitoring tasks"""
        service = WebSocketService()
        
        with patch('app.services.websocket_service.asyncio.create_task') as mock_create_task:
            # Mock task that will raise exception
            failing_task = AsyncMock()
            failing_task.side_effect = Exception("Background task failed")
            mock_create_task.return_value = failing_task
            
            # Should not raise exception during start
            await service.start_monitoring()
            
            # Task should still be set despite potential future failure
            assert service._status_monitor_task == failing_task