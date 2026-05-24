"""Global FastAPI exception handlers for domain exceptions.

Centralises the mapping from framework-agnostic domain exceptions
(raised by application-layer services) to HTTP responses. Originally
introduced under #273 for four targeted handlers; expanded under
Issue #76 to cover all domain exception roots, validation errors, and
unhandled exceptions while emitting a standard
:class:`app.core.error_schemas.ErrorResponse` payload that **also**
carries the legacy ``detail`` key for backward compatibility with
existing frontend clients.

Contract: every response built here is a JSON object with at minimum
``error`` (machine code), ``message``, ``status_code``, ``timestamp``,
``request_id``, and the legacy ``detail`` mirror. ``details`` is
populated for 422 validation errors. For 422 responses specifically,
``detail`` is kept in FastAPI's legacy ``list[dict]`` shape (rather
than the usual string mirror of ``message``) so frontend code that
iterates per-field errors (``response.detail.map(...)``) keeps
working unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.backups.domain.exceptions import (
    BackupDomainError,
    BackupError,
    BackupNotFoundError,
    BackupParentServerMissingError,
    BackupScheduleAlreadyExistsError,
    BackupScheduleNotFoundError,
)
from app.core.error_schemas import ErrorDetail, ErrorResponse
from app.core.exceptions import (
    APIException,
    DiskSpaceError,
    FileAccessDeniedError,
    FileAlreadyExistsError,
    FileMissingError,
    FileOperationException,
    FileTooLargeError,
    InvalidFileTypeError,
)
from app.core.visibility.domain.exceptions import (
    DuplicateGrantError,
    InvalidVisibilityTypeError,
    VisibilityError,
    VisibilityNotFoundError,
)
from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupError,
    GroupHasAttachmentsError,
    GroupNotFoundError,
    PlayerNotFoundInGroup,
    ServerGroupAttachmentExistsError,
    ServerGroupAttachmentNotFoundError,
    ServerNotFoundForAttachment,
)
from app.servers.domain.exceptions import (
    InvalidServerStateError,
    JavaCompatibilityError,
    NoAvailablePortError,
    ServerAccessError,
    ServerAlreadyExistsError,
    ServerCreationRollbackError,
    ServerDirectoryCreationError,
    ServerError,
    ServerJarDownloadError,
    ServerNameConflictError,
    ServerNotFoundError,
    ServerPortConflictError,
    UnsupportedMinecraftVersionError,
)

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> Optional[str]:
    """Pull the correlation ID set by ``AuditMiddleware`` (if mounted).

    Returns ``None`` rather than raising when middleware did not run
    (e.g. some unit tests bypass the middleware stack); the handler
    leaves the field empty in that case.
    """
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "request_id", None)


def _build_payload(
    *,
    request: Request,
    error_code: str,
    message: str,
    status_code: int,
    details: Optional[List[ErrorDetail]] = None,
) -> Dict[str, Any]:
    """Assemble the standard error JSON payload.

    Returns a plain dict (not an :class:`ErrorResponse`) so callers can
    hand it straight to :class:`JSONResponse` without an extra Pydantic
    round-trip. The shape mirrors :class:`ErrorResponse` exactly and
    must stay in sync.
    """
    payload = ErrorResponse(
        error=error_code,
        message=message,
        status_code=status_code,
        details=details,
        request_id=_request_id(request),
        timestamp=datetime.now(timezone.utc),
        # Mirror ``message`` into ``detail`` so existing frontend code
        # that reads ``response.detail`` continues to work unchanged.
        detail=message,
    )
    return payload.model_dump(mode="json", exclude_none=False)


def _domain_response(
    request: Request,
    exc: Exception,
    *,
    status_code: int,
    default_message: str,
    fallback_code: str,
) -> JSONResponse:
    """Render a domain-exception payload (uses ``error_code`` if defined).

    If the exception exposes an ``extra_details()`` method (Issue #33
    introduced it on the new server-creation exceptions so structured
    field-level context can travel through the same response envelope
    used by 422 validation errors) the returned :class:`ErrorDetail`
    list is forwarded into the response ``details`` array. Exceptions
    that do not implement the method fall through to the legacy single
    ``message`` shape unchanged.
    """
    error_code = getattr(exc, "error_code", fallback_code) or fallback_code
    message = str(exc) or default_message
    extra_details_fn = getattr(exc, "extra_details", None)
    details: Optional[List[ErrorDetail]] = None
    if callable(extra_details_fn):
        try:
            collected = extra_details_fn()
            if collected:
                details = list(collected)
        except Exception:  # pragma: no cover - defensive
            logger.exception("extra_details_failed", extra={"error_code": error_code})
    return JSONResponse(
        status_code=status_code,
        content=_build_payload(
            request=request,
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain-exception → HTTP-response handlers on ``app``."""

    # --- Servers ----------------------------------------------------

    @app.exception_handler(ServerNotFoundError)
    async def _server_not_found(request: Request, exc: ServerNotFoundError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Server not found",
            fallback_code="SERVER_NOT_FOUND",
        )

    @app.exception_handler(ServerAccessError)
    async def _server_access_denied(request: Request, exc: ServerAccessError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_403_FORBIDDEN,
            default_message="Access denied",
            fallback_code="SERVER_ACCESS_DENIED",
        )

    @app.exception_handler(ServerAlreadyExistsError)
    async def _server_already_exists(request: Request, exc: ServerAlreadyExistsError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Server already exists",
            fallback_code="SERVER_ALREADY_EXISTS",
        )

    @app.exception_handler(InvalidServerStateError)
    async def _server_invalid_state(request: Request, exc: InvalidServerStateError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Server is in an invalid state for this operation",
            fallback_code="SERVER_INVALID_STATE",
        )

    # --- Issue #33: actionable server-creation errors ----------------
    # Registered before the generic ``ServerError`` handler so the more
    # specific code/status pair wins (FastAPI matches on exception
    # type, not order, but registering the specific handler ensures
    # the dispatcher resolves it as the canonical mapping for that
    # type — important when subclass relationships exist, e.g.
    # ``ServerNameConflictError`` extends ``ServerAlreadyExistsError``
    # which the dispatcher would otherwise short-circuit on).

    @app.exception_handler(ServerNameConflictError)
    async def _server_name_conflict(request: Request, exc: ServerNameConflictError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Server name already taken",
            fallback_code="SERVER_NAME_CONFLICT",
        )

    @app.exception_handler(ServerPortConflictError)
    async def _server_port_conflict(request: Request, exc: ServerPortConflictError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Port already in use by another server",
            fallback_code="SERVER_PORT_CONFLICT",
        )

    @app.exception_handler(NoAvailablePortError)
    async def _server_no_port_available(request: Request, exc: NoAvailablePortError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="No available port in the searched range",
            fallback_code="SERVER_NO_PORT_AVAILABLE",
        )

    @app.exception_handler(UnsupportedMinecraftVersionError)
    async def _server_unsupported_version(
        request: Request, exc: UnsupportedMinecraftVersionError
    ):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_400_BAD_REQUEST,
            default_message="Minecraft version is not supported",
            fallback_code="SERVER_UNSUPPORTED_VERSION",
        )

    @app.exception_handler(JavaCompatibilityError)
    async def _server_java_incompatible(request: Request, exc: JavaCompatibilityError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_400_BAD_REQUEST,
            default_message="No compatible Java runtime found",
            fallback_code="SERVER_JAVA_INCOMPATIBLE",
        )

    @app.exception_handler(ServerJarDownloadError)
    async def _server_jar_download_failed(request: Request, exc: ServerJarDownloadError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
            default_message="Failed to download server JAR from upstream",
            fallback_code="SERVER_JAR_DOWNLOAD_FAILED",
        )

    @app.exception_handler(ServerDirectoryCreationError)
    async def _server_directory_failed(
        request: Request, exc: ServerDirectoryCreationError
    ):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Failed to create server directory",
            fallback_code="SERVER_DIRECTORY_FAILED",
        )

    @app.exception_handler(ServerCreationRollbackError)
    async def _server_rollback_failed(request: Request, exc: ServerCreationRollbackError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Server creation failed and rollback did not complete",
            fallback_code="SERVER_CREATION_ROLLBACK_FAILED",
        )

    @app.exception_handler(ServerError)
    async def _server_error(request: Request, exc: ServerError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Server operation failed",
            fallback_code="SERVER_ERROR",
        )

    # --- Backups ----------------------------------------------------

    @app.exception_handler(BackupNotFoundError)
    async def _backup_not_found(request: Request, exc: BackupNotFoundError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Backup not found",
            fallback_code="BACKUP_NOT_FOUND",
        )

    @app.exception_handler(BackupParentServerMissingError)
    async def _backup_parent_missing(
        request: Request, exc: BackupParentServerMissingError
    ):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Server not found for backup",
            fallback_code="BACKUP_PARENT_SERVER_MISSING",
        )

    @app.exception_handler(BackupScheduleNotFoundError)
    async def _backup_schedule_not_found(
        request: Request, exc: BackupScheduleNotFoundError
    ):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Backup schedule not found",
            fallback_code="BACKUP_SCHEDULE_NOT_FOUND",
        )

    @app.exception_handler(BackupScheduleAlreadyExistsError)
    async def _backup_schedule_exists(
        request: Request, exc: BackupScheduleAlreadyExistsError
    ):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Backup schedule already exists",
            fallback_code="BACKUP_SCHEDULE_ALREADY_EXISTS",
        )

    @app.exception_handler(BackupDomainError)
    async def _backup_domain_error(request: Request, exc: BackupDomainError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Backup operation failed",
            fallback_code="BACKUP_DOMAIN_ERROR",
        )

    @app.exception_handler(BackupError)
    async def _backup_error(request: Request, exc: BackupError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Backup operation failed",
            fallback_code="BACKUP_ERROR",
        )

    # --- Groups -----------------------------------------------------

    @app.exception_handler(GroupNotFoundError)
    async def _group_not_found(request: Request, exc: GroupNotFoundError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Group not found",
            fallback_code="GROUP_NOT_FOUND",
        )

    @app.exception_handler(GroupAccessError)
    async def _group_access_denied(request: Request, exc: GroupAccessError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_403_FORBIDDEN,
            default_message="Access denied",
            fallback_code="GROUP_ACCESS_DENIED",
        )

    @app.exception_handler(GroupAlreadyExistsError)
    async def _group_already_exists(request: Request, exc: GroupAlreadyExistsError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_400_BAD_REQUEST,
            default_message="Group already exists",
            fallback_code="GROUP_ALREADY_EXISTS",
        )

    @app.exception_handler(GroupHasAttachmentsError)
    async def _group_has_attachments(request: Request, exc: GroupHasAttachmentsError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Group has active server attachments",
            fallback_code="GROUP_HAS_ATTACHMENTS",
        )

    @app.exception_handler(PlayerNotFoundInGroup)
    async def _player_not_in_group(request: Request, exc: PlayerNotFoundInGroup):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Player not found in group",
            fallback_code="GROUP_PLAYER_NOT_FOUND",
        )

    @app.exception_handler(ServerNotFoundForAttachment)
    async def _attach_server_missing(request: Request, exc: ServerNotFoundForAttachment):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Target server not found",
            fallback_code="GROUP_ATTACH_SERVER_NOT_FOUND",
        )

    @app.exception_handler(ServerGroupAttachmentExistsError)
    async def _attachment_exists(request: Request, exc: ServerGroupAttachmentExistsError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="Group is already attached to this server",
            fallback_code="GROUP_ATTACHMENT_EXISTS",
        )

    @app.exception_handler(ServerGroupAttachmentNotFoundError)
    async def _attachment_not_found(
        request: Request, exc: ServerGroupAttachmentNotFoundError
    ):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Group is not attached to this server",
            fallback_code="GROUP_ATTACHMENT_NOT_FOUND",
        )

    @app.exception_handler(GroupError)
    async def _group_error(request: Request, exc: GroupError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Group operation failed",
            fallback_code="GROUP_ERROR",
        )

    # --- Visibility -------------------------------------------------

    @app.exception_handler(VisibilityNotFoundError)
    async def _visibility_not_found(request: Request, exc: VisibilityNotFoundError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_404_NOT_FOUND,
            default_message="Visibility record not found",
            fallback_code="VISIBILITY_NOT_FOUND",
        )

    @app.exception_handler(InvalidVisibilityTypeError)
    async def _visibility_invalid_type(request: Request, exc: InvalidVisibilityTypeError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_400_BAD_REQUEST,
            default_message="Operation requires SPECIFIC_USERS visibility",
            fallback_code="VISIBILITY_INVALID_TYPE",
        )

    @app.exception_handler(DuplicateGrantError)
    async def _visibility_duplicate_grant(request: Request, exc: DuplicateGrantError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_409_CONFLICT,
            default_message="User already has access grant",
            fallback_code="VISIBILITY_DUPLICATE_GRANT",
        )

    @app.exception_handler(VisibilityError)
    async def _visibility_error(request: Request, exc: VisibilityError):
        return _domain_response(
            request,
            exc,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            default_message="Visibility operation failed",
            fallback_code="VISIBILITY_ERROR",
        )

    # --- File operations (Issue #35) --------------------------------
    # Each file subclass declares its own ``error_code`` and the parent
    # ``APIException`` already carries the status code; registering a
    # dedicated handler per subclass keeps the wire-level mapping
    # explicit and makes the test surface for the file taxonomy
    # discoverable in isolation.

    def _api_exception_response(request: Request, exc: APIException) -> JSONResponse:
        extra_details_fn = getattr(exc, "extra_details", None)
        details: Optional[List[ErrorDetail]] = None
        if callable(extra_details_fn):
            try:
                collected = extra_details_fn()
                if collected:
                    details = list(collected)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "extra_details_failed",
                    extra={"error_code": getattr(exc, "error_code", None)},
                )
        return JSONResponse(
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
            content=_build_payload(
                request=request,
                error_code=getattr(exc, "error_code", "API_ERROR") or "API_ERROR",
                message=str(exc.detail) if exc.detail else "API error",
                status_code=exc.status_code,
                details=details,
            ),
        )

    @app.exception_handler(FileMissingError)
    async def _file_missing(request: Request, exc: FileMissingError):
        return _api_exception_response(request, exc)

    @app.exception_handler(FileAccessDeniedError)
    async def _file_access_denied(request: Request, exc: FileAccessDeniedError):
        return _api_exception_response(request, exc)

    @app.exception_handler(FileTooLargeError)
    async def _file_too_large(request: Request, exc: FileTooLargeError):
        return _api_exception_response(request, exc)

    @app.exception_handler(InvalidFileTypeError)
    async def _file_invalid_type(request: Request, exc: InvalidFileTypeError):
        return _api_exception_response(request, exc)

    @app.exception_handler(DiskSpaceError)
    async def _file_disk_space(request: Request, exc: DiskSpaceError):
        return _api_exception_response(request, exc)

    @app.exception_handler(FileAlreadyExistsError)
    async def _file_already_exists(request: Request, exc: FileAlreadyExistsError):
        return _api_exception_response(request, exc)

    @app.exception_handler(FileOperationException)
    async def _file_operation_failed(request: Request, exc: FileOperationException):
        # Generic fallback (500) — subclass handlers above already
        # capture the targeted statuses.
        return _api_exception_response(request, exc)

    # --- APIException (legacy HTTPException subclass) ---------------

    @app.exception_handler(APIException)
    async def _api_exception(request: Request, exc: APIException):
        # `APIException` already subclasses `HTTPException` and FastAPI's
        # default handler would render `{"detail": ...}`. Override so
        # the new structured payload is emitted while still preserving
        # the legacy `detail` field for back-compat. Forwards
        # ``extra_details()`` for subclasses (e.g. file operation
        # exceptions under Issue #35) that surface structured context.
        return _api_exception_response(request, exc)

    # --- Validation (422) -------------------------------------------

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        details: List[ErrorDetail] = []
        for err in exc.errors():
            loc = err.get("loc") or ()
            # Drop the leading scope segment ("body" / "query" / "path")
            # for a cleaner field path. Cast all segments to str so JSON
            # serialisation never trips on numeric list indices.
            field_path = (
                ".".join(str(seg) for seg in loc[1:])
                if len(loc) > 1
                else (str(loc[0]) if loc else None)
            )
            details.append(
                ErrorDetail(
                    field=field_path,
                    message=str(err.get("msg", "validation error")),
                    code=str(err.get("type")) if err.get("type") is not None else None,
                )
            )
        payload = _build_payload(
            request=request,
            error_code="VALIDATION_ERROR",
            message="Request validation failed",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )
        # Backward-compat: FastAPI's default 422 handler renders
        # ``detail`` as a ``list[dict]`` of per-field errors. Existing
        # frontend code commonly does e.g. ``response.detail.map(...)``
        # which would break if we mirrored ``message`` (a string) into
        # ``detail`` like every other status. Preserve the legacy
        # ``list[dict]`` shape here; the structured per-field errors are
        # additionally surfaced in the new ``details`` field above.
        payload["detail"] = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=payload,
        )

    # --- HTTPException fallback -------------------------------------

    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException):
        # Use the explicit code when the raiser is an APIException
        # subclass (handled above already), otherwise synthesise one
        # from the status code so the wire still has a stable code.
        error_code = getattr(exc, "error_code", None) or f"HTTP_{exc.status_code}"
        message = str(exc.detail) if exc.detail else f"HTTP {exc.status_code}"
        return JSONResponse(
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
            content=_build_payload(
                request=request,
                error_code=error_code,
                message=message,
                status_code=exc.status_code,
            ),
        )

    # --- Last-resort fallback ---------------------------------------

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception):
        logger.exception(
            "unhandled_exception",
            extra={
                "event": "unhandled_exception",
                "path": request.url.path,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_build_payload(
                request=request,
                error_code="INTERNAL_ERROR",
                message="An internal server error occurred",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
        )
