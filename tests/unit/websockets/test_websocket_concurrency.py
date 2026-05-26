"""WebSocket semaphore concurrency tests (Issue #351)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import WebSocket

from app.core.concurrency import ConcurrencySemaphore, SemaphoreRegistry
from app.users.domain.value_objects import Role
from app.users.models import User
from app.websockets.application.service import ConnectionManager


def _make_websocket() -> Mock:
    ws = Mock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _make_user(name: str = "user") -> Mock:
    user = Mock(spec=User)
    user.id = 1
    user.username = name
    user.role = Role.user
    return user


def _registry_with_limits(
    backup: int = 2, websocket: int = 2, file_io: int = 10
) -> SemaphoreRegistry:
    reg = SemaphoreRegistry()
    reg.backup = ConcurrencySemaphore("backup", backup)
    reg.websocket = ConcurrencySemaphore("websocket", websocket)
    reg.file_io = ConcurrencySemaphore("file_io", file_io)
    return reg


@pytest.fixture
def _patch_semaphores():
    reg = _registry_with_limits(websocket=2)
    with (
        patch("app.core.concurrency.semaphores", reg),
        patch("app.core.concurrency.get_semaphores", return_value=reg),
    ):
        yield reg


class TestWebSocketConcurrency:
    @pytest.mark.asyncio
    async def test_rejects_at_limit_with_1013(self, _patch_semaphores):
        reg = _patch_semaphores
        mgr = ConnectionManager()
        # Monkey-patch log streaming to avoid filesystem access
        mgr._stream_server_logs = AsyncMock()

        ws1 = _make_websocket()
        ws2 = _make_websocket()
        ws3 = _make_websocket()
        user = _make_user()

        result1 = await mgr.connect(ws1, 1, user)
        assert result1 is True
        assert reg.websocket.in_use == 1

        result2 = await mgr.connect(ws2, 1, user)
        assert result2 is True
        assert reg.websocket.in_use == 2

        result3 = await mgr.connect(ws3, 1, user)
        assert result3 is False
        ws3.accept.assert_called_once()
        ws3.close.assert_called_once_with(code=1013, reason="Connection limit reached")
        assert reg.websocket.in_use == 2

        # Cleanup
        await mgr.disconnect(ws1, 1)
        await mgr.disconnect(ws2, 1)

    @pytest.mark.asyncio
    async def test_semaphore_released_on_disconnect(self, _patch_semaphores):
        reg = _patch_semaphores
        mgr = ConnectionManager()
        mgr._stream_server_logs = AsyncMock()

        ws = _make_websocket()
        user = _make_user()

        await mgr.connect(ws, 1, user)
        assert reg.websocket.in_use == 1

        await mgr.disconnect(ws, 1)
        assert reg.websocket.in_use == 0
