"""
Unified server router module.

This module combines all server-related routers into a single router
for external use, maintaining the same API structure as the original
monolithic router.

Split into modules:
- management.py: Server CRUD operations
- control.py: Server process control
- utilities.py: Utility endpoints
- import_export.py: Export/import functionality
"""

from fastapi import APIRouter, status

# Import route functions directly rather than routers to avoid conflicts
from app.servers.schemas import (
    ServerListResponse,
    ServerLogsResponse,
    ServerResponse,
    ServerStatusResponse,
    SupportedVersionsResponse,
)

from .control import (
    get_server_logs,
    get_server_status,
    restart_server,
    send_server_command,
    start_server,
    stop_server,
)
from .import_export import export_server, import_server
from .management import (
    create_server,
    delete_server,
    get_server,
    list_servers,
    update_server,
)
from .utilities import (
    cleanup_cache,
    get_cache_stats,
    get_supported_versions,
    sync_server_states,
)

# Create the main router that combines all endpoints
router = APIRouter(tags=["servers"])

# Management endpoints
router.add_api_route(
    "",
    create_server,
    methods=["POST"],
    response_model=ServerResponse,
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route("", list_servers, methods=["GET"], response_model=ServerListResponse)
router.add_api_route(
    "/{server_id}", get_server, methods=["GET"], response_model=ServerResponse
)
router.add_api_route(
    "/{server_id}", update_server, methods=["PUT"], response_model=ServerResponse
)
router.add_api_route(
    "/{server_id}",
    delete_server,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)

# Control endpoints
router.add_api_route(
    "/{server_id}/start",
    start_server,
    methods=["POST"],
    response_model=ServerStatusResponse,
)
router.add_api_route("/{server_id}/stop", stop_server, methods=["POST"])
router.add_api_route("/{server_id}/restart", restart_server, methods=["POST"])
router.add_api_route(
    "/{server_id}/status",
    get_server_status,
    methods=["GET"],
    response_model=ServerStatusResponse,
)
router.add_api_route("/{server_id}/command", send_server_command, methods=["POST"])
router.add_api_route(
    "/{server_id}/logs",
    get_server_logs,
    methods=["GET"],
    response_model=ServerLogsResponse,
)

# Utility endpoints
router.add_api_route(
    "/versions/supported",
    get_supported_versions,
    methods=["GET"],
    response_model=SupportedVersionsResponse,
)
router.add_api_route("/sync", sync_server_states, methods=["POST"])
router.add_api_route("/cache/stats", get_cache_stats, methods=["GET"])
router.add_api_route("/cache/cleanup", cleanup_cache, methods=["POST"])

# Import/Export endpoints
router.add_api_route("/{server_id}/export", export_server, methods=["GET"])
router.add_api_route(
    "/import",
    import_server,
    methods=["POST"],
    response_model=ServerResponse,
    status_code=status.HTTP_201_CREATED,
)

__all__ = ["router"]
