"""DEPRECATED: re-export shim for ``app.servers.application.database_integration``.

Resolves ``database_integration_service`` lazily through the holder
introduced in PR #279 (mirrors the ``backup_scheduler_instance`` pattern
from PR #264). Previously this shim bound the symbol at import time,
which captured the pre-lifespan instance whose event loop had never been
set — leading to ``RuntimeError: asyncio.run() cannot be called from a
running event loop`` whenever a FastAPI request handler resolved through
the shim. Module-level ``__getattr__`` (PEP 562) now defers the lookup
to call time, so callers always see the lifespan-initialised singleton.

See PR #228 / PR #279.
"""

from typing import Any

from app.servers.application.database_integration import (  # noqa: F401
    DatabaseIntegrationService,
    StatusUpdateCallback,
    UowFactory,
    database_integration_instance,
    make_database_integration_service,
)

# ``database_integration_service`` is resolved lazily via __getattr__
# (PEP 562); ruff's F822 cannot see PEP-562 names so it is suppressed.
__all__ = [  # noqa: F822
    "DatabaseIntegrationService",
    "StatusUpdateCallback",
    "UowFactory",
    "database_integration_instance",
    "database_integration_service",
    "make_database_integration_service",
]


def __getattr__(name: str) -> Any:
    if name == "database_integration_service":
        return database_integration_instance.get()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
