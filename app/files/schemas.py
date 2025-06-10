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
    is_image: bool = False
    image_data: Optional[str] = None


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


class FileRenameRequest(BaseModel):
    new_name: str = Field(
        ..., min_length=1, max_length=255, description="New filename or directory name"
    )


class FileRenameResponse(BaseModel):
    message: str
    old_path: str
    new_path: str
    file: FileInfoResponse


# File Edit History Schemas
class FileHistoryRecord(BaseModel):
    id: int
    server_id: int
    file_path: str
    version_number: int
    file_size: int
    content_hash: Optional[str]
    editor_user_id: Optional[int]
    editor_username: Optional[str]
    created_at: datetime
    description: Optional[str]

    class Config:
        from_attributes = True


class FileHistoryListResponse(BaseModel):
    file_path: str
    total_versions: int
    history: List[FileHistoryRecord]


class FileVersionContentResponse(BaseModel):
    file_path: str
    version_number: int
    content: str
    encoding: str
    created_at: datetime
    editor_username: Optional[str]
    description: Optional[str]


class RestoreFromVersionRequest(BaseModel):
    create_backup_before_restore: bool = Field(
        True, description="復元前に現在の内容をバックアップ"
    )
    description: Optional[str] = Field(None, description="復元操作の説明")


class RestoreResponse(BaseModel):
    message: str
    file: FileInfoResponse
    backup_created: bool
    restored_from_version: int


class DeleteVersionResponse(BaseModel):
    message: str
    deleted_version: int


class ServerFileHistoryStatsResponse(BaseModel):
    server_id: int
    total_files_with_history: int
    total_versions: int
    total_storage_used: int  # bytes
    oldest_version_date: Optional[datetime]
    most_edited_file: Optional[str]
    most_edited_file_versions: Optional[int]


class CleanupResult(BaseModel):
    deleted_versions: int
    freed_storage: int  # bytes
    cleanup_type: str
