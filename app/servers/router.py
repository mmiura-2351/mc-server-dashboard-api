import logging
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictException
from app.servers.models import ServerStatus, ServerType
from app.servers.schemas import (
    ServerCommandRequest,
    ServerCreateRequest,
    ServerImportRequest,
    ServerListResponse,
    ServerLogsResponse,
    ServerResponse,
    ServerStatusResponse,
    ServerUpdateRequest,
    SupportedVersionsResponse,
)
from app.servers.service import server_service
from app.services.authorization_service import authorization_service
from app.services.jar_cache_manager import jar_cache_manager
from app.services.minecraft_server import minecraft_server_manager
from app.services.version_manager import minecraft_version_manager
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

            # Check if Java is available
            import subprocess

            try:
                java_check = subprocess.run(
                    ["java", "-version"], capture_output=True, timeout=5
                )
                if java_check.returncode != 0:
                    logger.error(
                        f"Java not available: {java_check.stderr.decode() if java_check.stderr else 'Unknown Java error'}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Server start failed: Java runtime not available",
                    )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                logger.error("Java executable not found")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Server start failed: Java executable not found",
                )

            # Check server files
            from pathlib import Path

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


# Utility Endpoints


@router.get("/versions/supported", response_model=SupportedVersionsResponse)
async def get_supported_versions():
    """
    Get list of supported Minecraft versions

    Returns all supported Minecraft versions by server type with download URLs.
    All versions 1.8+ are supported with dynamic API integration.
    """
    try:
        from app.servers.schemas import MinecraftVersionInfo

        all_versions = []

        # Get versions for each server type
        for server_type in ServerType:
            try:
                versions = await minecraft_version_manager.get_supported_versions(
                    server_type
                )
                # Convert VersionInfo objects to MinecraftVersionInfo objects
                for version_info in versions:
                    minecraft_version_info = MinecraftVersionInfo(
                        version=version_info.version,
                        server_type=version_info.server_type,
                        download_url=version_info.download_url,
                        is_supported=True,  # All returned versions are supported
                        release_date=version_info.release_date,
                        is_stable=version_info.is_stable,
                        build_number=version_info.build_number,
                    )
                    all_versions.append(minecraft_version_info)
            except Exception as e:
                logger.warning(f"Failed to get versions for {server_type.value}: {e}")
                continue

        return SupportedVersionsResponse(versions=all_versions)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get supported versions: {str(e)}",
        )


@router.post("/sync")
async def sync_server_states(current_user: User = Depends(get_current_user)):
    """
    Synchronize server states between database and process manager

    Admin-only endpoint to manually trigger synchronization of server states.
    This ensures database status matches actual running processes.
    """
    try:
        # Only admins can trigger sync
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can sync server states",
            )

        from app.services.database_integration import database_integration_service

        database_integration_service.sync_server_states()

        # Get current state summary
        running_servers = database_integration_service.get_all_running_servers()

        return {
            "message": "Server states synchronized",
            "running_servers": running_servers,
            "total_running": len(running_servers),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync server states: {str(e)}",
        )


@router.get("/cache/stats")
async def get_cache_stats(current_user: User = Depends(get_current_user)):
    """
    Get JAR cache statistics

    Returns information about cached JAR files, total size, and cache efficiency.
    """
    try:
        # Only admins can view cache stats
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view cache statistics",
            )

        stats = await jar_cache_manager.get_cache_stats()
        return stats

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cache stats: {str(e)}",
        )


@router.post("/cache/cleanup")
async def cleanup_cache(current_user: User = Depends(get_current_user)):
    """
    Manually trigger cache cleanup

    Removes old and oversized cache files. Admin-only operation.
    """
    try:
        # Only admins can trigger cache cleanup
        if current_user.role != Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can trigger cache cleanup",
            )

        await jar_cache_manager.cleanup_old_cache()
        stats = await jar_cache_manager.get_cache_stats()

        return {"message": "Cache cleanup completed", "cache_stats": stats}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup cache: {str(e)}",
        )


# Server Export/Import Endpoints


