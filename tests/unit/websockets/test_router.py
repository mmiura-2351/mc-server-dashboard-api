"""
Comprehensive test coverage for WebSocket router
Tests WebSocket endpoints and error handling
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, WebSocket

from app.users.models import Role, User
from app.websockets.router import (
    websocket_notifications,
    websocket_server_logs,
    websocket_server_status,
)


class TestWebSocketRouter:
    """Test cases for WebSocket router endpoints"""

    @pytest.fixture
    def mock_websocket(self):
        """Create mock WebSocket"""
        websocket = Mock(spec=WebSocket)
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.receive_text = AsyncMock()
        return websocket

    @pytest.fixture
    def mock_user(self):
        """Create mock user"""
        user = Mock(spec=User)
        user.id = 1
        user.username = "testuser"
        user.role = Role.user
        return user

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session"""
        return Mock()

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.websocket_service")
    async def test_websocket_server_logs_success(
        self, mock_ws_service, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test successful WebSocket server logs connection"""
        mock_auth.return_value = mock_user
        mock_ws_service.handle_connection = AsyncMock()

        await websocket_server_logs(
            websocket=mock_websocket, server_id=1, token="valid-token", db=mock_db_session
        )

        mock_auth.assert_called_once_with("valid-token", mock_db_session)
        mock_ws_service.handle_connection.assert_called_once_with(
            mock_websocket, 1, mock_user, mock_db_session
        )

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    async def test_websocket_server_logs_auth_error(
        self, mock_auth, mock_websocket, mock_db_session
    ):
        """Test WebSocket server logs with authentication error"""
        mock_auth.side_effect = HTTPException(status_code=401, detail="Unauthorized")

        await websocket_server_logs(
            websocket=mock_websocket,
            server_id=1,
            token="invalid-token",
            db=mock_db_session,
        )

        mock_websocket.close.assert_called_once_with(code=1008, reason="Unauthorized")

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.websocket_service")
    async def test_websocket_server_logs_internal_error(
        self, mock_ws_service, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test WebSocket server logs with internal error"""
        mock_auth.return_value = mock_user
        mock_ws_service.handle_connection.side_effect = Exception("Internal error")

        await websocket_server_logs(
            websocket=mock_websocket, server_id=1, token="valid-token", db=mock_db_session
        )

        mock_websocket.close.assert_called_once_with(
            code=1011, reason="Internal error: Internal error"
        )

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.websocket_service")
    async def test_websocket_server_status_success(
        self, mock_ws_service, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test successful WebSocket server status connection"""
        mock_auth.return_value = mock_user
        mock_ws_service.handle_connection = AsyncMock()

        await websocket_server_status(
            websocket=mock_websocket, server_id=2, token="valid-token", db=mock_db_session
        )

        mock_auth.assert_called_once_with("valid-token", mock_db_session)
        mock_ws_service.handle_connection.assert_called_once_with(
            mock_websocket, 2, mock_user, mock_db_session
        )

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    async def test_websocket_server_status_auth_error(
        self, mock_auth, mock_websocket, mock_db_session
    ):
        """Test WebSocket server status with authentication error"""
        mock_auth.side_effect = HTTPException(status_code=403, detail="Access denied")

        await websocket_server_status(
            websocket=mock_websocket,
            server_id=2,
            token="invalid-token",
            db=mock_db_session,
        )

        mock_websocket.close.assert_called_once_with(code=1008, reason="Access denied")

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.websocket_service")
    async def test_websocket_server_status_internal_error(
        self, mock_ws_service, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test WebSocket server status with internal error"""
        mock_auth.return_value = mock_user
        mock_ws_service.handle_connection.side_effect = Exception("Service error")

        await websocket_server_status(
            websocket=mock_websocket, server_id=2, token="valid-token", db=mock_db_session
        )

        mock_websocket.close.assert_called_once_with(
            code=1011, reason="Internal error: Service error"
        )

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.datetime")
    async def test_websocket_notifications_success_ping_pong(
        self, mock_datetime, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test successful WebSocket notifications with ping-pong"""
        mock_auth.return_value = mock_user

        # Mock datetime
        test_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = test_time

        # Mock receive_text to return ping then raise exception to exit loop
        mock_websocket.receive_text.side_effect = [
            json.dumps({"type": "ping"}),
            Exception("Connection closed"),
        ]

        await websocket_notifications(
            websocket=mock_websocket, token="valid-token", db=mock_db_session
        )

        # Verify WebSocket accept was called
        mock_websocket.accept.assert_called_once()

        # Verify welcome message was sent
        welcome_call = mock_websocket.send_text.call_args_list[0]
        welcome_data = json.loads(welcome_call[0][0])
        assert welcome_data["type"] == "welcome"
        assert (
            welcome_data["message"]
            == f"Connected to notifications as {mock_user.username}"
        )

        # Verify pong message was sent
        pong_call = mock_websocket.send_text.call_args_list[1]
        pong_data = json.loads(pong_call[0][0])
        assert pong_data["type"] == "pong"

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    async def test_websocket_notifications_auth_error(
        self, mock_auth, mock_websocket, mock_db_session
    ):
        """Test WebSocket notifications with authentication error"""
        mock_auth.side_effect = HTTPException(status_code=401, detail="Token expired")

        await websocket_notifications(
            websocket=mock_websocket, token="expired-token", db=mock_db_session
        )

        mock_websocket.close.assert_called_once_with(code=1008, reason="Token expired")

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.datetime")
    async def test_websocket_notifications_unknown_message(
        self, mock_datetime, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test WebSocket notifications with unknown message type"""
        mock_auth.return_value = mock_user

        test_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = test_time

        # Mock receive_text to return unknown message then raise exception
        mock_websocket.receive_text.side_effect = [
            json.dumps({"type": "unknown", "data": "test"}),
            Exception("Connection closed"),
        ]

        await websocket_notifications(
            websocket=mock_websocket, token="valid-token", db=mock_db_session
        )

        # Should only send welcome message, no response to unknown message
        assert mock_websocket.send_text.call_count == 1

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.datetime")
    async def test_websocket_notifications_json_error(
        self, mock_datetime, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test WebSocket notifications with JSON parsing error"""
        mock_auth.return_value = mock_user

        test_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = test_time

        # Mock receive_text to return invalid JSON
        mock_websocket.receive_text.side_effect = [
            "invalid json",
            Exception("Connection closed"),
        ]

        await websocket_notifications(
            websocket=mock_websocket, token="valid-token", db=mock_db_session
        )

        # Should only send welcome message, JSON error should be caught
        assert mock_websocket.send_text.call_count == 1

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    async def test_websocket_notifications_general_error(
        self, mock_auth, mock_websocket, mock_db_session
    ):
        """Test WebSocket notifications with general error"""
        mock_auth.return_value = Mock(username="testuser")
        mock_websocket.accept.side_effect = Exception("Connection error")

        await websocket_notifications(
            websocket=mock_websocket, token="valid-token", db=mock_db_session
        )

        mock_websocket.close.assert_called_once_with(
            code=1011, reason="Internal error: Connection error"
        )

    @pytest.mark.asyncio
    @patch("app.websockets.router.get_current_user_ws")
    @patch("app.websockets.router.datetime")
    async def test_websocket_notifications_empty_loop(
        self, mock_datetime, mock_auth, mock_websocket, mock_user, mock_db_session
    ):
        """Test WebSocket notifications message loop with immediate exception"""
        mock_auth.return_value = mock_user

        test_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = test_time

        # Mock receive_text to immediately raise exception
        mock_websocket.receive_text.side_effect = Exception(
            "Connection closed immediately"
        )

        await websocket_notifications(
            websocket=mock_websocket, token="valid-token", db=mock_db_session
        )

        # Should still send welcome message
        assert mock_websocket.send_text.call_count == 1
        welcome_call = mock_websocket.send_text.call_args_list[0]
        welcome_data = json.loads(welcome_call[0][0])
        assert welcome_data["type"] == "welcome"
