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
from app.services.authorization_service import authorization_service
from app.services.file_management_service import file_management_service
from app.types import FileType
from app.users.models import User

router = APIRouter()


@router.get("/servers/{server_id}/files", response_model=FileListResponse)
async def list_server_files(
    server_id: int,
    path: str = "",
    file_type: Optional[FileType] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files and directories in server directory"""
    files = await file_management_service.get_server_files(
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
    content = await file_management_service.read_file(
        server_id=server_id,
        file_path=file_path,
        encoding=encoding,
        db=db,
    )

    files = await file_management_service.get_server_files(
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
    if not authorization_service.can_modify_files(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await file_management_service.write_file(
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
    if not authorization_service.can_modify_files(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await file_management_service.upload_file(
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
    file_location, filename = await file_management_service.download_file(
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
    if not authorization_service.can_modify_files(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    full_path = f"{directory_path}/{request.name}".strip("/")

    result = await file_management_service.create_directory(
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
    if not authorization_service.can_modify_files(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await file_management_service.delete_file(
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
    from app.files.schemas import FileSearchResult

    search_result = await file_management_service.search_files(
        server_id=server_id,
        query=request.query,
        file_type=request.file_type,
        include_content=request.include_content,
        max_results=request.max_results,
        db=db,
    )

    # Convert results to proper schema objects
    formatted_results = []
    for result in search_result["results"]:
        formatted_results.append(
            FileSearchResult(
                file=FileInfoResponse(**result["file"]),
                matches=result["matches"],
                match_count=result["match_count"],
            )
        )

    return FileSearchResponse(
        results=formatted_results,
        query=search_result["query"],
        total_results=search_result["total_results"],
        search_time_ms=search_result["search_time_ms"],
    )
