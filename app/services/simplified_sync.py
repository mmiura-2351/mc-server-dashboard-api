"""DEPRECATED: re-export shim. See `app.servers.application.simplified_sync`."""

from app.servers.application.simplified_sync import (
    SimplifiedSyncService,
    simplified_sync_service,
)

__all__ = ["SimplifiedSyncService", "simplified_sync_service"]
