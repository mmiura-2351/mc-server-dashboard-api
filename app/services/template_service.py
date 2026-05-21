"""Backward-compatibility shim for the migrated template service.

The real implementation lives at
`app.templates.application.service.TemplateService` and is wired in
production via `app.templates.api.dependencies.get_template_service`.

The legacy `template_service` singleton at this module path is
preserved for callers that still construct it manually
(`app.services.backup_service` instantiates `TemplateService()`
directly inside `restore_backup_with_template`). The facade builds a
one-shot `SqlAlchemyTemplatesUnitOfWork` + `SqlAlchemyServerReadPort`
per call from the explicit `db=` argument legacy callers pass.

TODO(#228): once `backup_service` migrates to DI, delete this file and
remove the legacy `db=` parameter.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.models import ServerType
from app.templates.adapters.uow import SqlAlchemyTemplatesUnitOfWork
from app.templates.application.service import (
    TemplateService as _ApplicationTemplateService,
)
from app.templates.domain.entities import TemplateEntity
from app.templates.domain.exceptions import (
    TemplateAccessError,
    TemplateCreationError,
    TemplateError,
    TemplateNotFoundError,
)
from app.users.models import User

__all__ = [
    "TemplateService",
    "TemplateError",
    "TemplateNotFoundError",
    "TemplateCreationError",
    "TemplateAccessError",
    "template_service",
]


class _LegacyTemplateFacade:
    """Adapts the new DI-shaped `TemplateService` to legacy callers that
    pass `db=Session` and a `creator` User object per call.

    A `SqlAlchemyTemplatesUnitOfWork` is bound to a single session, so
    this facade builds a fresh service instance per call rather than
    caching one across requests.
    """

    def __init__(self, templates_directory: Path = Path("templates")):
        self.templates_directory = Path(templates_directory)

    def _build(self, db: Session) -> _ApplicationTemplateService:
        return _ApplicationTemplateService(
            uow=SqlAlchemyTemplatesUnitOfWork(db=db),
            server_read=SqlAlchemyServerReadPort(db),
            templates_directory=self.templates_directory,
        )

    async def create_template_from_server(
        self,
        server_id: int,
        name: str,
        db: Optional[Session] = None,
        creator: Optional[User] = None,
        description: Optional[str] = None,
        is_public: bool = False,
    ) -> TemplateEntity:
        if db is None:
            raise TemplateError(
                "Database session is required for security-critical operations"
            )
        if creator is None:
            raise TemplateError("Creator user is required for template creation")

        return await self._build(db).create_template_from_server(
            server_id=server_id,
            name=name,
            creator_id=creator.id,
            description=description,
            is_public=is_public,
        )

    async def create_custom_template(
        self,
        name: str,
        minecraft_version: str,
        server_type: ServerType,
        configuration: Dict[str, Any],
        db: Optional[Session] = None,
        creator: Optional[User] = None,
        description: Optional[str] = None,
        default_groups: Optional[Dict[str, List[int]]] = None,
        is_public: bool = False,
    ) -> TemplateEntity:
        if db is None:
            raise TemplateError(
                "Database session is required for security-critical operations"
            )
        if creator is None:
            raise TemplateError("Creator user is required for template creation")

        return await self._build(db).create_custom_template(
            name=name,
            minecraft_version=minecraft_version,
            server_type=server_type,
            configuration=configuration,
            creator_id=creator.id,
            description=description,
            default_groups=default_groups,
            is_public=is_public,
        )


# Public alias: legacy callers that instantiate `TemplateService()` (e.g.
# `app.services.backup_service.restore_backup_and_create_template`) get
# the facade class so the zero-arg constructor keeps working. The new
# DI-shaped application service is available as
# `app.templates.application.service.TemplateService` for code that has
# migrated to Depends-based wiring.
TemplateService = _LegacyTemplateFacade

template_service = _LegacyTemplateFacade()
