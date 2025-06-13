"""Fixed comprehensive tests for WebSocket service matching actual implementation"""
import pytest
import asyncio
import json
from unittest.mock import Mock, patch, AsyncMock, MagicMock, mock_open
from datetime import datetime
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.services.websocket_service import (
    ConnectionManager,
    WebSocketService,
    websocket_service
)
from app.users.models import User, Role
from app.servers.models import Server, ServerStatus


class TestConnectionManagerFixed:
    """Fixed tests for WebSocket connection management"""
    
    @pytest.fixture
    def connection_manager(self):
        """Create connection manager instance"""
        return ConnectionManager()
    
    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket connection"""
        websocket = Mock(spec=WebSocket)
        websocket.send_text = AsyncMock()
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
        """Test successful user connection to server"""
        server_id = 1
        
        with patch('app.services.websocket_service.asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await connection_manager.connect(mock_websocket, server_id, mock_user)
            
            # Verify connection is stored
            assert server_id in connection_manager.active_connections
            assert mock_websocket in connection_manager.active_connections[server_id]
            
            # Verify user mapping
            assert mock_websocket in connection_manager.user_connections
            assert connection_manager.user_connections[mock_websocket] == mock_user
            
            # Verify log task was created
            assert server_id in connection_manager.server_log_tasks
            
            # Verify websocket accept was called
            mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_multiple_users_same_server(self, connection_manager, mock_user):
        """Test multiple users connecting to same server"""
        server_id = 1
        
        # First user
        ws1 = Mock(spec=WebSocket)
        ws1.accept = AsyncMock()
        user1 = Mock(spec=User)
        user1.username = "user1"
        
        # Second user  
        ws2 = Mock(spec=WebSocket)
        ws2.accept = AsyncMock()
        user2 = Mock(spec=User)
        user2.username = "user2"
        
        with patch('app.services.websocket_service.asyncio.create_task'):
            await connection_manager.connect(ws1, server_id, user1)
            await connection_manager.connect(ws2, server_id, user2)
            
            # Verify both connections exist for same server
            assert len(connection_manager.active_connections[server_id]) == 2
            assert ws1 in connection_manager.active_connections[server_id]
            assert ws2 in connection_manager.active_connections[server_id]
            
            # Verify user mappings
            assert connection_manager.user_connections[ws1] == user1
            assert connection_manager.user_connections[ws2] == user2

    def test_disconnect_existing_connection(self, connection_manager, mock_websocket, mock_user):
        """Test disconnecting existing connection"""
        server_id = 1
        
        # Setup connection first
        connection_manager.active_connections[server_id] = {mock_websocket}
        connection_manager.user_connections[mock_websocket] = mock_user
        
        # Mock log task
        mock_task = Mock()
        mock_task.cancel = Mock()
        connection_manager.server_log_tasks[server_id] = mock_task
        
        connection_manager.disconnect(mock_websocket, server_id)
        
        # Verify connection was removed
        assert server_id not in connection_manager.active_connections
        assert mock_websocket not in connection_manager.user_connections
        
        # Verify log task was cancelled
        mock_task.cancel.assert_called_once()
        assert server_id not in connection_manager.server_log_tasks

    def test_disconnect_nonexistent_connection(self, connection_manager, mock_websocket):
        """Test disconnecting connection that doesn't exist"""
        server_id = 999
        
        # Should not raise exception
        connection_manager.disconnect(mock_websocket, server_id)
        
        # State should remain clean
        assert connection_manager.active_connections == {}
        assert connection_manager.user_connections == {}

    @pytest.mark.asyncio
    async def test_send_to_server_connections_success(self, connection_manager):
        """Test sending message to server connections"""
        server_id = 1
        message = {"type": "test", "data": "hello"}
        
        # Setup connections
        ws1 = Mock(spec=WebSocket)
        ws1.send_text = AsyncMock()
        ws2 = Mock(spec=WebSocket)
        ws2.send_text = AsyncMock()
        
        connection_manager.active_connections[server_id] = {ws1, ws2}
        
        await connection_manager.send_to_server_connections(server_id, message)
        
        # Verify message sent to both connections
        expected_json = json.dumps(message)
        ws1.send_text.assert_called_once_with(expected_json)
        ws2.send_text.assert_called_once_with(expected_json)

    @pytest.mark.asyncio
    async def test_send_to_server_connections_with_failure(self, connection_manager):
        """Test sending message when one connection fails"""
        server_id = 1
        message = {"type": "test", "data": "hello"}
        
        # Setup connections - one will fail
        ws1 = Mock(spec=WebSocket)
        ws1.send_text = AsyncMock()
        ws2 = Mock(spec=WebSocket)
        ws2.send_text = AsyncMock(side_effect=Exception("Connection failed"))
        
        connection_manager.active_connections[server_id] = {ws1, ws2}
        connection_manager.user_connections[ws2] = Mock(username="user2")
        
        await connection_manager.send_to_server_connections(server_id, message)
        
        # Verify successful connection still got message
        ws1.send_text.assert_called_once()
        
        # Verify failed connection was removed
        assert ws2 not in connection_manager.active_connections[server_id]
        assert ws2 not in connection_manager.user_connections

    @pytest.mark.asyncio
    async def test_send_personal_message_success(self, connection_manager, mock_websocket):
        """Test sending personal message to websocket"""
        message = {"type": "personal", "data": "hello"}
        
        await connection_manager.send_personal_message(mock_websocket, message)
        
        expected_json = json.dumps(message)
        mock_websocket.send_text.assert_called_once_with(expected_json)

    @pytest.mark.asyncio
    async def test_send_personal_message_failure(self, connection_manager):
        """Test sending personal message when websocket fails"""
        ws = Mock(spec=WebSocket)
        ws.send_text = AsyncMock(side_effect=Exception("Send failed"))
        message = {"type": "personal", "data": "hello"}
        
        # Should not raise exception, just log error
        await connection_manager.send_personal_message(ws, message)
        
        ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_server_status(self, connection_manager):
        """Test broadcasting server status"""
        server_id = 1
        status = {"running": True, "players": 5}
        
        with patch.object(connection_manager, 'send_to_server_connections') as mock_send:
            await connection_manager.broadcast_server_status(server_id, status)
            
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == server_id
            
            message = args[1]
            assert message["type"] == "server_status"
            assert message["server_id"] == server_id
            assert message["data"] == status
            assert "timestamp" in message

    @pytest.mark.asyncio
    async def test_broadcast_server_notification(self, connection_manager):
        """Test broadcasting server notification"""
        server_id = 1
        notification = {"message": "Server restarted", "level": "info"}
        
        with patch.object(connection_manager, 'send_to_server_connections') as mock_send:
            await connection_manager.broadcast_server_notification(server_id, notification)
            
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == server_id
            
            message = args[1]
            assert message["type"] == "notification"
            assert message["server_id"] == server_id
            assert message["data"] == notification

    def test_determine_log_type_error_messages(self, connection_manager):
        """Test log type determination for error messages"""
        assert connection_manager._determine_log_type("[ERROR] Something went wrong") == "error"
        assert connection_manager._determine_log_type("Exception occurred") == "error"

    def test_determine_log_type_warning_messages(self, connection_manager):
        """Test log type determination for warning messages"""
        assert connection_manager._determine_log_type("[WARN] Deprecated feature") == "warning"
        assert connection_manager._determine_log_type("Warning: Low memory") == "warning"

    def test_determine_log_type_info_messages(self, connection_manager):
        """Test log type determination for info messages"""
        assert connection_manager._determine_log_type("[INFO] Server started") == "info"

    def test_determine_log_type_player_events(self, connection_manager):
        """Test log type determination for player events"""
        assert connection_manager._determine_log_type("Player123 joined the game") == "player_join"
        assert connection_manager._determine_log_type("Player123 left the game") == "player_leave"

    def test_determine_log_type_chat_messages(self, connection_manager):
        """Test log type determination for chat messages"""
        assert connection_manager._determine_log_type("<Player123> Hello world") == "chat"
        assert connection_manager._determine_log_type("Player chat message") == "chat"

    def test_determine_log_type_other_messages(self, connection_manager):
        """Test log type determination for other messages"""
        assert connection_manager._determine_log_type("Random server message") == "other"

    @pytest.mark.asyncio
    async def test_stream_server_logs_success(self, connection_manager):
        """Test streaming server logs"""
        server_id = 1
        log_content = "Test log line\nAnother log line\n"
        
        # Mock server manager
        mock_server_manager = Mock()
        mock_server_manager.server_dir = Path("/servers/test")
        
        # Setup active connections
        connection_manager.active_connections[server_id] = {Mock()}
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch('builtins.open', mock_open(read_data=log_content)) as mock_file, \
             patch.object(connection_manager, 'send_to_server_connections') as mock_send, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.is_file', return_value=True), \
             patch('asyncio.sleep', side_effect=asyncio.CancelledError()):
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            # Should be cancelled by sleep
            await connection_manager._stream_server_logs(server_id)
            
            # Verify server manager was retrieved
            mock_mgr.get_server.assert_called_once_with(str(server_id))


