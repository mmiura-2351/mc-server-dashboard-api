"""Comprehensive test coverage for the servers control router.

Originally deferred under #228 PR 2b (#270) when the legacy
module-level `authorization_service` singleton was replaced by FastAPI
DI of an `AuthorizationService` instance. The 33 tests in this file
have been rewritten to:

1. Pass an `AsyncMock(spec=AuthorizationService)` directly via the
   handler's `auth=` kwarg (replacing the legacy
   `@patch("...control.authorization_service")` shape).
2. Mock the ORM refetch performed in `start_server` / `restart_server`
   — those handlers now call `db.get(Server, server_id)` rather than
   the legacy `db.query(Server).filter(...)` chain (transitional refetch
   tracked by #149 / #272). Tests stub `db_session.get` to return the
   `mock_server` fixture.

All other behaviour (audit logging, Java availability checks, JAR
existence checks, server-status validation, command execution, log
retrieval) is preserved verbatim.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException, Request

from app.servers.application.authorization import AuthorizationService
from app.servers.models import ServerStatus
from app.servers.routers.control import (
    get_server_logs,
    get_server_status,
    restart_server,
    send_server_command,
    start_server,
    stop_server,
)
from app.servers.schemas import ServerCommandRequest
from app.users.domain.value_objects import Role
from app.users.models import User


def _make_auth_mock(server_entity=None) -> AsyncMock:
    """Build an `AsyncMock` shaped like `AuthorizationService`.

    Default `check_server_access` resolves to `server_entity` (so each
    test can inject its own mock server returned from the access
    check). Tests that exercise the access-denied path overwrite
    `auth.check_server_access.side_effect` directly.
    """
    auth = AsyncMock(spec=AuthorizationService)
    auth.check_server_access = AsyncMock(return_value=server_entity)
    return auth


class TestServerControlRouter:
    """Test class for server control router endpoints."""

    @pytest.fixture
    def mock_request(self):
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {}
        return request

    @pytest.fixture
    def admin_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.role = Role.admin
        user.username = "admin"
        return user

    @pytest.fixture
    def regular_user(self):
        user = Mock(spec=User)
        user.id = 2
        user.role = Role.user
        user.username = "testuser"
        return user

    @pytest.fixture
    def mock_server(self):
        server = Mock()
        server.id = 1
        server.name = "test-server"
        server.owner_id = 2
        server.directory_path = "/servers/test-server"
        return server

    @pytest.fixture
    def mock_db_session(self, mock_server):
        """Mock DB session. `db.get(Server, sid)` returns `mock_server`.

        The start/restart handlers now refetch the ORM `Server` via
        `db.get(...)` (see PR 2c — replaces legacy `db.query(...).filter()`).
        """
        db = Mock()
        db.get = Mock(return_value=mock_server)
        return db

    # ---------------- start_server ----------------

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_start_server_success(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Successful server start."""
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=True)
        mock_manager.get_server_info.return_value = {"pid": 12345, "memory": "512MB"}

        result = await start_server(
            server_id=mock_server.id,
            request=mock_request,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert result.server_id == mock_server.id
        assert result.status == ServerStatus.starting
        assert mock_audit.log_server_event.call_count >= 2

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_start_server_invalid_status(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Server start while the server is already running → 409."""
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.running

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 409
        assert "cannot start" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    async def test_start_server_java_not_available(
        self,
        mock_subprocess,
        mock_settings,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """When Java check returns non-zero exit → 500 Java runtime not available."""
        auth = _make_auth_mock(mock_server)
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
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "java runtime not available" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    async def test_start_server_java_executable_not_found(
        self,
        mock_subprocess,
        mock_settings,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """FileNotFoundError on `java` invocation → 500 Java executable not found."""
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5
        mock_subprocess.side_effect = FileNotFoundError("Java executable not found")

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    @patch("pathlib.Path.exists")
    async def test_start_server_jar_missing(
        self,
        mock_exists,
        mock_subprocess,
        mock_settings,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Java ok, but server.jar missing → 500 server.jar not found."""
        auth = _make_auth_mock(mock_server)
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
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "server.jar not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_start_server_unexpected_error(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_db_session,
    ):
        """auth.check_server_access raising Exception → 500."""
        auth = _make_auth_mock()
        auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=1,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to start server" in exc_info.value.detail.lower()

    # ---------------- stop_server ----------------

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_stop_server_success(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.stop_server = AsyncMock(return_value=True)

        result = await stop_server(
            server_id=mock_server.id,
            force=False,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "stop initiated" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_stop_server_force(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.stop_server = AsyncMock(return_value=True)

        result = await stop_server(
            server_id=mock_server.id,
            force=True,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "stop initiated" in result["message"].lower()
        mock_manager.stop_server.assert_called_once_with(mock_server.id, force=True)

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_stop_server_already_stopped(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id=mock_server.id,
                force=False,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 409
        assert "already stopped" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_stop_server_failed_but_actually_stopped(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.side_effect = [
            ServerStatus.running,
            ServerStatus.stopped,
        ]
        mock_manager.stop_server = AsyncMock(return_value=False)

        result = await stop_server(
            server_id=mock_server.id,
            force=False,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "stop completed" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_stop_server_failed(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.side_effect = [
            ServerStatus.running,
            ServerStatus.running,
        ]
        mock_manager.stop_server = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id=mock_server.id,
                force=False,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to stop server" in exc_info.value.detail.lower()

    # ---------------- restart_server ----------------

    @pytest.mark.slow
    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_restart_server_success(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.side_effect = [
            ServerStatus.running,
            ServerStatus.stopped,
        ]
        mock_manager.stop_server = AsyncMock(return_value=True)
        mock_manager.start_server = AsyncMock(return_value=True)

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "restart initiated" in result["message"].lower()
        mock_manager.stop_server.assert_called_once()
        mock_manager.start_server.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_restart_server_already_stopped(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=True)

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "restart initiated" in result["message"].lower()
        mock_manager.stop_server.assert_not_called()
        mock_manager.start_server.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("asyncio.sleep")
    async def test_restart_server_wait_for_stop(
        self,
        mock_sleep,
        mock_manager,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.side_effect = [
            ServerStatus.running,
            ServerStatus.stopping,
            ServerStatus.stopped,
        ]
        mock_manager.stop_server = AsyncMock(return_value=True)
        mock_manager.start_server = AsyncMock(return_value=True)
        mock_sleep.return_value = None

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "restart initiated" in result["message"].lower()
        assert mock_sleep.call_count >= 1

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_restart_server_start_failed(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await restart_server(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to restart server" in exc_info.value.detail.lower()

    # ---------------- get_server_status ----------------

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_get_server_status_success(
        self,
        mock_manager,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Resolves the database integration service through the
        lifespan-scoped holder (PR #279 B1) instead of patching the
        shim attribute (now resolved lazily via ``__getattr__``).
        """
        from app.servers.application.database_integration import (
            database_integration_instance,
        )

        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_db_integration = MagicMock()
        mock_db_integration.get_server_process_info.return_value = {
            "pid": 12345,
            "memory": "512MB",
        }

        previous = (
            database_integration_instance.get()
            if database_integration_instance.is_set()
            else None
        )
        database_integration_instance.set(mock_db_integration)
        try:
            result = await get_server_status(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )
        finally:
            if previous is None:
                database_integration_instance.clear()
            else:
                database_integration_instance.set(previous)

        assert result.server_id == mock_server.id
        assert result.status == ServerStatus.running
        assert result.process_info["pid"] == 12345

    @pytest.mark.asyncio
    async def test_get_server_status_access_denied(
        self, regular_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock()
        auth.check_server_access.side_effect = HTTPException(
            status_code=403, detail="Access denied"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_server_status(
                server_id=mock_server.id,
                current_user=regular_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 403

    # ---------------- send_server_command ----------------

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_send_server_command_success(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=True)

        command_request = ServerCommandRequest(command="say Hello World")
        result = await send_server_command(
            server_id=mock_server.id,
            command_request=command_request,
            http_request=mock_request,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "command 'say hello world' sent" in result["message"].lower()
        mock_manager.send_command.assert_called_once_with(
            mock_server.id, "say Hello World"
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_send_server_command_server_not_running(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_audit.log_server_command_event = Mock()
        mock_audit.log_server_event = Mock()

        command_request = ServerCommandRequest(command="say Hello World")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id=mock_server.id,
                command_request=command_request,
                http_request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 409
        assert (
            "commands can only be sent to running servers"
            in exc_info.value.detail.lower()
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_send_server_command_failed(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.running
        mock_manager.send_command = AsyncMock(return_value=False)
        mock_audit.log_server_command_event = Mock()

        command_request = ServerCommandRequest(command="invalid_command")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id=mock_server.id,
                command_request=command_request,
                http_request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to send command" in exc_info.value.detail.lower()

    # ---------------- get_server_logs ----------------

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_get_server_logs_success(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_logs = [
            "[INFO] Server started",
            "[INFO] Player joined",
            "[INFO] Player left",
        ]
        mock_manager.get_server_logs = AsyncMock(return_value=mock_logs)

        result = await get_server_logs(
            server_id=mock_server.id,
            lines=50,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert result.server_id == mock_server.id
        assert result.logs == mock_logs
        assert result.total_lines == 3
        mock_manager.get_server_logs.assert_called_once_with(mock_server.id, 50)

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_get_server_logs_default_lines(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_logs = AsyncMock(return_value=[])

        result = await get_server_logs(
            server_id=mock_server.id,
            lines=100,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert result.server_id == mock_server.id
        mock_manager.get_server_logs.assert_called_once_with(mock_server.id, 100)

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_get_server_logs_failed(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_logs = AsyncMock(side_effect=Exception("Log read failed"))

        with pytest.raises(HTTPException) as exc_info:
            await get_server_logs(
                server_id=mock_server.id,
                lines=100,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to get server logs" in exc_info.value.detail.lower()

    # ---------------- Edge cases ----------------

    @pytest.mark.asyncio
    async def test_authorization_failure_all_endpoints(
        self, mock_request, regular_user, mock_db_session
    ):
        """Each endpoint must surface a 403 when `auth.check_server_access` raises one."""
        server_id = 1

        def _denying_auth() -> AsyncMock:
            auth = AsyncMock(spec=AuthorizationService)
            auth.check_server_access = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )
            return auth

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id, mock_request, regular_user, mock_db_session, _denying_auth()
            )
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id, False, regular_user, mock_db_session, _denying_auth()
            )
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await restart_server(
                server_id, regular_user, mock_db_session, _denying_auth()
            )
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_server_status(
                server_id, regular_user, mock_db_session, _denying_auth()
            )
        assert exc_info.value.status_code == 403

        command_request = ServerCommandRequest(command="test")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id,
                command_request,
                mock_request,
                regular_user,
                mock_db_session,
                _denying_auth(),
            )
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            await get_server_logs(
                server_id, 100, regular_user, mock_db_session, _denying_auth()
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    async def test_start_server_java_check_timeout(
        self,
        mock_subprocess,
        mock_settings,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Java check times out → 500 java executable not found."""
        auth = _make_auth_mock(mock_server)
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
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("asyncio.sleep")
    async def test_restart_server_stop_timeout(
        self,
        mock_sleep,
        mock_manager,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Stop takes longer than the inner wait loop — restart still proceeds."""
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.side_effect = [ServerStatus.running] + [
            ServerStatus.stopping
        ] * 30
        mock_manager.stop_server = AsyncMock(return_value=True)
        mock_manager.start_server = AsyncMock(return_value=True)
        mock_sleep.return_value = None

        result = await restart_server(
            server_id=mock_server.id,
            current_user=admin_user,
            db=mock_db_session,
            auth=auth,
        )

        assert "restart initiated" in result["message"].lower()
        assert mock_sleep.call_count == 30

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    @patch("pathlib.Path.exists")
    async def test_start_server_configuration_issue(
        self,
        mock_exists,
        mock_subprocess,
        mock_settings,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """Java ok, JAR ok, but server still won't start → generic config message."""
        auth = _make_auth_mock(mock_server)
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
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert (
            "check server configuration and system requirements"
            in exc_info.value.detail.lower()
        )

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_stop_server_unexpected_error(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock()
        auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await stop_server(
                server_id=mock_server.id,
                force=False,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to stop server" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_restart_server_unexpected_error(
        self, mock_manager, admin_user, mock_server, mock_db_session
    ):
        auth = _make_auth_mock()
        auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await restart_server(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to restart server" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    async def test_get_server_status_unexpected_error(
        self,
        mock_manager,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """The error path triggers before holder resolution, so no holder
        injection is required."""
        auth = _make_auth_mock()
        auth.check_server_access.side_effect = Exception("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            await get_server_status(
                server_id=mock_server.id,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to get server status" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    async def test_send_server_command_unexpected_error(
        self,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        auth = _make_auth_mock()
        auth.check_server_access.side_effect = Exception("Unexpected error")
        mock_audit.log_server_command_event = Mock()

        command_request = ServerCommandRequest(command="test")
        with pytest.raises(HTTPException) as exc_info:
            await send_server_command(
                server_id=mock_server.id,
                command_request=command_request,
                http_request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "failed to send command" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    async def test_start_server_java_timeout_error(
        self,
        mock_subprocess,
        mock_settings,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """asyncio.TimeoutError on communicate() → 500 java executable not found."""
        auth = _make_auth_mock(mock_server)
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
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.servers.routers.control.minecraft_server_manager")
    @patch("app.servers.routers.control.AuditService")
    @patch("app.servers.routers.control.settings")
    @patch("asyncio.create_subprocess_exec")
    async def test_start_server_os_error(
        self,
        mock_subprocess,
        mock_settings,
        mock_audit,
        mock_manager,
        mock_request,
        admin_user,
        mock_server,
        mock_db_session,
    ):
        """OSError on the subprocess → 500 java executable not found."""
        auth = _make_auth_mock(mock_server)
        mock_manager.get_server_status.return_value = ServerStatus.stopped
        mock_manager.start_server = AsyncMock(return_value=False)
        mock_settings.JAVA_CHECK_TIMEOUT = 5
        mock_subprocess.side_effect = OSError("System error")

        with pytest.raises(HTTPException) as exc_info:
            await start_server(
                server_id=mock_server.id,
                request=mock_request,
                current_user=admin_user,
                db=mock_db_session,
                auth=auth,
            )

        assert exc_info.value.status_code == 500
        assert "java executable not found" in exc_info.value.detail.lower()
