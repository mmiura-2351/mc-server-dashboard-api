"""Comprehensive tests for WebSocket service covering real-time communication"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch, mock_open

import pytest
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.servers.models import Server
from app.services.websocket_service import (
    ConnectionManager,
    WebSocketService,
    websocket_service
)
from app.users.models import User, Role


class TestConnectionManager:
    """Test ConnectionManager functionality"""
    
    @pytest.fixture
    def manager(self):
        """Create fresh ConnectionManager instance"""
        return ConnectionManager()
    
    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket"""
        websocket = AsyncMock(spec=WebSocket)
        websocket.accept = AsyncMock()
        websocket.send_text = AsyncMock()
        return websocket
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user"""
        user = Mock(spec=User)
        user.username = "testuser"
        user.role = Mock()
        user.role.value = "admin"
        return user
    
    @pytest.mark.asyncio
    async def test_connect_new_server(self, manager, mock_websocket, mock_user):
        """Test connecting to a new server"""
        server_id = 1
        
        with patch.object(manager, '_stream_server_logs') as mock_stream:
            mock_stream.return_value = AsyncMock()
            
            await manager.connect(mock_websocket, server_id, mock_user)
            
            mock_websocket.accept.assert_called_once()
            assert server_id in manager.active_connections
            assert mock_websocket in manager.active_connections[server_id]
            assert manager.user_connections[mock_websocket] is mock_user
            assert server_id in manager.server_log_tasks
    
    @pytest.mark.asyncio
    async def test_connect_existing_server(self, manager, mock_user):
        """Test connecting to an existing server with active connections"""
        server_id = 1
        websocket1 = AsyncMock(spec=WebSocket)
        websocket2 = AsyncMock(spec=WebSocket)
        
        # Mock existing connection
        manager.active_connections[server_id] = {websocket1}
        manager.server_log_tasks[server_id] = Mock()
        
        with patch.object(manager, '_stream_server_logs'):
            await manager.connect(websocket2, server_id, mock_user)
            
            assert len(manager.active_connections[server_id]) == 2
            assert websocket1 in manager.active_connections[server_id]
            assert websocket2 in manager.active_connections[server_id]
    
    def test_disconnect_last_connection(self, manager, mock_websocket, mock_user):
        """Test disconnecting the last connection for a server"""
        server_id = 1
        
        # Setup existing connection
        manager.active_connections[server_id] = {mock_websocket}
        manager.user_connections[mock_websocket] = mock_user
        
        # Mock log task
        mock_task = Mock()
        mock_task.cancel = Mock()
        manager.server_log_tasks[server_id] = mock_task
        
        manager.disconnect(mock_websocket, server_id)
        
        assert server_id not in manager.active_connections
        assert mock_websocket not in manager.user_connections
        assert server_id not in manager.server_log_tasks
        mock_task.cancel.assert_called_once()
    
    def test_disconnect_partial_connection(self, manager, mock_user):
        """Test disconnecting one of multiple connections"""
        server_id = 1
        websocket1 = Mock(spec=WebSocket)
        websocket2 = Mock(spec=WebSocket)
        
        # Setup multiple connections
        manager.active_connections[server_id] = {websocket1, websocket2}
        manager.user_connections[websocket1] = mock_user
        manager.user_connections[websocket2] = mock_user
        manager.server_log_tasks[server_id] = Mock()
        
        manager.disconnect(websocket1, server_id)
        
        assert server_id in manager.active_connections
        assert websocket1 not in manager.active_connections[server_id]
        assert websocket2 in manager.active_connections[server_id]
        assert websocket1 not in manager.user_connections
        assert websocket2 in manager.user_connections
        assert server_id in manager.server_log_tasks
    
    def test_disconnect_nonexistent_server(self, manager, mock_websocket, mock_user):
        """Test disconnecting from nonexistent server"""
        server_id = 999
        manager.user_connections[mock_websocket] = mock_user
        
        # Should not raise exception
        manager.disconnect(mock_websocket, server_id)
        
        assert mock_websocket not in manager.user_connections
    
    @pytest.mark.asyncio
    async def test_send_to_server_connections_success(self, manager):
        """Test sending message to server connections successfully"""
        server_id = 1
        websocket1 = AsyncMock(spec=WebSocket)
        websocket2 = AsyncMock(spec=WebSocket)
        
        manager.active_connections[server_id] = {websocket1, websocket2}
        
        message = {"type": "test", "data": "hello"}
        
        await manager.send_to_server_connections(server_id, message)
        
        websocket1.send_text.assert_called_once_with(json.dumps(message))
        websocket2.send_text.assert_called_once_with(json.dumps(message))
    
    @pytest.mark.asyncio
    async def test_send_to_server_connections_with_error(self, manager, mock_user):
        """Test sending message handles connection errors"""
        server_id = 1
        websocket1 = AsyncMock(spec=WebSocket)
        websocket2 = AsyncMock(spec=WebSocket)
        
        # Make one websocket fail
        websocket1.send_text.side_effect = Exception("Connection lost")
        
        manager.active_connections[server_id] = {websocket1, websocket2}
        manager.user_connections[websocket1] = mock_user
        
        message = {"type": "test", "data": "hello"}
        
        with patch.object(manager, 'disconnect') as mock_disconnect:
            await manager.send_to_server_connections(server_id, message)
            
            mock_disconnect.assert_called_once_with(websocket1, server_id)
            websocket2.send_text.assert_called_once_with(json.dumps(message))
    
    @pytest.mark.asyncio
    async def test_send_personal_message_success(self, manager, mock_websocket):
        """Test sending personal message successfully"""
        message = {"type": "personal", "data": "hello"}
        
        await manager.send_personal_message(mock_websocket, message)
        
        mock_websocket.send_text.assert_called_once_with(json.dumps(message))
    
    @pytest.mark.asyncio
    async def test_send_personal_message_error(self, manager, mock_websocket):
        """Test sending personal message handles errors"""
        mock_websocket.send_text.side_effect = Exception("Connection lost")
        
        message = {"type": "personal", "data": "hello"}
        
        # Should not raise exception
        await manager.send_personal_message(mock_websocket, message)
    
    @pytest.mark.asyncio
    async def test_broadcast_server_status(self, manager):
        """Test broadcasting server status"""
        server_id = 1
        status = {"running": True, "players": 5}
        
        with patch.object(manager, 'send_to_server_connections') as mock_send:
            await manager.broadcast_server_status(server_id, status)
            
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == server_id
            message = args[1]
            assert message["type"] == "server_status"
            assert message["server_id"] == server_id
            assert message["data"] == status
            assert "timestamp" in message
    
    @pytest.mark.asyncio
    async def test_broadcast_server_notification(self, manager):
        """Test broadcasting server notification"""
        server_id = 1
        notification = {"message": "Player joined", "player": "Steve"}
        
        with patch.object(manager, 'send_to_server_connections') as mock_send:
            await manager.broadcast_server_notification(server_id, notification)
            
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == server_id
            message = args[1]
            assert message["type"] == "notification"
            assert message["server_id"] == server_id
            assert message["data"] == notification
    
    def test_determine_log_type_error(self, manager):
        """Test log type determination for error messages"""
        assert manager._determine_log_type("[ERROR] Something went wrong") == "error"
        assert manager._determine_log_type("Exception in thread") == "error"
    
    def test_determine_log_type_warning(self, manager):
        """Test log type determination for warning messages"""
        assert manager._determine_log_type("[WARN] This is a warning") == "warning"
    
    def test_determine_log_type_info(self, manager):
        """Test log type determination for info messages"""
        assert manager._determine_log_type("[INFO] Server started") == "info"
    
    def test_determine_log_type_debug(self, manager):
        """Test log type determination for debug messages"""
        assert manager._determine_log_type("[DEBUG] Debug information") == "debug"
    
    def test_determine_log_type_player_events(self, manager):
        """Test log type determination for player events"""
        assert manager._determine_log_type("Steve joined the game") == "player_join"
        assert manager._determine_log_type("Alex left the game") == "player_leave"
    
    def test_determine_log_type_chat(self, manager):
        """Test log type determination for chat messages"""
        assert manager._determine_log_type("<Steve> Hello everyone!") == "chat"
        assert manager._determine_log_type("chat message from player") == "chat"
    
    def test_determine_log_type_other(self, manager):
        """Test log type determination for other messages"""
        assert manager._determine_log_type("Some random log message") == "other"


class TestStreamServerLogs:
    """Test log streaming functionality"""
    
    @pytest.fixture
    def manager(self):
        """Create fresh ConnectionManager instance"""
        return ConnectionManager()
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_no_server_manager(self, manager):
        """Test log streaming when server manager not found"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr:
            mock_mgr.get_server.return_value = None
            
            await manager._stream_server_logs(server_id)
            
            mock_mgr.get_server.assert_called_once_with(str(server_id))
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_invalid_server_manager(self, manager):
        """Test log streaming with invalid server manager"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_manager.server_dir = None
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr:
            mock_mgr.get_server.return_value = mock_server_manager
            
            await manager._stream_server_logs(server_id)
            
            # Should return early due to invalid server_dir
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_log_file_not_exists(self, manager):
        """Test log streaming when log file doesn't exist"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_dir = Mock()
        mock_log_file = Mock()
        mock_log_file.exists.return_value = False
        
        mock_server_dir.__truediv__ = Mock(return_value=mock_log_file)
        mock_server_manager.server_dir = mock_server_dir
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr:
            mock_mgr.get_server.return_value = mock_server_manager
            
            await manager._stream_server_logs(server_id)
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_file_is_not_file(self, manager):
        """Test log streaming when log path is not a file"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_dir = Mock()
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_log_file.is_file.return_value = False
        
        mock_server_dir.__truediv__ = Mock(return_value=mock_log_file)
        mock_server_manager.server_dir = mock_server_dir
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr:
            mock_mgr.get_server.return_value = mock_server_manager
            
            await manager._stream_server_logs(server_id)
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_successful_streaming(self, manager):
        """Test successful log streaming"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_dir = Mock()
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_log_file.is_file.return_value = True
        
        mock_server_dir.__truediv__ = Mock(return_value=mock_log_file)
        mock_server_manager.server_dir = mock_server_dir
        
        # Mock file content
        log_lines = ["[INFO] Server starting", "[ERROR] Something failed", ""]
        mock_file = mock_open()
        mock_file.return_value.readline.side_effect = log_lines
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch('builtins.open', mock_file), \
             patch.object(manager, 'send_to_server_connections') as mock_send, \
             patch('asyncio.sleep', side_effect=asyncio.CancelledError):
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            await manager._stream_server_logs(server_id)
            
            # Should send messages for non-empty lines
            assert mock_send.call_count == 2
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_cancellation(self, manager):
        """Test log streaming handles cancellation"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_dir = Mock()
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_log_file.is_file.return_value = True
        
        mock_server_dir.__truediv__ = Mock(return_value=mock_log_file)
        mock_server_manager.server_dir = mock_server_dir
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch('builtins.open', mock_open()), \
             patch('asyncio.sleep', side_effect=asyncio.CancelledError):
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            # Should not raise exception
            await manager._stream_server_logs(server_id)
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_file_not_found(self, manager):
        """Test log streaming handles FileNotFoundError"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_dir = Mock()
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_log_file.is_file.return_value = True
        
        mock_server_dir.__truediv__ = Mock(return_value=mock_log_file)
        mock_server_manager.server_dir = mock_server_dir
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch('builtins.open', side_effect=FileNotFoundError("File not found")):
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            # Should not raise exception
            await manager._stream_server_logs(server_id)
    
    @pytest.mark.asyncio
    async def test_stream_server_logs_permission_error(self, manager):
        """Test log streaming handles PermissionError"""
        server_id = 1
        manager.active_connections[server_id] = {Mock()}
        
        mock_server_manager = Mock()
        mock_server_dir = Mock()
        mock_log_file = Mock()
        mock_log_file.exists.return_value = True
        mock_log_file.is_file.return_value = True
        
        mock_server_dir.__truediv__ = Mock(return_value=mock_log_file)
        mock_server_manager.server_dir = mock_server_dir
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch('builtins.open', side_effect=PermissionError("Permission denied")):
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            # Should not raise exception
            await manager._stream_server_logs(server_id)


