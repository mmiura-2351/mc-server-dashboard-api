"""Domain exceptions raised by the servers application service.

The router catches these and maps them to HTTPException. Where the
legacy `app.core.exceptions` module already names an analogous
exception, the domain class either re-exports or inherits from it so
the router's existing handlers keep working.

These types are introduced under #228 (PR 1/3) and are unwired from
the runtime in this PR; PR #2 rewires the callers.

Issue #33 (actionable server-creation errors): each new fine-grained
exception below carries an ``error_code`` and may optionally expose
structured field-level context through ``extra_details()``. The global
exception handler in :mod:`app.core.error_handlers` reads
``extra_details()`` (when present) and surfaces it through the
:class:`~app.core.error_schemas.ErrorResponse.details` array so the
frontend can render actionable, code-driven UI without parsing English
prose.
"""

from typing import ClassVar, List, Optional

from app.core.error_schemas import ErrorDetail
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


# ---------------------------------------------------------------------------
# Issue #33: actionable server-creation errors
# ---------------------------------------------------------------------------


class ServerNameConflictError(ServerAlreadyExistsError):
    """Raised when the requested server name collides with an existing one.

    Inherits from :class:`ServerAlreadyExistsError` so existing
    callers that pattern-match on the parent type (and the global
    handler that maps it to HTTP 409) continue to work; the more
    specific ``error_code`` ``SERVER_NAME_CONFLICT`` is surfaced
    through the response payload so the frontend can target the
    error precisely.
    """

    error_code: ClassVar[str] = "SERVER_NAME_CONFLICT"

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"A server named '{name}' already exists. "
            "Choose a different name or delete the existing server first."
        )

    def extra_details(self) -> List[ErrorDetail]:
        return [
            ErrorDetail(
                field="name",
                message=f"'{self.name}' is already taken",
                code="SERVER_NAME_TAKEN",
            )
        ]


class ServerPortConflictError(ServerError):
    """Raised when the requested port is already used by an active server.

    Carries the conflicting server name and a small list of suggested
    free ports the caller may try instead. Mapped to HTTP 409.
    """

    error_code: ClassVar[str] = "SERVER_PORT_CONFLICT"

    def __init__(
        self,
        port: int,
        conflicting_server: Optional[str] = None,
        suggested_ports: Optional[List[int]] = None,
    ) -> None:
        self.port = port
        self.conflicting_server = conflicting_server
        self.suggested_ports = list(suggested_ports or [])
        msg = (
            f"Port {port} is already in use"
            + (f" by server '{conflicting_server}'." if conflicting_server else ".")
            + " Choose a different port"
        )
        if self.suggested_ports:
            msg += f" (suggested: {', '.join(str(p) for p in self.suggested_ports)})."
        else:
            msg += "."
        super().__init__(msg)

    def extra_details(self) -> List[ErrorDetail]:
        details: List[ErrorDetail] = [
            ErrorDetail(
                field="port",
                message=(
                    f"Port {self.port} is already in use"
                    + (
                        f" by '{self.conflicting_server}'"
                        if self.conflicting_server
                        else ""
                    )
                ),
                code="PORT_IN_USE",
            )
        ]
        for suggestion in self.suggested_ports:
            details.append(
                ErrorDetail(
                    field="port",
                    message=str(suggestion),
                    code="PORT_SUGGESTION",
                )
            )
        return details


class UnsupportedMinecraftVersionError(ServerError):
    """Raised when the requested Minecraft version is unsupported.

    Mapped to HTTP 400. Carries the offending version and server type
    so the frontend can present an inline message on the version
    selector.
    """

    error_code: ClassVar[str] = "SERVER_UNSUPPORTED_VERSION"

    def __init__(self, version: str, server_type: str) -> None:
        self.version = version
        self.server_type = server_type
        super().__init__(
            f"Minecraft version '{version}' is not supported for server type "
            f"'{server_type}'. Refresh the supported-versions list or pick "
            "another version (minimum 1.8)."
        )

    def extra_details(self) -> List[ErrorDetail]:
        return [
            ErrorDetail(
                field="minecraft_version",
                message=(
                    f"Version '{self.version}' is not supported for "
                    f"server type '{self.server_type}'"
                ),
                code="VERSION_NOT_SUPPORTED",
            ),
            ErrorDetail(
                field=None,
                message="Refresh the supported-versions list or pick another version",
                code="RESOLUTION_STEP",
            ),
        ]


