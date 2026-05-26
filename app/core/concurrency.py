"""Semaphore-based concurrency control for heavy I/O operations.

Provides named ``asyncio.Semaphore`` wrappers with usage tracking and
a registry that reads limits from ``app.core.config.settings``. The
module exposes a singleton ``SemaphoreRegistry`` initialised lazily on
first access via :func:`get_semaphores`.

Issue #351.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ConcurrencySemaphore:
    """Named semaphore with in-use / available tracking."""

    __slots__ = ("name", "limit", "_semaphore", "_in_use")

    def __init__(self, name: str, limit: int) -> None:
        self.name = name
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._in_use = 0

    @property
    def in_use(self) -> int:
        return self._in_use

    @property
    def available(self) -> int:
        return self.limit - self._in_use

    async def acquire(self) -> None:
        if self._in_use >= self.limit:
            logger.info(
                "Semaphore %s: queued (in_use=%d, limit=%d)",
                self.name,
                self._in_use,
                self.limit,
            )
        await self._semaphore.acquire()
        self._in_use += 1
        logger.debug(
            "Semaphore %s: acquired (in_use=%d/%d)",
            self.name,
            self._in_use,
            self.limit,
        )

    def release(self) -> None:
        self._in_use -= 1
        self._semaphore.release()
        logger.debug(
            "Semaphore %s: released (in_use=%d/%d)",
            self.name,
            self._in_use,
            self.limit,
        )

    async def __aenter__(self) -> "ConcurrencySemaphore":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class SemaphoreRegistry:
    """Lazily-initialised registry of application-wide semaphores."""

    def __init__(self) -> None:
        self.backup: Optional[ConcurrencySemaphore] = None
        self.websocket: Optional[ConcurrencySemaphore] = None
        self.file_io: Optional[ConcurrencySemaphore] = None

    def initialize(self) -> None:
        from app.core.config import settings

        self.backup = ConcurrencySemaphore("backup", settings.MAX_CONCURRENT_BACKUPS)
        self.websocket = ConcurrencySemaphore(
            "websocket", settings.MAX_CONCURRENT_WEBSOCKETS
        )
        self.file_io = ConcurrencySemaphore("file_io", settings.FILE_IO_SEMAPHORE_LIMIT)
        logger.info(
            "Semaphores initialised: backup=%d, websocket=%d, file_io=%d",
            settings.MAX_CONCURRENT_BACKUPS,
            settings.MAX_CONCURRENT_WEBSOCKETS,
            settings.FILE_IO_SEMAPHORE_LIMIT,
        )

    def reset(self) -> None:
        self.initialize()


semaphores = SemaphoreRegistry()


def get_semaphores() -> SemaphoreRegistry:
    if semaphores.backup is None:
        semaphores.initialize()
    return semaphores
