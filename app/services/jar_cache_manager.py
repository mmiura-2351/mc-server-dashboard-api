"""DEPRECATED: re-export shim. See `app.versions.application.jar_cache_manager`."""

from app.versions.application.jar_cache_manager import (
    JarCacheManager,
    jar_cache_manager,
)

__all__ = ["JarCacheManager", "jar_cache_manager"]
