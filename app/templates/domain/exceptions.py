"""Domain exceptions raised by the templates application service.

Migrated from `app.services.template_service` so callers and tests can
import directly from the domain layer without going through the legacy
shim. The shim re-exports these names for backward compatibility.

``error_code`` (``ClassVar[str]``) feeds the global exception handler
(`app.core.error_handlers`) so :class:`app.core.error_schemas.ErrorResponse`
carries a stable machine identifier (Issue #76).
"""

from typing import ClassVar


class TemplateError(Exception):
    """Base exception for template operations."""

    error_code: ClassVar[str] = "TEMPLATE_ERROR"


class TemplateNotFoundError(TemplateError):
    """Raised when a referenced template (or source server) does not exist."""

    error_code: ClassVar[str] = "TEMPLATE_NOT_FOUND"


class TemplateCreationError(TemplateError):
    """Raised when template creation fails (e.g. missing server directory)."""

    error_code: ClassVar[str] = "TEMPLATE_CREATION_FAILED"


class TemplateAccessError(TemplateError):
    """Raised when a viewer lacks permission to read or modify a template."""

    error_code: ClassVar[str] = "TEMPLATE_ACCESS_DENIED"
