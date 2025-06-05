from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.types import FileType


class FileInfoResponse(BaseModel):
    name: str
    path: str
    type: FileType
    is_directory: bool
    size: Optional[int] = None
    modified: datetime
    permissions: Dict[str, bool]


class FileListResponse(BaseModel):
    files: List[FileInfoResponse]
    current_path: str
    total_files: int


class FileReadResponse(BaseModel):
    content: str
    encoding: str
    file_info: FileInfoResponse


class FileWriteRequest(BaseModel):
    content: str
    encoding: str = Field("utf-8", description="File encoding")
    create_backup: bool = Field(True, description="Create backup before writing")


class FileWriteResponse(BaseModel):
    message: str
    file: FileInfoResponse
    backup_created: bool


class FileUploadResponse(BaseModel):
    message: str
    file: FileInfoResponse
    extracted_files: List[str] = Field(default_factory=list)


class DirectoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Directory name")


class DirectoryCreateResponse(BaseModel):
    message: str
    directory: FileInfoResponse


class FileDeleteResponse(BaseModel):
    message: str


class FileSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query")
    file_type: Optional[FileType] = Field(None, description="Filter by file type")
    include_content: bool = Field(False, description="Search in file content")
    max_results: int = Field(50, ge=1, le=200, description="Maximum number of results")


class FileSearchResult(BaseModel):
    file: FileInfoResponse
    matches: List[str] = Field(
        default_factory=list, description="Matching lines if content search"
    )
    match_count: int = Field(0, description="Number of matches found")


class FileSearchResponse(BaseModel):
    results: List[FileSearchResult]
    query: str
    total_results: int
    search_time_ms: int
