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
"""


class VisibilityError(Exception):
    """Base exception for the visibility domain."""


class VisibilityNotFoundError(VisibilityError):
    """Raised when a referenced visibility row does not exist."""


class InvalidVisibilityTypeError(VisibilityError):
    """Raised when an operation requires SPECIFIC_USERS visibility."""


class DuplicateGrantError(VisibilityError):
    """Raised when the same user already has an access grant."""


__all__ = [
    "DuplicateGrantError",
    "InvalidVisibilityTypeError",
    "VisibilityError",
    "VisibilityNotFoundError",
]
