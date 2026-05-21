"""Domain exceptions raised by the templates application service.

Migrated from `app.services.template_service` so callers and tests can
import directly from the domain layer without going through the legacy
shim. The shim re-exports these names for backward compatibility.
"""


class TemplateError(Exception):
    """Base exception for template operations."""


class TemplateNotFoundError(TemplateError):
    """Raised when a referenced template (or source server) does not exist."""


class TemplateCreationError(TemplateError):
    """Raised when template creation fails (e.g. missing server directory)."""


class TemplateAccessError(TemplateError):
    """Raised when a viewer lacks permission to read or modify a template."""
