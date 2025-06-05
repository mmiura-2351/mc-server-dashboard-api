from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.files.schemas import (
    DirectoryCreateRequest,
    DirectoryCreateResponse,
    FileDeleteResponse,
    FileInfoResponse,
    FileListResponse,
    FileReadResponse,
    FileSearchRequest,
    FileSearchResponse,
    FileUploadResponse,
    FileWriteRequest,
    FileWriteResponse,
)
from app.services.file_management_service import FileManagementService
from app.types import FileType
from app.users.models import User

router = APIRouter()
file_service = FileManagementService()


@router.get("/servers/{server_id}/files", response_model=FileListResponse)
async def list_server_files(
    server_id: int,
    path: str = "",
    file_type: Optional[FileType] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files and directories in server directory"""
    files = await file_service.get_server_files(
        server_id=server_id,
        path=path,
        file_type=file_type,
        db=db,
    )

    return FileListResponse(
        files=files,
        current_path=path,
        total_files=len(files),
    )


@router.get("/servers/{server_id}/files/read", response_model=FileReadResponse)
async def read_file(
    server_id: int,
    file_path: str,
    encoding: str = "utf-8",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read content of a text file"""
    content = await file_service.read_file(
        server_id=server_id,
        file_path=file_path,
        encoding=encoding,
        db=db,
    )

    files = await file_service.get_server_files(
        server_id=server_id,
        path=file_path,
        db=db,
    )

    return FileReadResponse(
        content=content,
        encoding=encoding,
        file_info=files[0] if files else None,
    )


@router.put("/servers/{server_id}/files/write", response_model=FileWriteResponse)
async def write_file(
    server_id: int,
    file_path: str,
    request: FileWriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Write content to a file"""
    if current_user.role.value not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await file_service.write_file(
        server_id=server_id,
        file_path=file_path,
        content=request.content,
        encoding=request.encoding,
        create_backup=request.create_backup,
        user=current_user,
        db=db,
    )

    return FileWriteResponse(**result)


@router.post("/servers/{server_id}/files/upload", response_model=FileUploadResponse)
async def upload_file(
    server_id: int,
    file: UploadFile = File(...),
    destination_path: str = Form(""),
    extract_if_archive: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file to server directory"""
    if current_user.role.value not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await file_service.upload_file(
        server_id=server_id,
        file=file,
        destination_path=destination_path,
        extract_if_archive=extract_if_archive,
        user=current_user,
        db=db,
    )

    return FileUploadResponse(**result)


@router.get("/servers/{server_id}/files/download")
async def download_file(
    server_id: int,
    file_path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download a file or directory (as zip) from server"""
    file_location, filename = await file_service.download_file(
        server_id=server_id,
        file_path=file_path,
        db=db,
    )

    return FileResponse(
        path=file_location,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.post("/servers/{server_id}/directories", response_model=DirectoryCreateResponse)
async def create_directory(
    server_id: int,
    directory_path: str,
    request: DirectoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new directory in server"""
    if current_user.role.value not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    full_path = f"{directory_path}/{request.name}".strip("/")

    result = await file_service.create_directory(
        server_id=server_id,
        directory_path=full_path,
        user=current_user,
        db=db,
    )

    return DirectoryCreateResponse(**result)


@router.delete("/servers/{server_id}/files", response_model=FileDeleteResponse)
async def delete_file(
    server_id: int,
    file_path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a file or directory from server"""
    if current_user.role.value not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await file_service.delete_file(
        server_id=server_id,
        file_path=file_path,
        user=current_user,
        db=db,
    )

    return FileDeleteResponse(**result)


@router.post("/servers/{server_id}/files/search", response_model=FileSearchResponse)
async def search_files(
    server_id: int,
    request: FileSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search for files in server directory"""
    import re
    import time

    from app.files.schemas import FileSearchResult

    start_time = time.time()

    # Get all files first
    all_files = await file_service.get_server_files(
        server_id=server_id,
        path="",
        file_type=request.file_type,
        db=db,
    )

    results = []
    pattern = re.compile(request.query, re.IGNORECASE)

    for file_info in all_files:
        matches = []
        match_count = 0

        # Search in filename
        if pattern.search(file_info["name"]):
            match_count += 1
            matches.append(f"Filename: {file_info['name']}")

        # Search in file content if requested and file is readable
        if (
            request.include_content
            and not file_info["is_directory"]
            and file_info["permissions"]["readable"]
        ):
            try:
                content = await file_service.read_file(
                    server_id=server_id,
                    file_path=file_info["path"],
                    db=db,
                )

                content_matches = []
                for i, line in enumerate(content.split("\n"), 1):
                    if pattern.search(line):
                        content_matches.append(f"Line {i}: {line.strip()}")
                        match_count += 1

                matches.extend(content_matches[:10])  # Limit content matches

            except Exception:
                pass  # Skip files that can't be read

        if match_count > 0:
            results.append(
                FileSearchResult(
                    file=FileInfoResponse(**file_info),
                    matches=matches,
                    match_count=match_count,
                )
            )

        if len(results) >= request.max_results:
            break

    search_time_ms = int((time.time() - start_time) * 1000)

    return FileSearchResponse(
        results=results,
        query=request.query,
        total_results=len(results),
        search_time_ms=search_time_ms,
    )
