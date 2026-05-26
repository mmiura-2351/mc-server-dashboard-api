"""Minecraft server management sub-package.

Split out of the original :mod:`app.servers.application.minecraft_server`
module (see Issue #155). The original module is preserved as a thin
backwards-compat shim that re-exports the public API and any
module-level symbols that test code patches.

Refer to :mod:`app.servers.application.minecraft.manager` for the
composed :class:`MinecraftServerManager` and the
``minecraft_server_manager`` singleton.
"""

from app.servers.application.minecraft.manager import (
    MinecraftServerManager,
    minecraft_server_manager,
)
from app.servers.application.minecraft.rcon_client import MinecraftRCONClient
from app.servers.application.minecraft.server_process import ServerProcess

__all__ = [
    "MinecraftServerManager",
    "MinecraftRCONClient",
    "ServerProcess",
    "minecraft_server_manager",
]
