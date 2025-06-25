"""
Enhanced schemas for version management system.

Includes both database schemas and API response models for the new fast endpoints.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

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
    last_updated: datetime
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


# ===================
# New fast API response schemas
# ===================


class VersionStatsResponse(BaseModel):
    """Response schema for version statistics"""

    total_versions: int = Field(
        ..., description="Total number of versions across all server types"
    )
    active_versions: int = Field(..., description="Number of currently active versions")
    by_server_type: Dict[str, Dict[str, int]] = Field(
        ...,
        description="Statistics breakdown by server type",
        example={
            "vanilla": {"total": 50, "active": 45},
            "paper": {"total": 120, "active": 115},
            "fabric": {"total": 80, "active": 75},
            "forge": {"total": 200, "active": 180},
        },
    )


# ===================
# Legacy compatibility (for migration)
# ===================


class LegacyVersionResponse(BaseModel):
    """Legacy version response format for compatibility during migration"""

    version: str
    url: Optional[str] = None
    stable: bool = True

    @classmethod
    def from_db_version(cls, db_version) -> "LegacyVersionResponse":
        """Convert database version to legacy format"""
        return cls(
            version=db_version.version,
            url=db_version.download_url,
            stable=db_version.is_stable,
        )


class LegacySupportedVersionsResponse(BaseModel):
    """Legacy supported versions response format"""

    vanilla: List[LegacyVersionResponse] = Field(default_factory=list)
    paper: List[LegacyVersionResponse] = Field(default_factory=list)
    fabric: List[LegacyVersionResponse] = Field(default_factory=list)
    forge: List[LegacyVersionResponse] = Field(default_factory=list)

    @classmethod
    def from_db_versions(
        cls, versions_by_type: Dict[str, List]
    ) -> "LegacySupportedVersionsResponse":
        """Convert database versions to legacy format"""
        return cls(
            vanilla=[
                LegacyVersionResponse.from_db_version(v)
                for v in versions_by_type.get("vanilla", [])
            ],
            paper=[
                LegacyVersionResponse.from_db_version(v)
                for v in versions_by_type.get("paper", [])
            ],
            fabric=[
                LegacyVersionResponse.from_db_version(v)
                for v in versions_by_type.get("fabric", [])
            ],
            forge=[
                LegacyVersionResponse.from_db_version(v)
                for v in versions_by_type.get("forge", [])
            ],
        )


# ===================
# Admin management schemas
# ===================


class VersionManagementStatsResponse(BaseModel):
    """Response for admin version management statistics"""

    total_versions: int
    database_status: str = Field(..., description="healthy, degraded, or error")
    last_update: Optional[datetime] = Field(
        None, description="Last successful update time"
    )
    by_server_type: Dict[str, Dict] = Field(
        ..., description="Detailed stats by server type including latest versions"
    )


class VersionCleanupRequest(BaseModel):
    """Request schema for version cleanup operations"""

    server_type: Optional[str] = Field(
        None, description="Specific server type to clean (null for all)"
    )
    keep_latest: int = Field(
        100, ge=10, le=500, description="Number of latest versions to keep"
    )


class VersionCleanupResponse(BaseModel):
    """Response schema for version cleanup operations"""

    total_removed: int
    status: str = Field(..., description="success, partial_failure, or failed")
    by_server_type: Dict[str, Dict] = Field(
        ..., description="Cleanup results by server type"
    )


class DatabaseIntegrityResponse(BaseModel):
    """Response schema for database integrity validation"""

    status: str = Field(..., description="healthy, issues_found, or error")
    issues: List[str] = Field(default_factory=list, description="Critical issues found")
    warnings: List[str] = Field(default_factory=list, description="Non-critical warnings")
    statistics: Dict[str, int] = Field(
        default_factory=dict, description="Version counts by type"
    )
