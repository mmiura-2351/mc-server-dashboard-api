from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.servers.models import ServerStatus, ServerType


class ServerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Server name")
    description: Optional[str] = Field(
        None, max_length=500, description="Server description"
    )
    minecraft_version: str = Field(
        ..., min_length=1, max_length=20, description="Minecraft version (e.g., 1.20.1)"
    )
    server_type: ServerType = Field(
        ..., description="Server type: vanilla, forge, or paper"
    )
    port: int = Field(25565, ge=1024, le=65535, description="Server port")
    max_memory: int = Field(1024, ge=512, le=16384, description="Maximum memory in MB")
    max_players: int = Field(20, ge=1, le=100, description="Maximum number of players")
    template_id: Optional[int] = Field(
        None, description="Template ID to use for server creation"
    )

    # Server-specific configuration overrides
    server_properties: Optional[Dict[str, Any]] = Field(
        None, description="Custom server.properties overrides"
    )

    # Group attachments for new server
    attach_groups: Optional[Dict[str, List[int]]] = Field(
        None,
        description="Groups to attach: {'op_groups': [1,2], 'whitelist_groups': [3,4]}",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Server name cannot be empty")
        # Only allow alphanumeric, spaces, hyphens, underscores
        import re

        if not re.match(r"^[a-zA-Z0-9\s\-_]+$", v):
            raise ValueError("Server name contains invalid characters")
        return v.strip()

    @field_validator("minecraft_version")
    @classmethod
    def validate_minecraft_version(cls, v):
        # Basic version format validation (e.g., 1.20.1, 1.19.4)
        import re

        from packaging import version

        if not re.match(r"^\d+\.\d+(\.\d+)?$", v):
            raise ValueError("Invalid Minecraft version format. Use format like 1.20.1")

        # Check minimum version requirement (1.8+)
        try:
            parsed_version = version.Version(v)
            min_version = version.Version("1.8.0")
            if parsed_version < min_version:
                raise ValueError("Minimum supported Minecraft version is 1.8")
        except Exception as e:
            raise ValueError(f"Invalid version format: {e}")

        return v

    @field_validator("server_properties")
    @classmethod
    def validate_server_properties(cls, v):
        if v is None:
            return v

        # Validate common server.properties keys
        valid_keys = {
            "difficulty",
            "gamemode",
            "hardcore",
            "pvp",
            "spawn_protection",
            "enable_command_block",
            "allow_flight",
            "spawn_monsters",
            "spawn_animals",
            "spawn_npcs",
            "generate_structures",
            "level_name",
            "level_seed",
            "level_type",
            "motd",
            "online_mode",
            "white_list",
            "enforce_whitelist",
            "view_distance",
            "simulation_distance",
            "op_permission_level",
        }

        for key in v.keys():
            if key.replace("-", "_") not in valid_keys:
                raise ValueError(f"Unknown server property: {key}")

        return v

    @field_validator("attach_groups")
    @classmethod
    def validate_attach_groups(cls, v):
        if v is None:
            return v

        valid_keys = {"op_groups", "whitelist_groups"}
        for key in v.keys():
            if key not in valid_keys:
                raise ValueError(
                    f"Invalid group type: {key}. Must be one of {valid_keys}"
                )

            if not isinstance(v[key], list):
                raise ValueError(f"{key} must be a list of group IDs")

            for group_id in v[key]:
                if not isinstance(group_id, int) or group_id <= 0:
                    raise ValueError(f"Invalid group ID in {key}: {group_id}")

        return v

    @model_validator(mode="after")
    def validate_server_type_version_compatibility(self):
        server_type = self.server_type
        minecraft_version = self.minecraft_version

        if not server_type or not minecraft_version:
            return self

        # All server types now support 1.8+ with dynamic version management
        # Specific compatibility will be checked by the version manager
        try:
            from packaging import version

            parsed_version = version.Version(minecraft_version)
            min_version = version.Version("1.8.0")

            if parsed_version < min_version:
                raise ValueError(
                    f"All server types require Minecraft 1.8 or higher. Got: {minecraft_version}"
                )

        except Exception as e:
            raise ValueError(f"Version validation failed: {e}")

        return self


class ServerUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    max_memory: Optional[int] = Field(None, ge=512, le=16384)
    max_players: Optional[int] = Field(None, ge=1, le=100)
    server_properties: Optional[Dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Server name cannot be empty")
        return v.strip() if v else v


class ServerConfigurationResponse(BaseModel):
    id: int
    configuration_key: str
    configuration_value: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServerResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    minecraft_version: str
    server_type: ServerType
    status: ServerStatus
    directory_path: str
    port: int
    max_memory: int
    max_players: int
    owner_id: int
    template_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    # Additional runtime information
    process_info: Optional[Dict[str, Any]] = None
    configurations: List[ServerConfigurationResponse] = []

    model_config = {"from_attributes": True}


class ServerListResponse(BaseModel):
    servers: List[ServerResponse]
    total: int
    page: int
    size: int


class ServerStatusResponse(BaseModel):
    server_id: int
    status: ServerStatus
    process_info: Optional[Dict[str, Any]] = None


class ServerCommandRequest(BaseModel):
    command: str = Field(
        ..., min_length=1, max_length=500, description="Command to send to server"
    )

    @field_validator("command")
    @classmethod
    def validate_command(cls, v):
        # Basic command validation - prevent dangerous commands
        dangerous_commands = ["stop", "restart", "shutdown"]
        if v.strip().lower() in dangerous_commands:
            raise ValueError(f'Command "{v}" is not allowed through this endpoint')
        return v.strip()


class ServerLogsResponse(BaseModel):
    server_id: int
    logs: List[str]
    total_lines: int


class MinecraftVersionInfo(BaseModel):
    version: str
    server_type: ServerType
    download_url: str
    is_supported: bool = True
    release_date: Optional[datetime] = None
    is_stable: bool = True
    build_number: Optional[int] = None


class SupportedVersionsResponse(BaseModel):
    versions: List[MinecraftVersionInfo]


class ServerCreationProgress(BaseModel):
    """Progress tracking for server creation"""

    step: str
    progress: int  # 0-100
    message: str
    completed: bool = False
    error: Optional[str] = None


class ServerImportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Server name")
    description: Optional[str] = Field(
        None, max_length=500, description="Server description"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Server name cannot be empty")
        import re

        if not re.match(r"^[a-zA-Z0-9\s\-_]+$", v):
            raise ValueError("Server name contains invalid characters")
        return v.strip()


class ServerExportResponse(BaseModel):
    export_id: str
    server_id: int
    server_name: str
    file_size: int
    created_at: datetime
    download_url: str
