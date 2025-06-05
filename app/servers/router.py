from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.servers.models import ServerStatus
from app.servers.schemas import (
    ServerCommandRequest,
    ServerCreateRequest,
    ServerListResponse,
    ServerLogsResponse,
    ServerResponse,
    ServerStatusResponse,
    ServerUpdateRequest,
    SupportedVersionsResponse,
)
from app.servers.service import ServerCreationError, ServerExistsError, server_service
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import Role, User

router = APIRouter(tags=["servers"])


def check_server_owner_or_admin(server_id: int, current_user: User, db: Session):
    """Check if user owns the server or is admin"""
    from app.servers.models import Server

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
        )

    if current_user.role != Role.admin and server.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this server",
        )

    return server


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
        if current_user.role == Role.user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create servers",
            )

        server = await server_service.create_server(request, current_user, db)
        return server

    except ServerExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ServerCreationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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

        result = await server_service.list_servers(
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
        check_server_owner_or_admin(server_id, current_user, db)

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
        check_server_owner_or_admin(server_id, current_user, db)

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
        check_server_owner_or_admin(server_id, current_user, db)

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


# Server Process Control Endpoints


@router.post("/{server_id}/start", response_model=ServerStatusResponse)
async def start_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start a Minecraft server

    Starts the server process and begins monitoring. The server must be
    in 'stopped' or 'error' state to be started.
    """
    try:
        # Check ownership/admin access
        server = check_server_owner_or_admin(server_id, current_user, db)

        # Check current status
        current_status = minecraft_server_manager.get_server_status(server_id)
        if current_status not in [ServerStatus.stopped, ServerStatus.error]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Server is currently {current_status.value}, cannot start",
            )

        # Start the server
        success = await minecraft_server_manager.start_server(server)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start server",
            )

        # Update database status
        server.status = ServerStatus.starting
        db.commit()

        return ServerStatusResponse(
            server_id=server_id,
            status=ServerStatus.starting,
            process_info=minecraft_server_manager.get_server_info(server_id),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start server: {str(e)}",
        )


@router.post("/{server_id}/stop")
async def stop_server(
    server_id: int,
    force: bool = Query(False, description="Force stop the server"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stop a Minecraft server

    Gracefully stops the server by sending a 'stop' command. If force=true,
    terminates the process immediately.
    """
    try:
        # Check ownership/admin access
        server = check_server_owner_or_admin(server_id, current_user, db)

        # Check current status
        current_status = minecraft_server_manager.get_server_status(server_id)
        if current_status == ServerStatus.stopped:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Server is already stopped"
            )

        # Stop the server
        success = await minecraft_server_manager.stop_server(server_id, force=force)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stop server",
            )

        # Update database status
        server.status = ServerStatus.stopping
        db.commit()

        return {"message": "Server stop initiated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop server: {str(e)}",
        )


@router.post("/{server_id}/restart")
async def restart_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Restart a Minecraft server

    Stops the server (if running) and starts it again.
    """
    try:
        # Check ownership/admin access
        server = check_server_owner_or_admin(server_id, current_user, db)

        current_status = minecraft_server_manager.get_server_status(server_id)

        # Stop if running
        if current_status not in [ServerStatus.stopped, ServerStatus.error]:
            await minecraft_server_manager.stop_server(server_id)

            # Wait for server to stop
            import asyncio

            for _ in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)
                if (
                    minecraft_server_manager.get_server_status(server_id)
                    == ServerStatus.stopped
                ):
                    break

        # Start the server
        success = await minecraft_server_manager.start_server(server)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to restart server",
            )

        server.status = ServerStatus.starting
        db.commit()

        return {"message": "Server restart initiated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart server: {str(e)}",
        )


@router.get("/{server_id}/status", response_model=ServerStatusResponse)
async def get_server_status(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current server status and process information

    Returns the current status of the server process and runtime information.
    """
    try:
        # Check ownership/admin access
        check_server_owner_or_admin(server_id, current_user, db)

        status = minecraft_server_manager.get_server_status(server_id)
        process_info = minecraft_server_manager.get_server_info(server_id)

        return ServerStatusResponse(
            server_id=server_id, status=status, process_info=process_info
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server status: {str(e)}",
        )


@router.post("/{server_id}/command")
async def send_server_command(
    server_id: int,
    request: ServerCommandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Send a command to a running server

    Sends a console command to the server. The server must be running.
    Some dangerous commands are blocked for safety.
    """
    try:
        # Check ownership/admin access
        check_server_owner_or_admin(server_id, current_user, db)

        # Check if server is running
        status = minecraft_server_manager.get_server_status(server_id)
        if status != ServerStatus.running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Server is {status.value}, commands can only be sent to running servers",
            )

        # Send command
        success = await minecraft_server_manager.send_command(server_id, request.command)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send command to server",
            )

        return {"message": f"Command '{request.command}' sent to server"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send command: {str(e)}",
        )


@router.get("/{server_id}/logs", response_model=ServerLogsResponse)
async def get_server_logs(
    server_id: int,
    lines: int = Query(100, ge=1, le=1000, description="Number of log lines to retrieve"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get recent server logs

    Returns the most recent log entries from the server console.
    """
    try:
        # Check ownership/admin access
        check_server_owner_or_admin(server_id, current_user, db)

        logs = await minecraft_server_manager.get_server_logs(server_id, lines)

        return ServerLogsResponse(server_id=server_id, logs=logs, total_lines=len(logs))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server logs: {str(e)}",
        )


# Utility Endpoints


@router.get("/versions/supported", response_model=SupportedVersionsResponse)
async def get_supported_versions():
    """
    Get list of supported Minecraft versions

    Returns all supported Minecraft versions by server type with download URLs.
    """
    try:
        versions = server_service.get_supported_versions()
        return SupportedVersionsResponse(**versions)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get supported versions: {str(e)}",
        )
