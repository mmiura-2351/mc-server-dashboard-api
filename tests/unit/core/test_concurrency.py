"""Unit tests for app.core.concurrency (Issue #351)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.concurrency import ConcurrencySemaphore, SemaphoreRegistry


class TestConcurrencySemaphore:
    @pytest.mark.asyncio
    async def test_acquire_release_tracking(self):
        sema = ConcurrencySemaphore("test", limit=3)
        assert sema.in_use == 0
        assert sema.available == 3

        await sema.acquire()
        assert sema.in_use == 1
        assert sema.available == 2

        sema.release()
        assert sema.in_use == 0
        assert sema.available == 3

    @pytest.mark.asyncio
    async def test_context_manager(self):
        sema = ConcurrencySemaphore("test", limit=5)
        assert sema.in_use == 0

        async with sema:
            assert sema.in_use == 1

        assert sema.in_use == 0

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_blocks_at_limit(self):
        sema = ConcurrencySemaphore("test", limit=2)
        await sema.acquire()
        await sema.acquire()
        assert sema.in_use == 2

        blocked = asyncio.Event()

        async def try_acquire():
            blocked.set()
            await sema.acquire()
            sema.release()

        task = asyncio.create_task(try_acquire())
        await blocked.wait()
        # Give the task a moment to actually block on the semaphore
        await asyncio.sleep(0.05)
        assert sema.in_use == 2

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout=0.1)

        # Release one slot so the blocked task can proceed
        sema.release()
        await asyncio.wait_for(task, timeout=1.0)
        assert sema.in_use == 1

        sema.release()
        assert sema.in_use == 0

    @pytest.mark.asyncio
    async def test_release_on_exception(self):
        sema = ConcurrencySemaphore("test", limit=2)

        with pytest.raises(RuntimeError, match="boom"):
            async with sema:
                assert sema.in_use == 1
                raise RuntimeError("boom")

        assert sema.in_use == 0


class TestSemaphoreRegistry:
    @pytest.mark.asyncio
    async def test_initialize_from_settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        monkeypatch.setenv("MAX_CONCURRENT_BACKUPS", "3")
        monkeypatch.setenv("MAX_CONCURRENT_WEBSOCKETS", "50")
        monkeypatch.setenv("FILE_IO_SEMAPHORE_LIMIT", "8")

        import importlib

        import app.core.config

        importlib.reload(app.core.config)

        registry = SemaphoreRegistry()
        registry.initialize()

        assert registry.backup is not None
        assert registry.backup.limit == 3
        assert registry.websocket is not None
        assert registry.websocket.limit == 50
        assert registry.file_io is not None
        assert registry.file_io.limit == 8

    @pytest.mark.asyncio
    async def test_reset(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

        import importlib

        import app.core.config

        importlib.reload(app.core.config)

        registry = SemaphoreRegistry()
        registry.initialize()
        old_backup = registry.backup

        registry.reset()
        assert registry.backup is not None
        assert registry.backup is not old_backup
