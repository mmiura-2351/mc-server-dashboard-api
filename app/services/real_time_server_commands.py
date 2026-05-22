"""DEPRECATED: re-export shim. See `app.servers.application.real_time_server_commands`."""

from app.servers.application.real_time_server_commands import (
    RealTimeServerCommandService,
    real_time_server_commands,
)

__all__ = ["RealTimeServerCommandService", "real_time_server_commands"]
