"""DEPRECATED: re-export shim for `app.servers.application.service`.

Merged into `app/servers/application/service.py` under #228 PR 2c (the
move includes the #257 fix that deletes the legacy
`ServerTemplateService.apply_template` and the #259 fix that routes
group attachments through the correct `attach_group_to_server` call).
Import from `app.servers.application.service` directly in new code.

Extra module-level re-exports (`ServerResponse`, `PathValidator`,
`handle_file_error`, `Path`) are present for the legacy unit tests
that patch them via `patch("app.servers.service.X")`.
"""

from pathlib import Path

from app.core.exceptions import handle_file_error
from app.core.security import PathValidator
from app.servers.application.service import (
    ServerDatabaseService,
    ServerFileSystemService,
    ServerJarService,
    ServerSecurityValidator,
    ServerService,
    ServerValidationService,
)
from app.servers.application.service import (
    _server_service_legacy as server_service,
)
from app.servers.schemas import ServerResponse

__all__ = [
    "Path",
    "PathValidator",
    "ServerDatabaseService",
    "ServerFileSystemService",
    "ServerJarService",
    "ServerResponse",
    "ServerSecurityValidator",
    "ServerService",
    "ServerValidationService",
    "handle_file_error",
    "server_service",
]
