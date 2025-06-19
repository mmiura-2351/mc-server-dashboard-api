"""
Pydantic schemas for resource visibility API endpoints

Defines request/response models for the Phase 2 visibility management system.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.visibility import ResourceType, VisibilityType
from app.users.models import Role


class VisibilityUpdateRequest(BaseModel):
    """Request model for updating resource visibility"""

    visibility_type: VisibilityType = Field(
        description="Type of visibility to set for the resource"
    )
    role_restriction: Optional[Role] = Field(
        default=None,
        description="Role restriction for role_based visibility (required if visibility_type is role_based)",
    )

    class Config:
        json_schema_extra = {
            "example": {"visibility_type": "role_based", "role_restriction": "operator"}
        }


class UserAccessGrantRequest(BaseModel):
    """Request model for granting specific user access"""

    user_id: int = Field(description="ID of the user to grant access to")

    class Config:
        json_schema_extra = {"example": {"user_id": 123}}


class UserAccessGrantResponse(BaseModel):
    """Response model for user access grant information"""

    user_id: int
    granted_by_user_id: Optional[int]
    granted_at: datetime

    class Config:
        from_attributes = True


class VisibilityInfoResponse(BaseModel):
    """Response model for resource visibility information"""

    resource_type: ResourceType
    resource_id: int
    visibility_type: VisibilityType
    role_restriction: Optional[Role] = None
    granted_users: Optional[List[UserAccessGrantResponse]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "resource_type": "server",
                "resource_id": 1,
                "visibility_type": "specific_users",
                "role_restriction": None,
                "granted_users": [
                    {
                        "user_id": 123,
                        "granted_by_user_id": 456,
                        "granted_at": "2024-01-01T12:00:00Z",
                    }
                ],
                "created_at": "2024-01-01T10:00:00Z",
                "updated_at": "2024-01-01T11:00:00Z",
            }
        }


class MigrationStatusResponse(BaseModel):
    """Response model for migration status information"""

    migration_complete: bool
    issues: List[str]
    resource_stats: dict
    visibility_distribution: dict

    class Config:
        json_schema_extra = {
            "example": {
                "migration_complete": True,
                "issues": [],
                "resource_stats": {
                    "servers": {"total": 10, "with_visibility": 10, "missing": 0},
                    "groups": {"total": 5, "with_visibility": 5, "missing": 0},
                },
                "visibility_distribution": {
                    "server": {"public": 8, "private": 2},
                    "group": {"public": 3, "role_based": 2},
                },
            }
        }


class MigrationExecuteResponse(BaseModel):
    """Response model for migration execution results"""

    success: bool
    message: str
    migration_counts: dict

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Migration completed successfully",
                "migration_counts": {"servers": 10, "groups": 5, "total": 15},
            }
        }


# Export schemas
__all__ = [
    "VisibilityUpdateRequest",
    "UserAccessGrantRequest",
    "UserAccessGrantResponse",
    "VisibilityInfoResponse",
    "MigrationStatusResponse",
    "MigrationExecuteResponse",
]
