"""Global FastAPI exception handlers for domain exceptions.

Centralises the mapping from framework-agnostic domain exceptions
(raised by application-layer services) to HTTP responses. Introduced
under #273 so the ``AuthorizationService`` and other application
modules can ``raise`` plain Python exceptions without importing
``fastapi.HTTPException``.

The router-level ``try / except HTTPException: raise`` ladders are
extended to re-raise these domain types before the catch-all
``except Exception`` block so this handler is reached.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backups.domain.exceptions import (
    BackupNotFoundError,
    BackupParentServerMissingError,
)
from app.servers.domain.exceptions import ServerAccessError, ServerNotFoundError


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain-exception → HTTP-response handlers on ``app``."""

    @app.exception_handler(ServerNotFoundError)
    async def _server_not_found(request: Request, exc: ServerNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc) or "Server not found"},
        )

    @app.exception_handler(ServerAccessError)
    async def _server_access_denied(request: Request, exc: ServerAccessError):
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc) or "Access denied"},
        )

    @app.exception_handler(BackupNotFoundError)
    async def _backup_not_found(request: Request, exc: BackupNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc) or "Backup not found"},
        )

    @app.exception_handler(BackupParentServerMissingError)
    async def _backup_parent_missing(
        request: Request, exc: BackupParentServerMissingError
    ):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc) or "Server not found for backup"},
        )
