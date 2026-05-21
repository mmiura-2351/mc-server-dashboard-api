"""Memory-bound context manager used during streaming uploads.

Migrated verbatim from `app.services.backup_service.ResourceMonitor`.
Optional dependency on `psutil`; if unavailable the monitor degrades
to a no-op (legacy behaviour preserved).
"""

import logging

try:
    import psutil
except ImportError:  # pragma: no cover - environment dependent
    psutil = None

logger = logging.getLogger(__name__)


class ResourceMonitor:
    """Monitor and limit resource usage during file operations."""

    def __init__(self, max_memory_mb: int = 256):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.initial_memory = None
        self.enabled = psutil is not None
        if not self.enabled:
            logger.warning("psutil not available, memory monitoring disabled")

    async def __aenter__(self):
        if self.enabled:
            process = psutil.Process()
            self.initial_memory = process.memory_info().rss
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.enabled and exc_type is None:
            process = psutil.Process()
            current_memory = process.memory_info().rss
            memory_increase = current_memory - self.initial_memory
            logger.debug(
                f"Operation completed with memory increase: "
                f"{memory_increase / 1024 / 1024:.1f}MB"
            )

    async def check_memory_usage(self) -> None:
        if not self.enabled or self.initial_memory is None:
            return
        process = psutil.Process()
        current_memory = process.memory_info().rss
        memory_increase = current_memory - self.initial_memory
        if memory_increase > self.max_memory_bytes:
            raise MemoryError(
                f"Memory usage exceeded limit: "
                f"{memory_increase / 1024 / 1024:.1f}MB "
                f"(max: {self.max_memory_bytes / 1024 / 1024:.1f}MB)"
            )
