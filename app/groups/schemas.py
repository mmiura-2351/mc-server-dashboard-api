from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.groups.models import GroupType


class PlayerSchema(BaseModel):
    """Player information within a group"""

    uuid: str = Field(..., description="Player UUID")
    username: str = Field(..., description="Player username")
    added_at: Optional[str] = Field(None, description="When player was added")


class GroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Group name")
    description: Optional[str] = Field(
        None, max_length=500, description="Group description"
    )
    group_type: GroupType = Field(..., description="Group type: op or whitelist")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Group name cannot be empty")
        # Only allow alphanumeric, spaces, hyphens, underscores
        import re

        if not re.match(r"^[a-zA-Z0-9\s\-_]+$", v):
            raise ValueError("Group name contains invalid characters")
        return v.strip()


class GroupUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Group name cannot be empty")
        return v.strip() if v else v


class GroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    type: GroupType
    players: List[PlayerSchema] = []
    owner_id: int
    is_template: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        # Convert the Group model to response format
        players_data = obj.get_players() if hasattr(obj, "get_players") else []
        players = [
            PlayerSchema(
                uuid=player.get("uuid", ""),
                username=player.get("username", ""),
                added_at=player.get("added_at"),
            )
            for player in players_data
        ]

        return cls(
            id=obj.id,
            name=obj.name,
            description=obj.description,
            type=obj.type,
            players=players,
            owner_id=obj.owner_id,
            is_template=obj.is_template,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class GroupListResponse(BaseModel):
    groups: List[GroupResponse]
    total: int


class PlayerAddRequest(BaseModel):
    uuid: Optional[str] = Field(
        None,
        min_length=32,
        max_length=36,
        description="Player UUID (optional if username provided)",
    )
    username: Optional[str] = Field(
        None,
        min_length=1,
        max_length=16,
        description="Player username (optional if UUID provided)",
    )
    player_name: Optional[str] = Field(
        None, min_length=1, max_length=16, description="Alias for username"
    )

    def model_post_init(self, __context):
        """Post-initialization validation to handle player_name alias and ensure at least one field is provided"""
        # Handle player_name alias
        if self.player_name and not self.username:
            self.username = self.player_name

        # Ensure at least one field is provided
        if not self.uuid and not self.username:
            raise ValueError("Either uuid or username (or player_name) must be provided")

    @field_validator("uuid")
    @classmethod
    def validate_uuid(cls, v):
        # Basic UUID format validation
        if v is None:
            return v
        import re

        if not re.match(
            r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$",
            v,
        ):
            raise ValueError("Invalid UUID format")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        # Minecraft username validation
        if v is None:
            return v
        import re

        if not re.match(r"^[a-zA-Z0-9_]{1,16}$", v):
            raise ValueError("Invalid Minecraft username format")
        return v

    @field_validator("player_name")
    @classmethod
    def validate_player_name(cls, v):
        # Minecraft username validation (same as username)
        if v is None:
            return v
        import re

        if not re.match(r"^[a-zA-Z0-9_]{1,16}$", v):
            raise ValueError("Invalid Minecraft username format")
        return v


class PlayerRemoveRequest(BaseModel):
    uuid: str = Field(..., min_length=32, max_length=36, description="Player UUID")

    @field_validator("uuid")
    @classmethod
    def validate_uuid(cls, v):
        # Basic UUID format validation
        import re

        if not re.match(
            r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$",
            v,
        ):
            raise ValueError("Invalid UUID format")
        return v


class ServerAttachRequest(BaseModel):
    server_id: int = Field(..., ge=1, description="Server ID to attach")
    priority: int = Field(0, ge=0, le=100, description="Attachment priority (0-100)")


class ServerDetachRequest(BaseModel):
    server_id: int = Field(..., ge=1, description="Server ID to detach")


class AttachedServerResponse(BaseModel):
    """Server information for group attachments"""

    id: int
    name: str
    status: str
    priority: int
    attached_at: str


class AttachedGroupResponse(BaseModel):
    """Group information for server attachments"""

    id: int
    name: str
    description: Optional[str]
    type: str
    priority: int
    attached_at: str
    player_count: int


class GroupServersResponse(BaseModel):
    group_id: int
    servers: List[AttachedServerResponse]


class ServerGroupsResponse(BaseModel):
    server_id: int
    groups: List[AttachedGroupResponse]
