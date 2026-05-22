"""Port (Protocol) definitions for the templates domain.

Per `docs/ARCHITECTURE.md` §4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types crossing
these Protocols are pure domain entities defined in `entities.py`.

Two Ports are defined:
- `TemplateRepository`: persistence Port for templates.
- `TemplatesUnitOfWork`: transactional boundary Port. Application code
  wraps a set of Repository calls in `async with uow:` and calls
  `await uow.commit()` to finalize. Concrete adapters drive the
  SQLAlchemy session lifecycle.
"""

from types import TracebackType
from typing import Dict, Optional, Protocol

from app.servers.domain.value_objects import ServerType
from app.templates.domain.entities import (
    CreateTemplateCommand,
    TemplateEntity,
    TemplateListPage,
    TemplateListSpec,
    UpdateTemplateCommand,
)


class TemplateRepository(Protocol):
    """Persistence port for templates.

    Concrete implementations: `SqlAlchemyTemplateRepository`
    (production), `FakeTemplateRepository` (unit tests).

    Repository methods **do not commit**. Wrap calls in a
    `TemplatesUnitOfWork` context and call `await uow.commit()` once
    you are done.
    """

    # ----- Reads -----

    async def get(self, template_id: int) -> Optional[TemplateEntity]: ...

    async def find_by_creator_and_name(
        self, creator_id: int, name: str
    ) -> Optional[TemplateEntity]: ...

    async def list_paged(self, spec: TemplateListSpec) -> TemplateListPage: ...

    async def count_visible(self, viewer_id: int, viewer_is_admin: bool) -> int: ...

    async def count_visible_public(
        self, viewer_id: int, viewer_is_admin: bool
    ) -> int: ...

    async def count_owned_by(self, creator_id: int) -> int: ...

    async def count_visible_by_server_type(
        self, viewer_id: int, viewer_is_admin: bool
    ) -> Dict[ServerType, int]: ...

    async def count_active_dependent_servers(self, template_id: int) -> int: ...

    # ----- Writes -----

    async def add(self, command: CreateTemplateCommand) -> TemplateEntity: ...

    async def update(
        self, template_id: int, command: UpdateTemplateCommand
    ) -> Optional[TemplateEntity]: ...

    async def delete(self, template_id: int) -> bool: ...


class TemplatesUnitOfWork(Protocol):
    """Transactional boundary Port for the templates domain.

    Application services enter a UoW context, perform repository
    operations through the same session, then call `commit()` to
    persist atomically. Exiting the context without committing rolls
    back.
    """

    templates: TemplateRepository

    async def __aenter__(self) -> "TemplatesUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
