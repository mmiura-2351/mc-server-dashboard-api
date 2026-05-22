"""DEPRECATED: re-export shim for `app.servers.application.service`.

Merged into `app/servers/application/service.py` under #228 PR 2c.
Import from `app.servers.application.service` directly in new code.

`minecraft_server_manager` is re-exported for legacy unit tests that
patch it via `patch("app.services.server_service.minecraft_server_manager")`.
"""

from app.servers.application.service import ServerService, server_service
from app.services.minecraft_server import minecraft_server_manager

__all__ = ["ServerService", "server_service", "minecraft_server_manager"]