class JavaCompatibilityError(ServerError):
    """Raised when no compatible Java runtime is available.

    Mapped to HTTP 400. Carries the Minecraft version, the Java major
    version the request requires, and the list of available Java major
    versions so the frontend can render an actionable installation
    hint.
    """

    error_code: ClassVar[str] = "SERVER_JAVA_INCOMPATIBLE"

    def __init__(
        self,
        minecraft_version: str,
        required_java: Optional[int],
        available_java: Optional[List[int]] = None,
        message: Optional[str] = None,
    ) -> None:
        self.minecraft_version = minecraft_version
        self.required_java = required_java
        self.available_java = list(available_java or [])
        if message is None:
            if self.available_java:
                message = (
                    f"Minecraft {minecraft_version} requires Java "
                    f"{required_java}; only Java "
                    f"{self.available_java} are available. "
                    f"Install Java {required_java} or set "
                    f"JAVA_{required_java}_PATH in your environment."
                )
            else:
                message = (
                    "No Java installations were detected. Install an OpenJDK "
                    "build that matches the target Minecraft version and "
                    "ensure the java binary is on PATH."
                )
        super().__init__(message)

    def extra_details(self) -> List[ErrorDetail]:
        details: List[ErrorDetail] = [
            ErrorDetail(
                field="minecraft_version",
                message=(
                    f"Requires Java {self.required_java}"
                    if self.required_java is not None
                    else "Requires a compatible Java runtime"
                ),
                code="JAVA_REQUIRED",
            ),
        ]
        for ver in self.available_java:
            details.append(
                ErrorDetail(
                    field=None,
                    message=str(ver),
                    code="JAVA_AVAILABLE",
                )
            )
        if self.required_java is not None:
            details.append(
                ErrorDetail(
                    field=None,
                    message=(
                        f"Install Java {self.required_java} or set "
                        f"JAVA_{self.required_java}_PATH in .env"
                    ),
                    code="RESOLUTION_STEP",
                )
            )
        return details


class ServerJarDownloadError(ServerError):
    """Raised when the server JAR download or integrity check fails.

    Mapped to HTTP 502 — the dependency the API relies on (Mojang /
    Paper / Forge upstream) misbehaved. Carries a structured
    ``reason`` (``network`` / ``corrupted`` / ``upstream <status>``)
    and a ``retry_hint`` the caller can render verbatim.
    """

    error_code: ClassVar[str] = "SERVER_JAR_DOWNLOAD_FAILED"

    def __init__(
        self,
        server_type: str,
        version: str,
        reason: str,
        retry_hint: Optional[str] = None,
    ) -> None:
        self.server_type = server_type
        self.version = version
        self.reason = reason
        self.retry_hint = retry_hint
        msg = f"Failed to download {server_type} {version} JAR ({reason})."
        if retry_hint:
            msg += f" {retry_hint}"
        super().__init__(msg)

    def extra_details(self) -> List[ErrorDetail]:
        details: List[ErrorDetail] = [
            ErrorDetail(
                field=None,
                message=self.reason,
                code="JAR_DOWNLOAD_REASON",
            )
        ]
        if self.retry_hint:
            details.append(
                ErrorDetail(
                    field=None,
                    message=self.retry_hint,
                    code="RESOLUTION_STEP",
                )
            )
        return details


class ServerDirectoryCreationError(ServerError):
    """Raised when the on-disk server directory cannot be created.

    Mapped to HTTP 500. Distinct from
    :class:`~app.core.exceptions.FileOperationException` so the
    frontend can render a directory-specific message.
    """

    error_code: ClassVar[str] = "SERVER_DIRECTORY_FAILED"

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"Failed to create server directory for '{name}': {reason}")

    def extra_details(self) -> List[ErrorDetail]:
        return [
            ErrorDetail(
                field=None,
                message=self.reason,
                code="DIRECTORY_CREATION_REASON",
            ),
            ErrorDetail(
                field=None,
                message=(
                    "Check filesystem permissions on the servers/ directory and retry."
                ),
                code="RESOLUTION_STEP",
            ),
        ]


class ServerCreationRollbackError(ServerError):
    """Raised when cleanup after a failed server creation itself fails.

    Mapped to HTTP 500. Surfaces both the original failure stage and
    the rollback error so an operator can intervene manually (e.g.
    remove a stranded ``servers/<name>`` directory).
    """

    error_code: ClassVar[str] = "SERVER_CREATION_ROLLBACK_FAILED"

    def __init__(self, stage: str, original_error: str) -> None:
        self.stage = stage
        self.original_error = original_error
        super().__init__(
            f"Server creation failed at stage '{stage}' and cleanup did not "
            f"complete cleanly: {original_error}"
        )

    def extra_details(self) -> List[ErrorDetail]:
        return [
            ErrorDetail(
                field=None,
                message=self.stage,
                code="ROLLBACK_STAGE",
            ),
            ErrorDetail(
                field=None,
                message=self.original_error,
                code="ROLLBACK_ORIGINAL_ERROR",
            ),
        ]


# Re-export the legacy exceptions so callers migrating over to the
# domain module can `from app.servers.domain.exceptions import ...`
# without needing to keep two import paths.
__all__ = [
    "ServerError",
    "ServerNotFoundError",
    "ServerAlreadyExistsError",
    "ServerAccessError",
    "InvalidServerStateError",
    # Issue #33 — actionable creation errors
    "ServerNameConflictError",
    "ServerPortConflictError",
    "UnsupportedMinecraftVersionError",
    "JavaCompatibilityError",
    "ServerJarDownloadError",
    "ServerDirectoryCreationError",
    "ServerCreationRollbackError",
    # Legacy re-exports
    "ServerNotFoundException",
    "ServerAccessDeniedException",
]
