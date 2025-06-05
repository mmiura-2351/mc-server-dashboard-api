from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.servers.models import BackupStatus, BackupType


class BackupCreateRequest(BaseModel):
    """Request schema for creating a backup"""

    name: str = Field(..., min_length=1, max_length=100, description="Backup name")
    description: Optional[str] = Field(
        None, max_length=500, description="Optional backup description"
    )
    backup_type: BackupType = Field(
        BackupType.manual, description="Type of backup (manual, scheduled, pre_update)"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate backup name"""
        if not v.strip():
            raise ValueError("Backup name cannot be empty")

        # Check for invalid characters
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Backup name contains invalid characters")

        return v.strip()


class BackupRestoreRequest(BaseModel):
    """Request schema for restoring a backup"""

    target_server_id: Optional[int] = Field(
        None, description="Target server ID (defaults to original server)"
    )
    confirm: bool = Field(
        False, description="Confirmation flag - must be True to proceed"
    )

    @field_validator("confirm")
    @classmethod
    def validate_confirm(cls, v: bool) -> bool:
        """Validate confirmation"""
        if not v:
            raise ValueError("Confirmation required to restore backup")
        return v


class BackupResponse(BaseModel):
    """Response schema for backup information"""

    id: int
    server_id: int
    name: str
    description: Optional[str] = None
    file_path: str
    file_size: int
    file_size_mb: float
    backup_type: BackupType
    status: BackupStatus
    created_at: datetime

    # Server information
    server_name: Optional[str] = None
    minecraft_version: Optional[str] = None

    @classmethod
    def from_orm(cls, backup) -> "BackupResponse":
        """Create BackupResponse from ORM model"""
        file_size_mb = (
            round(backup.file_size / (1024 * 1024), 2) if backup.file_size else 0
        )

        return cls(
            id=backup.id,
            server_id=backup.server_id,
            name=backup.name,
            description=backup.description,
            file_path=backup.file_path,
            file_size=backup.file_size,
            file_size_mb=file_size_mb,
            backup_type=backup.backup_type,
            status=backup.status,
            created_at=backup.created_at,
            server_name=backup.server.name if backup.server else None,
            minecraft_version=backup.server.minecraft_version if backup.server else None,
        )

    class Config:
        from_attributes = True


class BackupListResponse(BaseModel):
    """Response schema for backup list with pagination"""

    backups: List[BackupResponse]
    total: int
    page: int
    size: int


class BackupStatisticsResponse(BaseModel):
    """Response schema for backup statistics"""

    total_backups: int
    completed_backups: int
    failed_backups: int
    total_size_bytes: int
    total_size_mb: float


class BackupFilterRequest(BaseModel):
    """Request schema for filtering backups"""

    server_id: Optional[int] = Field(None, description="Filter by server ID")
    backup_type: Optional[BackupType] = Field(None, description="Filter by backup type")
    status: Optional[BackupStatus] = Field(None, description="Filter by status")
    page: int = Field(1, ge=1, description="Page number")
    size: int = Field(50, ge=1, le=100, description="Page size")


class ScheduledBackupRequest(BaseModel):
    """Request schema for creating scheduled backup"""

    server_ids: List[int] = Field(..., min_length=1, description="List of server IDs")

    @field_validator("server_ids")
    @classmethod
    def validate_server_ids(cls, v: List[int]) -> List[int]:
        """Validate server IDs"""
        if not v:
            raise ValueError("At least one server ID is required")

        if len(set(v)) != len(v):
            raise ValueError("Duplicate server IDs not allowed")

        return v


class BackupOperationResponse(BaseModel):
    """Response schema for backup operations"""

    success: bool
    message: str
    backup_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
