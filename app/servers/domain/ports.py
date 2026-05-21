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


class ServerReadPort(Protocol):
    """Minimal cross-domain read view of Server.

    TBD(#154-8): introduced for #224 (files) — the file-history service
    needs a server's on-disk directory path during a restore. Once #228
    rebuilds the servers domain into the standard layout, this Port
    will gain a full `get(server_id) -> ServerEntity | None`, plus
    whatever else the consumers in #154-5 / #154-6 / #154-7 require.
    Until then, *only* the method below is sanctioned.
    """

    async def get_directory_path(self, server_id: int) -> Optional[str]: ...
