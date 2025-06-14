from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class BackupRestoreWithTemplateRequest(BaseModel):
    """Request schema for restoring a backup and creating a template"""

    target_server_id: Optional[int] = Field(
        None, description="Target server ID (defaults to original server)"
    )
    confirm: bool = Field(
        False, description="Confirmation flag - must be True to proceed"
    )
    template_name: str = Field(
        ..., min_length=1, max_length=100, description="Name for the template to create"
    )
    template_description: Optional[str] = Field(
        None, max_length=500, description="Optional template description"
    )
    is_public: bool = Field(False, description="Whether the template should be public")

    @field_validator("confirm")
    @classmethod
    def validate_confirm(cls, v: bool) -> bool:
        """Validate confirmation"""
        if not v:
            raise ValueError("Confirmation required to restore backup")
        return v

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, v: str) -> str:
        """Validate template name"""
        if not v.strip():
            raise ValueError("Template name cannot be empty")

        # Check for invalid characters
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Template name contains invalid characters")

        return v.strip()


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

    model_config = ConfigDict(from_attributes=True)


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


class BackupRestoreWithTemplateResponse(BaseModel):
    """Response schema for backup restore with template creation"""

    backup_restored: bool
    template_created: bool
    message: str
    backup_id: int
    template_id: Optional[int] = None
    template_name: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


# Backup Scheduler Schemas


class BackupScheduleRequest(BaseModel):
    """Request schema for creating/updating backup schedules"""

    interval_hours: int = Field(
        ..., ge=1, le=168, description="Backup interval in hours (1-168)"
    )
    max_backups: int = Field(
        ..., ge=1, le=30, description="Maximum backups to keep (1-30)"
    )
    enabled: bool = Field(True, description="Enable/disable the schedule")
    only_when_running: bool = Field(
        True, description="Only backup when server is running"
    )


class BackupScheduleUpdateRequest(BaseModel):
    """Request schema for updating backup schedules (all fields optional)"""

    interval_hours: Optional[int] = Field(
        None, ge=1, le=168, description="Backup interval in hours (1-168)"
    )
    max_backups: Optional[int] = Field(
        None, ge=1, le=30, description="Maximum backups to keep (1-30)"
    )
    enabled: Optional[bool] = Field(None, description="Enable/disable the schedule")
    only_when_running: Optional[bool] = Field(
        None, description="Only backup when server is running"
    )


class BackupScheduleResponse(BaseModel):
    """Response schema for backup schedule information"""

    id: int
    server_id: int
    interval_hours: int
    max_backups: int
    enabled: bool
    only_when_running: bool
    last_backup_at: Optional[datetime] = None
    next_backup_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BackupScheduleLogResponse(BaseModel):
    """Response schema for backup schedule log entries"""

    id: int
    server_id: int
    action: str
    reason: Optional[str] = None
    old_config: Optional[Dict[str, Any]] = None
    new_config: Optional[Dict[str, Any]] = None
    executed_by_user_id: Optional[int] = None
    executed_by_username: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SchedulerStatusResponse(BaseModel):
    """Response schema for scheduler status"""

    is_running: bool
    total_schedules: int
    enabled_schedules: int
    cache_size: int
    next_execution: Optional[datetime] = None


class BackupUploadRequest(BaseModel):
    """Request schema for uploading a backup"""

    name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Backup name (optional)"
    )
    description: Optional[str] = Field(
        None, max_length=500, description="Optional backup description"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate backup name"""
        if v is None:
            return v

        v = v.strip()
        if not v:
            return None

        # Check for invalid characters
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Backup name contains invalid characters")

        return v


class BackupUploadResponse(BaseModel):
    """Response schema for backup upload"""

    success: bool
    message: str
    backup: Optional[BackupResponse] = None
    file_size: int
    original_filename: str
