import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictException
from app.servers.api.dependencies import (
    get_authorization_service,
    get_server_service,
)
from app.servers.application.authorization import AuthorizationService
from app.servers.application.minecraft_server import minecraft_server_manager
from app.servers.application.service import (
    ServerService,
)
from app.servers.application.service import (
    _server_service_legacy as server_service,  # legacy module-level alias (still referenced by older unit tests)
)
from app.servers.models import ServerStatus
from app.servers.schemas import (
    ServerCreateRequest,
    ServerListResponse,
    ServerResponse,
    ServerUpdateRequest,
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
    """
    try:
        # Phase 1: All users can create servers
        if not AuthorizationService.can_create_server(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to create servers",
            )

        server = await server_service.create_server(request, current_user, db)
        return server

    except ConflictException as e:
        raise e  # Already has proper HTTP status code
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create server: {str(e)}",
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

        return ServerListResponse(**result)

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

    except HTTPException:
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

    except HTTPException:
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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete server: {str(e)}",
        )
