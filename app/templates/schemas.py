from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.servers.models import ServerType

if TYPE_CHECKING:
    from app.templates.domain.entities import TemplateEntity


class TemplateCreateFromServerRequest(BaseModel):
    """Request schema for creating template from existing server"""

    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    description: Optional[str] = Field(
        None, max_length=500, description="Template description"
    )
    is_public: bool = Field(False, description="Whether template should be public")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate template name"""
        if not v.strip():
            raise ValueError("Template name cannot be empty")

        # Check for invalid characters
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Template name contains invalid characters")

        return v.strip()


class TemplateCreateCustomRequest(BaseModel):
    """Request schema for creating custom template"""

    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    description: Optional[str] = Field(
        None, max_length=500, description="Template description"
    )
    minecraft_version: str = Field(..., description="Minecraft version (e.g., 1.20.1)")
    server_type: ServerType = Field(
        ..., description="Server type (vanilla, forge, paper)"
    )
    configuration: Dict[str, Any] = Field(
        default_factory=dict, description="Template configuration"
    )
    default_groups: Optional[Dict[str, List[int]]] = Field(
        None, description="Default group attachments"
    )
    is_public: bool = Field(False, description="Whether template should be public")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate template name"""
        if not v.strip():
            raise ValueError("Template name cannot be empty")

        # Check for invalid characters
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Template name contains invalid characters")

        return v.strip()

    @field_validator("minecraft_version")
    @classmethod
    def validate_minecraft_version(cls, v: str) -> str:
        """Validate Minecraft version format"""
        if not v.strip():
            raise ValueError("Minecraft version cannot be empty")

        # Basic version format validation (e.g., 1.20.1)
        import re

        if not re.match(r"^\d+\.\d+(\.\d+)?$", v.strip()):
            raise ValueError("Invalid Minecraft version format")

        return v.strip()


class TemplateUpdateRequest(BaseModel):
    """Request schema for updating template"""

    name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Template name"
    )
    description: Optional[str] = Field(
        None, max_length=500, description="Template description"
    )
    configuration: Optional[Dict[str, Any]] = Field(
        None, description="Template configuration"
    )
    default_groups: Optional[Dict[str, List[int]]] = Field(
        None, description="Default group attachments"
    )
    is_public: Optional[bool] = Field(
        None, description="Whether template should be public"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate template name"""
        if v is not None:
            if not v.strip():
                raise ValueError("Template name cannot be empty")

            # Check for invalid characters
            invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
            if any(char in v for char in invalid_chars):
                raise ValueError("Template name contains invalid characters")

            return v.strip()
        return v


class TemplateResponse(BaseModel):
    """Response schema for template information"""

    id: int
    name: str
    description: Optional[str] = None
    minecraft_version: str
    server_type: ServerType
    configuration: Dict[str, Any]
    default_groups: Dict[str, List[int]]
    created_by: int
    is_public: bool
    created_at: datetime
    updated_at: datetime

    # Creator information
    creator_name: Optional[str] = None

    @classmethod
    def from_entity(cls, entity: "TemplateEntity") -> "TemplateResponse":
        """Create TemplateResponse from a domain `TemplateEntity`.

        The entity already carries materialised `configuration`,
        `default_groups`, and `creator_name`, so no ORM lookups are
        performed here. This is the single supported constructor; the
        legacy Pydantic-v1 `from_orm` shim was removed in #256.
        """
        # The TemplateResponse fields are non-Optional for `id`,
        # `created_at`, `updated_at`; entities returned by the
        # application service after a successful read or write always
        # have these set.
        assert entity.id is not None
        assert entity.created_at is not None
        assert entity.updated_at is not None
        return cls(
            id=entity.id,
            name=entity.name,
            description=entity.description,
            minecraft_version=entity.minecraft_version,
            server_type=entity.server_type,
            configuration=entity.configuration,
            default_groups=entity.default_groups,
            created_by=entity.created_by,
            is_public=entity.is_public,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            creator_name=entity.creator_name,
        )

    model_config = ConfigDict(from_attributes=True)


class TemplateListResponse(BaseModel):
    """Response schema for template list with pagination.

    Issue #76 (Phase 1): keeps legacy ``templates`` / ``total`` /
    ``page`` / ``size`` keys for back-compat; adds an optional
    ``pagination`` block mirroring :class:`app.core.pagination.PaginationMeta`
    so new consumers can switch to the canonical shape.
    """

    templates: List[TemplateResponse]
    total: int
    page: int
    size: int
    pagination: Optional["PaginationMeta"] = None


from app.core.pagination import PaginationMeta  # noqa: E402

TemplateListResponse.model_rebuild()


class TemplateStatisticsResponse(BaseModel):
    """Response schema for template statistics"""

    total_templates: int
    public_templates: int
    user_templates: int
    server_type_distribution: Dict[str, int]


class TemplateFilterRequest(BaseModel):
    """Request schema for filtering templates"""

    minecraft_version: Optional[str] = Field(
        None, description="Filter by Minecraft version"
    )
    server_type: Optional[ServerType] = Field(None, description="Filter by server type")
    is_public: Optional[bool] = Field(None, description="Filter by public/private status")
    page: int = Field(1, ge=1, description="Page number")
    size: int = Field(50, ge=1, le=100, description="Page size")


class TemplateCloneRequest(BaseModel):
    """Request schema for cloning template"""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Name for the cloned template"
    )
    description: Optional[str] = Field(
        None, max_length=500, description="Description for the cloned template"
    )
    is_public: bool = Field(False, description="Whether cloned template should be public")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate template name"""
        if not v.strip():
            raise ValueError("Template name cannot be empty")

        # Check for invalid characters
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Template name contains invalid characters")

        return v.strip()


class TemplateOperationResponse(BaseModel):
    """Response schema for template operations"""

    success: bool
    message: str
    template_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
