"""
Pydantic schemas for version management
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.servers.models import ServerType


class MinecraftVersionBase(BaseModel):
    """Base schema for Minecraft version"""

    server_type: ServerType
    version: str
    download_url: str
    release_date: Optional[datetime] = None
    is_stable: bool = True
    build_number: Optional[int] = None


class MinecraftVersionCreate(MinecraftVersionBase):
    """Schema for creating a new version"""

    pass


class MinecraftVersionUpdate(BaseModel):
    """Schema for updating an existing version"""

    download_url: Optional[str] = None
    release_date: Optional[datetime] = None
    is_stable: Optional[bool] = None
    build_number: Optional[int] = None
    is_active: Optional[bool] = None


class MinecraftVersionResponse(MinecraftVersionBase):
    """Schema for version response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VersionUpdateLogBase(BaseModel):
    """Base schema for version update log"""

    update_type: str
    server_type: Optional[str] = None
    versions_added: int = 0
    versions_updated: int = 0
    versions_removed: int = 0
    execution_time_ms: Optional[int] = None
    external_api_calls: int = 0
    status: str
    error_message: Optional[str] = None
    executed_by_user_id: Optional[int] = None


class VersionUpdateLogCreate(VersionUpdateLogBase):
    """Schema for creating an update log"""

    pass


class VersionUpdateLogResponse(VersionUpdateLogBase):
    """Schema for update log response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate operation duration in seconds"""
        if self.execution_time_ms is not None:
            return self.execution_time_ms / 1000.0
        elif self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds()
        return None

    @property
    def total_changes(self) -> int:
        """Total number of version changes made"""
        return self.versions_added + self.versions_updated + self.versions_removed


class SupportedVersionsResponse(BaseModel):
    """Response schema for supported versions endpoint (backward compatibility)"""

    versions: List[MinecraftVersionResponse]


class VersionUpdateRequest(BaseModel):
    """Request schema for manual version updates"""

    server_types: Optional[List[ServerType]] = None  # None = all types
    force_refresh: bool = False


class VersionUpdateResult(BaseModel):
    """Result of a version update operation"""

    success: bool
    message: str
    log_id: Optional[int] = None
    versions_added: int = 0
    versions_updated: int = 0
    versions_removed: int = 0
    execution_time_ms: Optional[int] = None
    errors: List[str] = []


class UpdateStatusResponse(BaseModel):
    """Response for update status endpoint"""

    last_update: Optional[VersionUpdateLogResponse] = None
    total_versions: int
    versions_by_type: dict[str, int]
    next_scheduled_update: Optional[datetime] = None
    is_update_running: bool = False
