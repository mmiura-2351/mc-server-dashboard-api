import json
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
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
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
from app.servers.application.service import (
    ServerService,
)
from app.servers.application.service import (
    _server_service_legacy as server_service,  # legacy module-level alias for old unit tests
)
from app.servers.domain.exceptions import ServerAccessError, ServerNotFoundError
from app.servers.domain.ports import ServerRepository
from app.servers.models import ServerStatus, ServerType
from app.servers.schemas import (
    ServerCreateRequest,
    ServerImportRequest,
    ServerResponse,
)
from app.users.models import User

__all__ = ["router", "server_service"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["servers"])


@router.get("/{server_id}/export")
async def export_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """
    Export a server as a ZIP file

    Creates a ZIP archive containing the entire server directory
    with metadata for later import. Excludes logs and temporary files.
    """
    try:
        # Check ownership/admin access (includes operators)
        server = await auth.check_server_access(server_id, current_user)

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
    server_repo: ServerRepository = Depends(get_server_repository),
    server_service: ServerService = Depends(get_server_service),
):
    """
    Import a server from an exported ZIP file

    Creates a new server from an exported ZIP file with the specified
    name and description. Only admin and operator roles can import servers.
    """
    try:
        # Only operators and admins can import servers
        if not AuthorizationService.can_create_server(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can import servers",
            )

        # Validate file size (500MB limit)
        max_size = 500 * 1024 * 1024  # 500MB
        if file.size and file.size > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {max_size // (1024 * 1024)}MB",
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

            # Find available port (only check running servers).
            # Previous implementation applied Python's `not` to the
            # SQLAlchemy is_deleted Column, which always evaluates to
            # False, so `used_ports` was permanently empty and port
            # 25565 was always offered even when occupied. Route
            # through the Server Repository's
            # `list_by_port(port=None, statuses=...)` which excludes
            # soft-deleted rows by default.
            used_servers = await server_repo.list_by_port(
                port=None,
                statuses=[ServerStatus.running, ServerStatus.starting],
            )
            used_ports = {s.port for s in used_servers}

            port = 25565
            while port in used_ports:
                port += 1
                if port > 65535:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="No available ports for server",
                    )

            # Create server record
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
        logger.error(f"Failed to import server: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import server: {str(e)}",
        )
