"""Lifecycle tests for ``ConnectionManager`` (Issue #74).

These tests focus on the async resource-management behaviour added in
the Issue #74 fix:

* ``disconnect`` is async and **awaits** the cancelled log-streaming task
  so background coroutines fully release their resources before
  ``disconnect`` returns.
* The log-streaming task gets a done-callback that surfaces unexpected
  exceptions through the standard logger (cancellation is silently
  ignored).
* Repeated connect/disconnect cycles leave **no warnings** under
  ``filterwarnings = error::RuntimeWarning`` — i.e. no orphan coroutines
  or un-awaited tasks remain.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import WebSocket

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


class _NoopLogStream:
    """Mixin-style helper to replace ``_stream_server_logs`` with a
    deterministic, cancellable coroutine — keeps tests free of real
    filesystem dependencies.
    """

    @staticmethod
    async def coro(server_id: int) -> None:
        # Block indefinitely; only cancellation should terminate it.
        await asyncio.Event().wait()


class TestDisconnectAwaitsTask:
    @pytest.mark.asyncio
    async def test_disconnect_cancels_and_awaits_log_task(self) -> None:
        manager = ConnectionManager()
        manager._stream_server_logs = _NoopLogStream.coro  # type: ignore[assignment]

        ws = _make_websocket()
        await manager.connect(ws, server_id=1, user=_make_user())

        task = manager.server_log_tasks[1]
        assert not task.done()

        await manager.disconnect(ws, server_id=1)

        # State fully torn down.
        assert 1 not in manager.active_connections
        assert 1 not in manager.server_log_tasks
        assert ws not in manager.user_connections

        # Task is no longer pending — it was awaited to completion.
        assert task.done()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_disconnect_keeps_task_while_other_connections_remain(self) -> None:
        manager = ConnectionManager()
        manager._stream_server_logs = _NoopLogStream.coro  # type: ignore[assignment]

        ws1 = _make_websocket()
        ws2 = _make_websocket()
        await manager.connect(ws1, server_id=1, user=_make_user("u1"))
        await manager.connect(ws2, server_id=1, user=_make_user("u2"))

        task = manager.server_log_tasks[1]

        await manager.disconnect(ws1, server_id=1)

        # Task should remain because ws2 is still connected.
        assert 1 in manager.server_log_tasks
        assert manager.server_log_tasks[1] is task
        assert not task.done()

        await manager.disconnect(ws2, server_id=1)

        # Now task is cancelled and awaited.
        assert task.done()
        assert 1 not in manager.server_log_tasks

    @pytest.mark.asyncio
    async def test_disconnect_unknown_server_is_noop(self) -> None:
        manager = ConnectionManager()
        await manager.disconnect(_make_websocket(), server_id=999)
        assert manager.active_connections == {}
        assert manager.server_log_tasks == {}
        assert manager.user_connections == {}


class TestDoneCallbackSurfacesExceptions:
    @pytest.mark.asyncio
    async def test_callback_logs_warning_on_exception(self, caplog) -> None:
        manager = ConnectionManager()

        async def _boom(server_id: int) -> None:
            raise RuntimeError("boom")

        manager._stream_server_logs = _boom  # type: ignore[assignment]

        ws = _make_websocket()
        caplog.set_level(logging.WARNING, logger="app.websockets.application.service")

        await manager.connect(ws, server_id=42, user=_make_user())

        # Wait for the background task to finish so the done-callback runs.
        task = manager.server_log_tasks[42]
        try:
            await task
        except RuntimeError:
            pass
        # Yield once more so the done-callback (scheduled via call_soon)
        # gets to execute before we inspect caplog.
        await asyncio.sleep(0)

        warnings = [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "Log streaming task ended with exception" in rec.getMessage()
        ]
        assert warnings, f"expected warning log, got: {caplog.records!r}"

        # Cleanup so subsequent connects work; task is already done.
        manager.server_log_tasks.pop(42, None)
        manager.active_connections.pop(42, None)

    @pytest.mark.asyncio
    async def test_callback_silent_on_cancellation(self, caplog) -> None:
        manager = ConnectionManager()
        manager._stream_server_logs = _NoopLogStream.coro  # type: ignore[assignment]

        ws = _make_websocket()
        caplog.set_level(logging.WARNING, logger="app.websockets.application.service")
        await manager.connect(ws, server_id=7, user=_make_user())
        await manager.disconnect(ws, server_id=7)
        await asyncio.sleep(0)

        unexpected = [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "Log streaming task ended with exception" in rec.getMessage()
        ]
        assert unexpected == []


class TestNoResourceLeaks:
    """Drive multiple connect/disconnect cycles under the strict
    ``error::RuntimeWarning`` filter from ``pyproject.toml`` — any
    un-awaited coroutine or orphan task would be raised as an exception.
    """

    @pytest.mark.asyncio
    async def test_repeated_connect_disconnect_is_leak_free(self) -> None:
        manager = ConnectionManager()
        manager._stream_server_logs = _NoopLogStream.coro  # type: ignore[assignment]

        for i in range(5):
            ws = _make_websocket()
            await manager.connect(ws, server_id=i, user=_make_user(f"u{i}"))
            await manager.disconnect(ws, server_id=i)

        assert manager.active_connections == {}
        assert manager.server_log_tasks == {}
        assert manager.user_connections == {}
