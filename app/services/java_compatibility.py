"""DEPRECATED: re-export shim. See `app.versions.application.java_compatibility`."""

from app.versions.application.java_compatibility import (
    JavaCompatibilityService,
    JavaVersionInfo,
    java_compatibility_service,
)

__all__ = [
    "JavaCompatibilityService",
    "JavaVersionInfo",
    "java_compatibility_service",
]
