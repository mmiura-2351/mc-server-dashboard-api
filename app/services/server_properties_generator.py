"""DEPRECATED: re-export shim. See `app.servers.application.server_properties_generator`."""

from app.servers.application.server_properties_generator import (
    ServerPropertiesGenerator,
    server_properties_generator,
)

__all__ = ["ServerPropertiesGenerator", "server_properties_generator"]