class TestWebSocketServiceFixed:
    """Fixed tests for WebSocket service"""
    
    @pytest.fixture
    def ws_service(self):
        """Create WebSocket service instance"""
        return WebSocketService()
    
    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket"""
        websocket = Mock(spec=WebSocket)
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.receive_text = AsyncMock()
        websocket.send_text = AsyncMock()
        return websocket

    def test_websocket_service_initialization(self, ws_service):
        """Test WebSocket service initializes correctly"""
        assert ws_service.connection_manager is not None
        assert isinstance(ws_service.connection_manager, ConnectionManager)
        assert ws_service._status_monitor_task is None

    @pytest.mark.asyncio
    async def test_start_monitoring_creates_task(self, ws_service):
        """Test starting monitoring creates background task"""
        with patch('asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await ws_service.start_monitoring()
            
            assert ws_service._status_monitor_task == mock_task
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_monitoring_already_running(self, ws_service):
        """Test starting monitoring when already running"""
        # Setup existing running task
        existing_task = Mock()
        existing_task.done.return_value = False
        ws_service._status_monitor_task = existing_task
        
        with patch('asyncio.create_task') as mock_create_task:
            await ws_service.start_monitoring()
            
            # Should not create new task
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_monitoring_cancels_task(self, ws_service):
        """Test stopping monitoring cancels the task"""
        # Create a mock task using create_task to ensure proper behavior
        async def dummy_coro():
            await asyncio.sleep(10)  # This will be cancelled
            
        mock_task = asyncio.create_task(dummy_coro())
        
        # Mock the done method to return False (task is running)
        original_done = mock_task.done
        mock_task.done = Mock(return_value=False)
        
        # Mock the cancel method to track calls but still call the real cancel
        original_cancel = mock_task.cancel
        mock_task.cancel = Mock(side_effect=original_cancel)
        
        ws_service._status_monitor_task = mock_task
        
        await ws_service.stop_monitoring()
        
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_connection_success(self, ws_service, mock_websocket):
        """Test successful WebSocket connection handling"""
        server_id = 1
        user = Mock(spec=User)
        user.username = "testuser"
        user.role = Role.user
        
        # Mock database and server
        db = Mock(spec=Session)
        server = Mock(spec=Server)
        server.id = server_id
        db.query.return_value.filter.return_value.first.return_value = server
        
        # Mock WebSocket disconnect after initial setup
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()
        
        with patch.object(ws_service.connection_manager, 'connect') as mock_connect, \
             patch.object(ws_service.connection_manager, 'disconnect') as mock_disconnect, \
             patch.object(ws_service, '_send_initial_status') as mock_initial_status:
            
            await ws_service.handle_connection(mock_websocket, server_id, user, db)
            
            # Verify connection was established and cleaned up
            mock_connect.assert_called_once_with(mock_websocket, server_id, user)
            mock_disconnect.assert_called_once_with(mock_websocket, server_id)
            mock_initial_status.assert_called_once_with(mock_websocket, server_id)

    @pytest.mark.asyncio
    async def test_handle_connection_server_not_found(self, ws_service, mock_websocket):
        """Test connection handling when server doesn't exist"""
        server_id = 999
        user = Mock(spec=User)
        
        # Mock database returning no server
        db = Mock(spec=Session)
        db.query.return_value.filter.return_value.first.return_value = None
        
        await ws_service.handle_connection(mock_websocket, server_id, user, db)
        
        # Verify websocket was closed
        mock_websocket.close.assert_called_once_with(code=1008, reason="Server not found")

    @pytest.mark.asyncio
    async def test_send_initial_status_success(self, ws_service, mock_websocket):
        """Test sending initial status to client"""
        server_id = 1
        mock_status = {"running": True, "players": 2}
        
        # Mock server manager
        mock_server_manager = Mock()
        mock_server_manager.get_status = AsyncMock(return_value=mock_status)
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch.object(ws_service.connection_manager, 'send_personal_message') as mock_send:
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            await ws_service._send_initial_status(mock_websocket, server_id)
            
            # Verify status was sent
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == mock_websocket
            
            message = args[1]
            assert message["type"] == "initial_status"
            assert message["server_id"] == server_id
            assert message["data"] == mock_status

    def test_global_service_instance(self):
        """Test the global service instance exists and is configured"""
        assert websocket_service is not None
        assert isinstance(websocket_service, WebSocketService)
        assert isinstance(websocket_service.connection_manager, ConnectionManager)