"""DEPRECATED: re-export shim. See `app.versions.application.version_manager`."""

from app.versions.application.version_manager import (
    MinecraftVersionManager,
    VersionInfo,
    minecraft_version_manager,
)

__all__ = ["MinecraftVersionManager", "VersionInfo", "minecraft_version_manager"]