class TestWebSocketService:
    """Test WebSocketService functionality"""
    
    @pytest.fixture
    def service(self):
        """Create fresh WebSocketService instance"""
        return WebSocketService()
    
    @pytest.mark.asyncio
    async def test_start_monitoring_new_task(self, service):
        """Test starting monitoring creates new task"""
        with patch('asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await service.start_monitoring()
            
            assert service._status_monitor_task is mock_task
            mock_create_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_start_monitoring_existing_done_task(self, service):
        """Test starting monitoring when existing task is done"""
        old_task = Mock()
        old_task.done.return_value = True
        service._status_monitor_task = old_task
        
        with patch('asyncio.create_task') as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await service.start_monitoring()
            
            assert service._status_monitor_task is mock_task
    
    @pytest.mark.asyncio
    async def test_start_monitoring_existing_running_task(self, service):
        """Test starting monitoring when task is already running"""
        running_task = Mock()
        running_task.done.return_value = False
        service._status_monitor_task = running_task
        
        with patch('asyncio.create_task') as mock_create_task:
            await service.start_monitoring()
            
            # Should not create new task
            mock_create_task.assert_not_called()
            assert service._status_monitor_task is running_task
    
    @pytest.mark.asyncio
    async def test_stop_monitoring_with_task(self, service):
        """Test stopping monitoring with active task"""
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        mock_task.cancel = Mock()
        service._status_monitor_task = mock_task
        
        await service.stop_monitoring()
        
        mock_task.cancel.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stop_monitoring_with_done_task(self, service):
        """Test stopping monitoring with done task"""
        mock_task = Mock()
        mock_task.done.return_value = True
        service._status_monitor_task = mock_task
        
        await service.stop_monitoring()
        
        # Should not try to cancel done task
        assert not hasattr(mock_task, 'cancel') or not mock_task.cancel.called
    
    @pytest.mark.asyncio
    async def test_stop_monitoring_no_task(self, service):
        """Test stopping monitoring with no task"""
        service._status_monitor_task = None
        
        # Should not raise exception
        await service.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_handle_connection_server_not_found(self, service):
        """Test handling connection when server not found"""
        websocket = AsyncMock(spec=WebSocket)
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_db.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = None
        
        await service.handle_connection(websocket, 999, mock_user, mock_db)
        
        websocket.close.assert_called_once_with(code=1008, reason="Server not found")
    
    @pytest.mark.asyncio
    async def test_handle_connection_success(self, service):
        """Test successful connection handling"""
        websocket = AsyncMock(spec=WebSocket)
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        mock_server = Mock(spec=Server)
        mock_server.id = 1
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_db.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = mock_server
        
        # Mock WebSocket receive to trigger disconnect
        websocket.receive_text.side_effect = WebSocketDisconnect()
        
        with patch.object(service.connection_manager, 'connect') as mock_connect, \
             patch.object(service, '_send_initial_status') as mock_initial, \
             patch.object(service.connection_manager, 'disconnect') as mock_disconnect:
            
            await service.handle_connection(websocket, 1, mock_user, mock_db)
            
            mock_connect.assert_called_once_with(websocket, 1, mock_user)
            mock_initial.assert_called_once_with(websocket, 1)
            mock_disconnect.assert_called_once_with(websocket, 1)
    
    @pytest.mark.asyncio
    async def test_handle_connection_error(self, service):
        """Test connection handling with error"""
        websocket = AsyncMock(spec=WebSocket)
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        mock_server = Mock(spec=Server)
        mock_server.id = 1
        
        query_mock = Mock()
        filter_mock = Mock()
        mock_db.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.first.return_value = mock_server
        
        websocket.receive_text.side_effect = Exception("Connection error")
        
        with patch.object(service.connection_manager, 'connect'), \
             patch.object(service, '_send_initial_status'), \
             patch.object(service.connection_manager, 'disconnect') as mock_disconnect:
            
            await service.handle_connection(websocket, 1, mock_user, mock_db)
            
            mock_disconnect.assert_called_once_with(websocket, 1)


class TestWebSocketServiceHelpers:
    """Test WebSocket service helper methods"""
    
    @pytest.fixture
    def service(self):
        """Create fresh WebSocketService instance"""
        return WebSocketService()
    
    @pytest.mark.asyncio
    async def test_send_initial_status_success(self, service):
        """Test sending initial status successfully"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        
        mock_server_manager = AsyncMock()
        mock_status = {"running": True, "players": 3}
        mock_server_manager.get_status.return_value = mock_status
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr, \
             patch.object(service.connection_manager, 'send_personal_message') as mock_send:
            
            mock_mgr.get_server.return_value = mock_server_manager
            
            await service._send_initial_status(websocket, server_id)
            
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] is websocket
            message = args[1]
            assert message["type"] == "initial_status"
            assert message["server_id"] == server_id
            assert message["data"] == mock_status
    
    @pytest.mark.asyncio
    async def test_send_initial_status_no_server_manager(self, service):
        """Test sending initial status when server manager not found"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr:
            mock_mgr.get_server.return_value = None
            
            # Should not raise exception
            await service._send_initial_status(websocket, server_id)
    
    @pytest.mark.asyncio
    async def test_send_initial_status_invalid_server_manager(self, service):
        """Test sending initial status with invalid server manager"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        
        mock_server_manager = Mock()  # Missing get_status method
        
        with patch('app.services.websocket_service.minecraft_server_manager') as mock_mgr:
            mock_mgr.get_server.return_value = mock_server_manager
            
            # Should not raise exception
            await service._send_initial_status(websocket, server_id)
    
    @pytest.mark.asyncio
    async def test_handle_message_ping(self, service):
        """Test handling ping message"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        user = Mock(spec=User)
        db = Mock(spec=Session)
        
        message = {"type": "ping"}
        
        with patch.object(service.connection_manager, 'send_personal_message') as mock_send:
            await service._handle_message(websocket, server_id, message, user, db)
            
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] is websocket
            response = args[1]
            assert response["type"] == "pong"
            assert "timestamp" in response
    
    @pytest.mark.asyncio
    async def test_handle_message_send_command_admin(self, service):
        """Test handling send_command message as admin"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        user = Mock(spec=User)
        user.role.value = "admin"
        db = Mock(spec=Session)
        
        message = {"type": "send_command", "command": "say Hello"}
        
        with patch.object(service, '_send_server_command') as mock_send_cmd:
            await service._handle_message(websocket, server_id, message, user, db)
            
            mock_send_cmd.assert_called_once_with(server_id, "say Hello", user)
    
    @pytest.mark.asyncio
    async def test_handle_message_send_command_operator(self, service):
        """Test handling send_command message as operator"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        user = Mock(spec=User)
        user.role.value = "operator"
        db = Mock(spec=Session)
        
        message = {"type": "send_command", "command": "list"}
        
        with patch.object(service, '_send_server_command') as mock_send_cmd:
            await service._handle_message(websocket, server_id, message, user, db)
            
            mock_send_cmd.assert_called_once_with(server_id, "list", user)
    
    @pytest.mark.asyncio
    async def test_handle_message_send_command_user_denied(self, service):
        """Test handling send_command message as regular user (denied)"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        user = Mock(spec=User)
        user.role.value = "user"
        db = Mock(spec=Session)
        
        message = {"type": "send_command", "command": "op player"}
        
        with patch.object(service, '_send_server_command') as mock_send_cmd:
            await service._handle_message(websocket, server_id, message, user, db)
            
            mock_send_cmd.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_message_request_status(self, service):
        """Test handling request_status message"""
        websocket = AsyncMock(spec=WebSocket)
        server_id = 1
        user = Mock(spec=User)
        db = Mock(spec=Session)
        
        message = {"type": "request_status"}
        
        with patch.object(service, '_send_initial_status') as mock_send_status:
            await service._handle_message(websocket, server_id, message, user, db)
            
            mock_send_status.assert_called_once_with(websocket, server_id)


class TestGlobalWebSocketService:
    """Test global WebSocket service instance"""
    
    def test_global_service_exists(self):
        """Test global websocket_service exists"""
        assert websocket_service is not None
        assert isinstance(websocket_service, WebSocketService)
    
    def test_global_service_has_connection_manager(self):
        """Test global service has connection manager"""
        assert websocket_service.connection_manager is not None
        assert isinstance(websocket_service.connection_manager, ConnectionManager)