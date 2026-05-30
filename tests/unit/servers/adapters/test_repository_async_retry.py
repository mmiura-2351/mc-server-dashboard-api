"""Regression tests for Issue #410.

`SqlAlchemyServerRepository`'s status/port write methods own their transaction
via the synchronous `with_transaction`, whose retry path calls a blocking
`time.sleep`. These methods are `async def` and awaited on the event loop, so
the call must be offloaded to a worker thread or a backoff stalls the whole API.

Each test replaces `with_transaction` with a deliberately blocking stub and
asserts a concurrent heartbeat coroutine keeps ticking while the write runs —
i.e. the event loop is not blocked. Against the pre-fix code (a direct
synchronous call) the heartbeat would not advance.
"""

import asyncio
import time
from unittest.mock import Mock

import pytest

import app.servers.adapters.repository as repo_mod
from app.servers.adapters.repository import SqlAlchemyServerRepository
from app.servers.models import ServerStatus

pytestmark = pytest.mark.asyncio

# Long enough that a heartbeat ticking every 1 ms accrues many ticks if the
# loop stays free, but short enough to keep the test fast.
BLOCK_SECONDS = 0.1
SENTINEL = "transaction-result"


async def _assert_not_blocked(coro_factory):
    """Run ``coro_factory()`` while a heartbeat ticks; return its result.

    Asserts the heartbeat advanced during the call, proving the event loop was
    not blocked by the (stubbed) synchronous transaction.
    """
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.001)

    hb = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)  # let the heartbeat start
    try:
        result = await coro_factory()
    finally:
        hb.cancel()

    # A blocking on-loop sleep of BLOCK_SECONDS would leave ticks ~0.
    assert ticks > 5, f"event loop appears blocked (ticks={ticks})"
    return result


@pytest.fixture
def blocking_with_transaction(monkeypatch):
    """Patch `with_transaction` with a blocking stub returning a sentinel."""

    def _stub(db, fn):
        time.sleep(BLOCK_SECONDS)  # stand in for retry backoff / blocking I/O
        return SENTINEL

    monkeypatch.setattr(repo_mod, "with_transaction", _stub)
    return _stub


async def test_update_status_does_not_block_event_loop(blocking_with_transaction):
    repo = SqlAlchemyServerRepository(db=Mock())
    result = await _assert_not_blocked(
        lambda: repo.update_status(1, ServerStatus.running)
    )
    assert result == SENTINEL


async def test_update_port_does_not_block_event_loop(blocking_with_transaction):
    repo = SqlAlchemyServerRepository(db=Mock())
    result = await _assert_not_blocked(lambda: repo.update_port(1, 25565))
    assert result == SENTINEL


async def test_batch_update_statuses_does_not_block_event_loop(
    blocking_with_transaction,
):
    repo = SqlAlchemyServerRepository(db=Mock())
    result = await _assert_not_blocked(
        lambda: repo.batch_update_statuses({1: ServerStatus.running})
    )
    assert result == SENTINEL


async def test_batch_update_statuses_empty_short_circuits(blocking_with_transaction):
    """Empty input returns immediately without touching the transaction."""
    repo = SqlAlchemyServerRepository(db=Mock())
    assert await repo.batch_update_statuses({}) == {}
