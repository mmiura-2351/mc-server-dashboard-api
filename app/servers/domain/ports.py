"""Port (Protocol) definitions for the servers domain (minimal seed).

Per `docs/ARCHITECTURE.md` §4.1, this module must not import from
SQLAlchemy, Pydantic, FastAPI, or any other framework.

This file currently exposes only the smallest cross-domain read surface
that other domains genuinely need today. The full `ServerRepository`
and a finalised `ServerReadPort` will be introduced under #154-8
(Issue #228); do **not** speculatively add methods here in the
meantime — keep the surface minimal so #228 can shape it without
breakage churn.
"""

from typing import Optional, Protocol

from app.servers.domain.entities import ServerEntity


class ServerReadPort(Protocol):
    """Minimal cross-domain read view of Server.

    TBD(#154-8): introduced for #224 (files) — the file-history service
    needs a server's on-disk directory path during a restore. The
    `get(server_id)` method below was added for #225 (templates) to
    return a small read-only snapshot used to extract template metadata.
    Once #228 rebuilds the servers domain into the standard layout, this
    Port will be replaced with the full `ServerRepository` / final
    `ServerReadPort` shape. Until then, *only* the methods below are
    sanctioned.
    """

    async def get_directory_path(self, server_id: int) -> Optional[str]: ...

    # TBD(#154-8): added for #225 (templates). Returns the minimal
    # `ServerEntity` view used by `TemplateService.create_template_from_server`.
    # The full surface lands with the servers domain refactor in #228.
    async def get(self, server_id: int) -> Optional[ServerEntity]: ...
