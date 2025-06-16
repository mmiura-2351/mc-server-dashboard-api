"""
Comprehensive test coverage for servers control router
Tests all FastAPI endpoints for server control operations
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException, Request

from app.servers.routers.control import (
    start_server,
    stop_server,
    restart_server,
    get_server_status,
    send_server_command,
    get_server_logs,
)
from app.servers.models import ServerStatus
from app.servers.schemas import ServerCommandRequest
from app.users.models import User, Role


class TestServerControlRouter:
    """Test class for server control router endpoints"""

    @pytest.fixture
    def mock_request(self):
        """Create mock request object"""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {}
        return request

    @pytest.fixture
    def admin_user(self):
        """Create admin user mock"""
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        user.username = "admin"
        return user

    @pytest.fixture
    def regular_user(self):
        """Create regular user mock"""
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        user.username = "testuser"
        return user

    @pytest.fixture
    def mock_server(self):
        """Create mock server"""
        server = Mock()
        server.id = 1
        server.name = "test-server"
        server.owner_id = 2
        server.directory_path = "/servers/test-server"
        return server

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session"""
        return Mock()

    # Test start_server endpoint
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_start_server_success(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test successful server start"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=True)
        mock_manager.get_server_info.return_value = {"pid": 12345, "memory": "512MB"}

        result = await start_server(
            server_id=mock_server.id,
            request=mock_request,
            current_user=admin_user,
            db=mock_db_session
        )

        assert result.server_id == mock_server.id
        assert result.status == ServerStatus.starting
        assert mock_audit.log_server_event.call_count >= 2

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_start_server_invalid_status(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start with invalid status"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 409
        assert "cannot start" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    async def test_start_server_java_not_available(self, mock_subprocess, mock_settings, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start when Java is not available"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5

        mock_process = Mock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Java not found"))
        mock_subprocess.return_value = mock_process

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "java runtime not available" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    async def test_start_server_java_executable_not_found(self, mock_subprocess, mock_settings, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start when Java executable is not found"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5
        mock_subprocess.side_effect = FileNotFoundError("Java executable not found")

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    @patch('pathlib.Path.exists')
    async def test_start_server_jar_missing(self, mock_exists, mock_subprocess, mock_settings, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start when server JAR is missing"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5

        mock_process = Mock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"Java 17", b""))
        mock_subprocess.return_value = mock_process
        mock_exists.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "server.jar not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_start_server_unexpected_error(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start with unexpected error"""
        mock_auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to start server" in exc_info.value.detail.lower()

    # Test stop_server endpoint
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_stop_server_success(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test successful server stop"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.stop_server = AsyncMock(return_value=True)

        result = await stop_server(
            server_id=mock_server.id,
            force=False,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "stop initiated" in result["message"].lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_stop_server_force(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test force stop server"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.stop_server = AsyncMock(return_value=True)

        result = await stop_server(
            server_id=mock_server.id,
            force=True,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "stop initiated" in result["message"].lower()
        mock_manager.stop_server.assert_called_once_with(mock_server.id, force=True)

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_stop_server_already_stopped(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test stop server when already stopped"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id=mock_server.id,
                force=False,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 409
        assert "already stopped" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_stop_server_failed_but_actually_stopped(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test stop server when command fails but server is actually stopped"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.side_effect = [ServerStatus.running, ServerStatus.stopped]
        mock_manager.stop_server = AsyncMock(return_value=False)

        result = await stop_server(
            server_id=mock_server.id,
            force=False,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "stop completed" in result["message"].lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_stop_server_failed(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test stop server failure"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.side_effect = [ServerStatus.running, ServerStatus.running]
        mock_manager.stop_server = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id=mock_server.id,
                force=False,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to stop server" in exc_info.value.detail.lower()

    # Test restart_server endpoint
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_restart_server_success(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test successful server restart"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.side_effect = [ServerStatus.running, ServerStatus.stopped]
        mock_manager.stop_server = AsyncMock(return_value=True)
        mock_manager.start_server = AsyncMock(return_value=True)

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "restart initiated" in result["message"].lower()
        mock_manager.stop_server.assert_called_once()
        mock_manager.start_server.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_restart_server_already_stopped(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test restart server when already stopped"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=True)

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "restart initiated" in result["message"].lower()
        mock_manager.stop_server.assert_not_called()
        mock_manager.start_server.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('asyncio.sleep')
    async def test_restart_server_wait_for_stop(self, mock_sleep, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test restart server waiting for stop to complete"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.side_effect = [ServerStatus.running, ServerStatus.stopping, ServerStatus.stopped]
        mock_manager.stop_server = AsyncMock(return_value=True)
        mock_manager.start_server = AsyncMock(return_value=True)
        mock_sleep.return_value = None

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "restart initiated" in result["message"].lower()
        assert mock_sleep.call_count >= 1

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_restart_server_start_failed(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test restart server when start fails"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await restart_server(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to restart server" in exc_info.value.detail.lower()

    # Test get_server_status endpoint
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.services.database_integration.database_integration_service')
    async def test_get_server_status_success(self, mock_db_integration, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test successful get server status"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_db_integration.get_server_process_info.return_value = {"pid": 12345, "memory": "512MB"}

        result = await get_server_status(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session
        )

        assert result.server_id == mock_server.id
        assert result.status == ServerStatus.running
        assert result.process_info["pid"] == 12345

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    async def test_get_server_status_access_denied(self, mock_auth, regular_user, mock_server, mock_db_session):
        """Test get server status with access denied"""
        mock_auth.check_server_access.side_effect = HTTPException(status_code=403, detail="Access denied")

        with pytest.raises(HTTPException) as exc_info:
            await get_server_status(
                server_id=mock_server.id,
                current_user=regular_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 403

    # Test send_server_command endpoint
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_send_server_command_success(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test successful command send"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=True)

        command_request = ServerCommandRequest(command="say Hello World")
        result = await send_server_command(
            server_id=mock_server.id,
            command_request=command_request,
            http_request=mock_request,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "command 'say hello world' sent" in result["message"].lower()
        mock_manager.send_command.assert_called_once_with(mock_server.id, "say Hello World")

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_send_server_command_server_not_running(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test command send when server not running"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        command_request = ServerCommandRequest(command="say Hello World")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id=mock_server.id,
                command_request=command_request,
                http_request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 409
        assert "commands can only be sent to running servers" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_send_server_command_failed(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test command send failure"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=False)

        command_request = ServerCommandRequest(command="invalid_command")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id=mock_server.id,
                command_request=command_request,
                http_request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to send command" in exc_info.value.detail.lower()

    # Test get_server_logs endpoint
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_get_server_logs_success(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test successful get server logs"""
        mock_auth.check_server_access.return_value = mock_server
        mock_logs = ["[INFO] Server started", "[INFO] Player joined", "[INFO] Player left"]
        mock_manager.get_server_logs = AsyncMock(return_value=mock_logs)

        result = await get_server_logs(
            server_id=mock_server.id,
            lines=50,
            current_user=admin_user,
            db=mock_db_session
        )

        assert result.server_id == mock_server.id
        assert result.logs == mock_logs
        assert result.total_lines == 3
        mock_manager.get_server_logs.assert_called_once_with(mock_server.id, 50)

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_get_server_logs_default_lines(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test get server logs with default line count"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_logs = AsyncMock(return_value=[])

        result = await get_server_logs(
            server_id=mock_server.id,
            lines=100,
            current_user=admin_user,
            db=mock_db_session
        )

        assert result.server_id == mock_server.id
        mock_manager.get_server_logs.assert_called_once_with(mock_server.id, 100)

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_get_server_logs_failed(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test get server logs failure"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_logs = AsyncMock(side_effect=Exception("Log read failed"))

        with pytest.raises(HTTPException) as exc_info:
            await get_server_logs(
                server_id=mock_server.id,
                lines=100,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to get server logs" in exc_info.value.detail.lower()

    # Test edge cases and error conditions
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    async def test_authorization_failure_all_endpoints(self, mock_auth, mock_request, regular_user, mock_db_session):
        """Test authorization failure for all endpoints"""
        mock_auth.check_server_access.side_effect = HTTPException(status_code=403, detail="Access denied")

        server_id = 1
        
        with pytest.raises(HTTPException) as exc_info:
            await start_server(server_id, mock_request, regular_user, mock_db_session)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(server_id, False, regular_user, mock_db_session)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await restart_server(server_id, regular_user, mock_db_session)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_server_status(server_id, regular_user, mock_db_session)
        assert exc_info.value.status_code == 403

        command_request = ServerCommandRequest(command="test")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(server_id, command_request, mock_request, regular_user, mock_db_session)
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_server_logs(server_id, 100, regular_user, mock_db_session)
        assert exc_info.value.status_code == 403

    # Test timeout and async operation edge cases
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    async def test_start_server_java_check_timeout(self, mock_subprocess, mock_settings, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start with Java check timeout"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 1

        mock_process = Mock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))
        mock_subprocess.return_value = mock_process

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('asyncio.sleep')
    async def test_restart_server_stop_timeout(self, mock_sleep, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test restart server when stop takes too long"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.side_effect = [ServerStatus.running] + [ServerStatus.stopping] * 30
        mock_manager.stop_server = AsyncMock(return_value=True)
        mock_manager.start_server = AsyncMock(return_value=True)
        mock_sleep.return_value = None

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session
        )

        assert "restart initiated" in result["message"].lower()
        assert mock_sleep.call_count == 30

    # Test configuration failures
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    @patch('pathlib.Path.exists')
    async def test_start_server_configuration_issue(self, mock_exists, mock_subprocess, mock_settings, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start with generic configuration issue"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5

        mock_process = Mock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"Java 17", b""))
        mock_subprocess.return_value = mock_process
        mock_exists.return_value = True

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "check server configuration and system requirements" in exc_info.value.detail.lower()

    # Test error handling in other endpoints
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_stop_server_unexpected_error(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test stop server with unexpected error"""
        mock_auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id=mock_server.id,
                force=False,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to stop server" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_restart_server_unexpected_error(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test restart server with unexpected error"""
        mock_auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await restart_server(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to restart server" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    async def test_get_server_status_unexpected_error(self, mock_manager, mock_auth, admin_user, mock_server, mock_db_session):
        """Test get server status with unexpected error"""
        mock_auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await get_server_status(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to get server status" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    async def test_send_server_command_unexpected_error(self, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test send server command with unexpected error"""
        mock_auth.check_server_access.side_effect = Exception("Unexpected error")

        command_request = ServerCommandRequest(command="test")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id=mock_server.id,
                command_request=command_request,
                http_request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "failed to send command" in exc_info.value.detail.lower()

    # Test comprehensive error scenarios in start_server
    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    async def test_start_server_java_timeout_error(self, mock_subprocess, mock_settings, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start with Java timeout error"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 1

        with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError("Timeout")):
            mock_process = Mock()
            mock_process.communicate = AsyncMock(return_value=(b"Java 17", b""))
            mock_subprocess.return_value = mock_process

            with pytest.raises(HTTPException) as exc_info:
                await start_server(
                    server_id=mock_server.id,
                    request=mock_request,
                    current_user=admin_user,
                    db=mock_db_session
                )

            assert exc_info.value.status_code == 500
            assert "java executable not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('app.servers.routers.control.authorization_service')
    @patch('app.servers.routers.control.minecraft_server_manager')
    @patch('app.servers.routers.control.AuditService')
    @patch('app.servers.routers.control.settings')
    @patch('asyncio.create_subprocess_exec')
    async def test_start_server_os_error(self, mock_subprocess, mock_settings, mock_audit, mock_manager, mock_auth, mock_request, admin_user, mock_server, mock_db_session):
        """Test server start with OS error"""
        mock_auth.check_server_access.return_value = mock_server
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5
        mock_subprocess.side_effect = OSError("System error")

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()