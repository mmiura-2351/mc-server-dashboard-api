import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.servers.models import ServerStatus
from app.servers.schemas import (
    ServerCommandRequest,
    ServerLogsResponse,
    ServerStatusResponse,
)
from app.services.authorization_service import authorization_service
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["servers"])


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
        server = authorization_service.check_server_access(server_id, current_user, db)

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
            # Get more detailed error information
            logger.error(f"Server {server_id} failed to start - checking system state")

            # Check if Java is available using async subprocess
            import asyncio

            try:
                process = await asyncio.create_subprocess_exec(
                    "java",
                    "-version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)

                if process.returncode != 0:
                    logger.error(
                        f"Java not available: {stderr.decode() if stderr else 'Unknown Java error'}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Server start failed: Java runtime not available",
                    )
            except (asyncio.TimeoutError, FileNotFoundError, OSError):
                logger.error("Java executable not found or check timed out")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Server start failed: Java executable not found",
                )

            # Check server files
            server_dir = Path(server.directory_path)
            jar_path = server_dir / "server.jar"

            if not jar_path.exists():
                logger.error(f"Server JAR missing: {jar_path}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Server start failed: server.jar not found",
                )

            # Generic failure if we can't determine specific cause
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server start failed: Check server configuration and system requirements",
            )

        # Database status will be updated automatically via callback
        # when the server actually starts

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
        authorization_service.check_server_access(server_id, current_user, db)

        # Check current status
        current_status = minecraft_server_manager.get_server_status(server_id)
        if current_status == ServerStatus.stopped:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Server is already stopped"
            )

        # Stop the server
        success = await minecraft_server_manager.stop_server(server_id, force=force)
        if success:
            return {"message": "Server stop initiated"}
        else:
            # If stop_server returns False, check if the server is actually stopped
            # Sometimes the process might have stopped but returned False due to timing
            final_status = minecraft_server_manager.get_server_status(server_id)
            if final_status == ServerStatus.stopped:
                return {"message": "Server stop completed"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to stop server",
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error stopping server {server_id}: {e}")
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
        server = authorization_service.check_server_access(server_id, current_user, db)

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

        # Database status will be updated automatically via callback

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
        authorization_service.check_server_access(server_id, current_user, db)

        from app.services.database_integration import database_integration_service

        status = minecraft_server_manager.get_server_status(server_id)
        process_info = database_integration_service.get_server_process_info(server_id)

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
        authorization_service.check_server_access(server_id, current_user, db)

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
        authorization_service.check_server_access(server_id, current_user, db)

        logs = await minecraft_server_manager.get_server_logs(server_id, lines)

        return ServerLogsResponse(server_id=server_id, logs=logs, total_lines=len(logs))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server logs: {str(e)}",
        )
