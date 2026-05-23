import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.backups.domain.exceptions import (
    BackupNotFoundError,
    BackupParentServerMissingError,
)
from app.core.database import get_db
from app.servers.api.dependencies import (
    get_authorization_service,
    get_server_repository,
    get_server_service,
)
from app.servers.application.authorization import AuthorizationService
from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.application.port_allocator import (
    find_available_ports,
    port_holder,
)
from app.servers.application.service import (
    ServerService,
)
from app.servers.application.service import (
    _server_service_legacy as server_service,  # legacy module-level alias (still referenced by older unit tests)
)
from app.servers.domain.exceptions import (
    NoAvailablePortError,
    ServerAccessError,
    ServerNotFoundError,
)
from app.servers.domain.ports import ServerRepository
from app.servers.models import ServerStatus
from app.servers.schemas import (
    AvailablePortsResponse,
    PortAvailabilityResponse,
    ServerCreateRequest,
    ServerListResponse,
    ServerResponse,
    ServerUpdateRequest,
    ValidateServerCreationResponse,
)
from app.users.models import User

# `server_service` re-exported above is the legacy module-level default
# instance retained for unit tests that patch it via
# `patch("app.servers.routers.management.server_service")`. Production
# routers now receive `ServerService` through DI; the module-level alias
# is no longer used in any endpoint body.
__all__ = ["router", "server_service"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["servers"])


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    request: ServerCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
):
    """
    Create a new Minecraft server

    Creates a server with the specified configuration, downloads the appropriate
    server JAR file, and sets up the server directory structure.

    - **name**: Unique server name
    - **minecraft_version**: Minecraft version (e.g., 1.20.1)
    - **server_type**: Server type (vanilla, forge, paper)
    - **port**: Server port (must be unique)
    - **max_memory**: Maximum memory allocation in MB
    - **max_players**: Maximum number of players
    - **template_id**: Optional template to apply
    - **server_properties**: Custom server.properties overrides
    - **attach_groups**: Groups to attach on creation

    Failure modes raise structured domain exceptions
    (``SERVER_NAME_CONFLICT``, ``SERVER_PORT_CONFLICT``,
    ``SERVER_UNSUPPORTED_VERSION``, ``SERVER_JAVA_INCOMPATIBLE``,
    ``SERVER_JAR_DOWNLOAD_FAILED`` etc.) mapped to actionable HTTP
    responses by the global handlers in
    :mod:`app.core.error_handlers` (Issue #33).
    """
    # Phase 1: All users can create servers
    if not AuthorizationService.can_create_server(current_user):
        raise ServerAccessError("Insufficient permissions to create servers")

    return await server_service.create_server(request, current_user, db)