@router.get("/{server_id}/export")
async def export_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Export a server as a ZIP file

    Creates a ZIP archive containing the entire server directory
    with metadata for later import. Excludes logs and temporary files.
    """
    try:
        # Check ownership/admin access (includes operators)
        server = authorization_service.check_server_access(server_id, current_user, db)

        # Check if server exists and get server directory
        server_dir = Path(server.directory_path)
        if not server_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server directory not found"
            )

        # Create temporary export file
        export_id = str(uuid.uuid4())
        temp_dir = Path(tempfile.gettempdir())
        export_file = temp_dir / f"server_export_{export_id}.zip"

        # Create metadata
        metadata = {
            "server_name": server.name,
            "description": server.description,
            "minecraft_version": server.minecraft_version,
            "server_type": server.server_type.value,
            "max_memory": server.max_memory,
            "max_players": server.max_players,
            "export_version": "1.0",
            "exported_at": str(server.updated_at),
        }

        # Create ZIP archive
        with zipfile.ZipFile(export_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Add metadata
            import json

            zipf.writestr("export_metadata.json", json.dumps(metadata, indent=2))

            # Add server files (exclude logs and temp files)
            exclude_patterns = {
                "*.log",
                "logs/",
                "crash-reports/",
                "*.tmp",
                "*.temp",
                ".DS_Store",
                "Thumbs.db",
            }

            for root, dirs, files in os.walk(server_dir):
                # Skip excluded directories
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(
                        d.lower().startswith(pattern.rstrip("/").lower())
                        for pattern in exclude_patterns
                        if "/" in pattern
                    )
                ]

                for file in files:
                    # Skip excluded files
                    if (
                        any(
                            file.lower().endswith(pattern.lstrip("*").lower())
                            for pattern in exclude_patterns
                            if "*" in pattern
                        )
                        or file in exclude_patterns
                    ):
                        continue

                    file_path = Path(root) / file
                    arc_path = file_path.relative_to(server_dir)
                    zipf.write(file_path, arc_path)

        # Get file size
        file_size = export_file.stat().st_size

        # Return file as download
        return FileResponse(
            path=str(export_file),
            filename=f"{server.name}_export_{export_id[:8]}.zip",
            media_type="application/zip",
            headers={
                "Content-Length": str(file_size),
                "Content-Disposition": f'attachment; filename="{server.name}_export_{export_id[:8]}.zip"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export server {server_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export server: {str(e)}",
        )


@router.post(
    "/import", response_model=ServerResponse, status_code=status.HTTP_201_CREATED
)
async def import_server(
    name: str = Form(...),
    description: str = Form(None),
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Import a server from an exported ZIP file

    Creates a new server from an exported ZIP file with the specified
    name and description. Only admin and operator roles can import servers.
    """
    try:
        # Only operators and admins can import servers
        if not authorization_service.can_create_server(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can import servers",
            )

        # Validate file size (500MB limit)
        max_size = 500 * 1024 * 1024  # 500MB
        if file.size and file.size > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {max_size // (1024*1024)}MB",
            )

        # Validate file type
        if not file.filename.endswith(".zip"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only ZIP files are supported",
            )

        # Create request object for validation
        import_request = ServerImportRequest(name=name, description=description)

        # Create temporary directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Save uploaded file
            zip_path = temp_path / "import.zip"
            content = await file.read()
            with open(zip_path, "wb") as f:
                f.write(content)

            # Extract and validate ZIP file
            extract_path = temp_path / "extracted"
            extract_path.mkdir()

            try:
                with zipfile.ZipFile(zip_path, "r") as zipf:
                    zipf.extractall(extract_path)
            except zipfile.BadZipFile:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ZIP file"
                )

            # Read and validate metadata
            metadata_file = extract_path / "export_metadata.json"
            if not metadata_file.exists():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid export file: missing metadata",
                )

            try:
                import json

                with open(metadata_file, "r") as f:
                    metadata = json.load(f)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid export file: corrupted metadata",
                )

            # Validate required metadata fields
            required_fields = [
                "minecraft_version",
                "server_type",
                "max_memory",
                "max_players",
            ]
            for field in required_fields:
                if field not in metadata:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid export file: missing {field} in metadata",
                    )

            # Find available port (only check running servers)
            from app.servers.models import Server

            used_ports = (
                db.query(Server.port)
                .filter(
                    and_(
                        not Server.is_deleted,
                        Server.status.in_([ServerStatus.running, ServerStatus.starting]),
                    )
                )
                .all()
            )
            used_ports = {port[0] for port in used_ports}

            port = 25565
            while port in used_ports:
                port += 1
                if port > 65535:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="No available ports for server",
                    )

            # Create server record
            from app.servers.schemas import ServerCreateRequest

            create_request = ServerCreateRequest(
                name=import_request.name,
                description=import_request.description or metadata.get("description"),
                minecraft_version=metadata["minecraft_version"],
                server_type=ServerType(metadata["server_type"]),
                port=port,
                max_memory=metadata["max_memory"],
                max_players=metadata["max_players"],
            )

            # Create server using existing service
            server = await server_service.create_server(create_request, current_user, db)

            # Replace server directory with imported files
            server_dir = Path(server.directory_path)

            # Remove auto-generated files
            if server_dir.exists():
                import shutil

                shutil.rmtree(server_dir)

            # Move extracted files to server directory
            import shutil

            shutil.move(str(extract_path), str(server_dir))

            # Remove metadata file from server directory
            metadata_file_in_server = server_dir / "export_metadata.json"
            if metadata_file_in_server.exists():
                metadata_file_in_server.unlink()

            logger.info(f"Successfully imported server {server.id} from ZIP file")

            return server

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import server: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import server: {str(e)}",
        )
