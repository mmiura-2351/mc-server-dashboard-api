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
from app.servers.models import ServerStatus
from app.servers.schemas import (
    ServerCreateRequest,
    ServerListResponse,
    ServerResponse,
    ServerUpdateRequest,
)
from app.servers.service import server_service
from app.services.authorization_service import authorization_service
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["servers"])


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    request: ServerCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
        # Only operators and admins can create servers
        if not authorization_service.can_create_server(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create servers",
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
):
    """
    List servers with pagination

    Returns a paginated list of servers. Regular users see only their own servers,
    while admins see all servers.
    """
    try:
        # Admins see all servers, others see only their own
        owner_id = None if current_user.role == Role.admin else current_user.id

        result = server_service.list_servers(
            owner_id=owner_id, page=page, size=size, db=db
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
):
    """
    Get server details by ID

    Returns detailed information about a specific server including
    runtime status and process information.
    """
    try:
        # Check ownership/admin access
        authorization_service.check_server_access(server_id, current_user, db)

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
):
    """
    Update server configuration

    Updates server settings such as name, description, memory allocation,
    and server properties. Server must be stopped to update certain settings.
    """
    try:
        # Check ownership/admin access
        authorization_service.check_server_access(server_id, current_user, db)

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
):
    """
    Delete a server

    Performs a soft delete of the server. The server will be stopped if running
    and marked as deleted in the database.
    """
    try:
        # Check ownership/admin access
        authorization_service.check_server_access(server_id, current_user, db)

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