@router.post(
    "/validate",
    response_model=ValidateServerCreationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_server_creation(
    request: ServerCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
):
    """Pre-validate a server-creation request without persisting (Issue #33).

    Mirrors the validation pipeline of ``POST /api/v1/servers`` so the
    frontend can render inline error/warning UI before the user
    commits. Returns ``200 OK`` with ``valid=false`` (rather than
    raising) so multiple issues can be surfaced in one round-trip.

    Authorization mirrors create — the same ``can_create_server`` gate
    is enforced.
    """
    if not AuthorizationService.can_create_server(current_user):
        raise ServerAccessError("Insufficient permissions to validate server creation")

    return await server_service.validate_creation_request(request, db)


@router.get(
    "/ports/available",
    response_model=AvailablePortsResponse,
    status_code=status.HTTP_200_OK,
)
async def list_available_ports(
    start: int = Query(
        25565,
        ge=1024,
        le=65535,
        description="Starting port for the search (inclusive). Default 25565.",
    ),
    count: int = Query(
        1,
        ge=1,
        le=50,
        description=(
            "Number of free ports to return (clamped to 50 to bound the "
            "scan and mitigate DoS via large ranges)."
        ),
    ),
    current_user: User = Depends(get_current_user),
    server_repo: ServerRepository = Depends(get_server_repository),
):
    """Discover free ports for server creation (Issue #32).

    Walks the registered-port range from ``start`` upward and returns
    up to ``count`` ports that are not currently held by an active
    server (``starting`` / ``running``). Stopped servers do not block
    re-use, matching the contract enforced by the create-server path.

    Authorization mirrors create — the ``can_create_server`` gate is
    enforced so unauthenticated/unauthorized callers cannot enumerate
    the port allocation table. Raises :class:`NoAvailablePortError`
    (409) when the search finds zero free ports.
    """
    if not AuthorizationService.can_create_server(current_user):
        raise ServerAccessError("Insufficient permissions to discover server ports")

    ports = await find_available_ports(server_repo, start, count=count)
    if not ports:
        raise NoAvailablePortError(start_port=start)
    return AvailablePortsResponse(ports=ports, start_port=start)


@router.get(
    "/ports/check/{port}",
    response_model=PortAvailabilityResponse,
    status_code=status.HTTP_200_OK,
)
async def check_port(
    port: int = Path(
        ...,
        ge=1024,
        le=65535,
        description="The port to query (registered range only, 1024-65535).",
    ),
    current_user: User = Depends(get_current_user),
    server_repo: ServerRepository = Depends(get_server_repository),
):
    """Check whether a specific port is currently held (Issue #32).

    Returns the active server holding the port (if any) so frontends
    can render inline feedback before the user submits the create
    form. Holder disclosure mirrors the create-server pre-flight
    behaviour (gated by ``can_create_server``) — non-creator callers
    cannot enumerate other users' ports.
    """
    if not AuthorizationService.can_create_server(current_user):
        raise ServerAccessError("Insufficient permissions to check server ports")

    holder = await port_holder(server_repo, port)
    return PortAvailabilityResponse(
        port=port,
        available=holder is None,
        holder=holder,
    )


@router.get("", response_model=ServerListResponse)
async def list_servers(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    server_service: ServerService = Depends(get_server_service),
):
    """
    List servers with pagination

    Returns a paginated list of all servers. All authenticated users can see all servers.
    """
    try:
        # All users can see all servers
        owner_id = None

        result = await server_service.list_servers_async(
            owner_id=owner_id, page=page, size=size
        )

        # Issue #76 (Phase 1): retain legacy ``page``/``size``/``total``
        # keys (via ``**result``) and additionally surface the canonical
        # ``pagination`` block so new clients can switch over.
        from app.core.pagination import build_pagination_meta

        pagination = build_pagination_meta(
            total=int(result.get("total", 0)),
            page=int(result.get("page", page)),
            size=int(result.get("size", size)),
        )
        return ServerListResponse(**result, pagination=pagination)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list servers: {str(e)}",
        )


@router.get("/{server_id}", response_model=ServerResponse)
async def get_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    auth: AuthorizationService = Depends(get_authorization_service),
    server_service: ServerService = Depends(get_server_service),
):
    """
    Get server details by ID

    Returns detailed information about a specific server including
    runtime status and process information.
    """
    try:
        # Check ownership/admin access
        await auth.check_server_access(server_id, current_user)

        server = await server_service.get_server(server_id, db)
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        return server

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server: {str(e)}",
        )


@router.put("/{server_id}", response_model=ServerResponse)
async def update_server(
    server_id: int,
    request: ServerUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    auth: AuthorizationService = Depends(get_authorization_service),
    server_service: ServerService = Depends(get_server_service),
):
    """
    Update server configuration

    Updates server settings such as name, description, memory allocation,
    and server properties. Server must be stopped to update certain settings.
    """
    try:
        # Check ownership/admin access
        await auth.check_server_access(server_id, current_user)

        # Check if server is running (some updates require server to be stopped)
        server_status = minecraft_server_manager.get_server_status(server_id)
        if server_status not in [ServerStatus.stopped, ServerStatus.error]:
            if request.max_memory is not None or request.server_properties is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Server must be stopped to update memory or server properties",
                )

        server = await server_service.update_server(server_id, request, db)
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        return server

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update server: {str(e)}",
        )


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    auth: AuthorizationService = Depends(get_authorization_service),
    server_service: ServerService = Depends(get_server_service),
):
    """
    Delete a server

    Performs a soft delete of the server. The server will be stopped if running
    and marked as deleted in the database.

    Only admins and server owners can delete servers.
    """
    try:
        # Check server exists and get server entity
        server = await auth.check_server_access(server_id, current_user)

        # Check deletion permission (admin or server owner only)
        if not AuthorizationService.can_delete_server(server, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and server owners can delete servers",
            )

        success = await server_service.delete_server(server_id, db)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete server: {str(e)}",
        )
