"""Domain exceptions raised by the servers application service.

The router catches these and maps them to HTTPException. Where the
legacy `app.core.exceptions` module already names an analogous
exception, the domain class either re-exports or inherits from it so
the router's existing handlers keep working.

These types are introduced under #228 (PR 1/3) and are unwired from
the runtime in this PR; PR #2 rewires the callers.
"""

from typing import ClassVar

from app.core.exceptions import (
    ServerAccessDeniedException,
    ServerNotFoundException,
)


class ServerError(Exception):
    """Base exception for server-domain operations."""

    error_code: ClassVar[str] = "SERVER_ERROR"


class ServerNotFoundError(ServerError):
    """Raised when a requested server does not exist.

    Pairs with the legacy `ServerNotFoundException` (HTTP 404). The
    router/application boundary may catch either depending on context.
    """

    error_code: ClassVar[str] = "SERVER_NOT_FOUND"


class ServerAlreadyExistsError(ServerError):
    """Raised when a server with the requested name already exists.

    Unlike the legacy code, name uniqueness is a domain invariant
    rather than a database constraint — surface it as a domain
    exception so the application layer can react before staging
    inserts.
    """

    error_code: ClassVar[str] = "SERVER_ALREADY_EXISTS"


class ServerAccessError(ServerError):
    """Raised when the actor is not permitted to access the server.

    Pairs with the legacy `ServerAccessDeniedException` (HTTP 403).
    """

    error_code: ClassVar[str] = "SERVER_ACCESS_DENIED"


class InvalidServerStateError(ServerError):
    """Raised when an operation is attempted in an incompatible state.

    E.g. starting an already-running server, deleting a server with a
    live process attached. The router maps this to HTTP 409.
    """

    error_code: ClassVar[str] = "SERVER_INVALID_STATE"


# Re-export the legacy exceptions so callers migrating over to the
# domain module can `from app.servers.domain.exceptions import ...`
# without needing to keep two import paths.
__all__ = [
    "ServerError",
    "ServerNotFoundError",
    "ServerAlreadyExistsError",
    "ServerAccessError",
    "InvalidServerStateError",
    "ServerNotFoundException",
    "ServerAccessDeniedException",
]
