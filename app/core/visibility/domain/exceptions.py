"""Domain exceptions raised by the visibility application service.

The legacy `VisibilityService` raised plain `ValueError` for invalid
role configurations and `HTTPException` directly from inside the
service for missing-resource / wrong-visibility-type cases. The
migration to the hexagonal layout pulls FastAPI out of the application
layer entirely, so the service now raises the domain-specific errors
below and the API layer (`visibility_router.py`) translates them to
HTTP responses.

Legacy callers that catch `HTTPException` directly continue to work
because the router wraps the new errors in the same status codes.

``error_code`` (``ClassVar[str]``) feeds the global exception handler
(`app.core.error_handlers`) so :class:`app.core.error_schemas.ErrorResponse`
carries a stable machine identifier (Issue #76).
"""

from typing import ClassVar


class VisibilityError(Exception):
    """Base exception for the visibility domain."""

    error_code: ClassVar[str] = "VISIBILITY_ERROR"


class VisibilityNotFoundError(VisibilityError):
    """Raised when a referenced visibility row does not exist."""

    error_code: ClassVar[str] = "VISIBILITY_NOT_FOUND"


class InvalidVisibilityTypeError(VisibilityError):
    """Raised when an operation requires SPECIFIC_USERS visibility."""

    error_code: ClassVar[str] = "VISIBILITY_INVALID_TYPE"


class DuplicateGrantError(VisibilityError):
    """Raised when the same user already has an access grant."""

    error_code: ClassVar[str] = "VISIBILITY_DUPLICATE_GRANT"


__all__ = [
    "DuplicateGrantError",
    "InvalidVisibilityTypeError",
    "VisibilityError",
    "VisibilityNotFoundError",
]
