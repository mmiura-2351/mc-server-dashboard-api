"""Backwards-compat shim for the original ``minecraft_server`` module.

The 2,324-line implementation that lived here was split into the
:mod:`app.servers.application.minecraft` sub-package under Issue #155
using mixin composition (see ``minecraft/manager.py``).

This module remains as the public import path that the rest of the
application (and the test suite) targets — re-exporting the public API
plus the module-level names that ``unittest.mock.patch`` calls reach
into via ``app.servers.application.minecraft_server.<name>``.

Behavior is preserved byte-for-byte: every log message, exception
type, subprocess/fork sequence, signal handling step, and method
signature is unchanged. Only the file layout differs.
"""

import logging

# Re-export the real implementation (singleton, classes, dataclass).
from app.servers.application.minecraft.manager import (  # noqa: F401
    MinecraftServerManager,
    minecraft_server_manager,
)
from app.servers.application.minecraft.rcon_client import (  # noqa: F401
    MinecraftRCONClient,
)
from app.servers.application.minecraft.server_process import ServerProcess  # noqa: F401

# Re-export module-level symbols that tests patch via
# ``app.servers.application.minecraft_server.<name>``. The split
# modules read these back through a lazy proxy
# (:mod:`app.servers.application.minecraft._compat`) so any
# ``mock.patch`` applied here propagates to all call sites.
from app.versions.application.java_compatibility import (  # noqa: F401
    java_compatibility_service,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MinecraftServerManager",
    "MinecraftRCONClient",
    "ServerProcess",
    "minecraft_server_manager",
    "java_compatibility_service",
    "logger",
]
