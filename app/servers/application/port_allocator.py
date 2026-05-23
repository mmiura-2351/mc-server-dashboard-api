"""Server port-allocation helpers (Issue #33).

A single source of truth for "which ports are currently held by an
active server" and "give me the next N free ports starting at
``start_port``". Previously this logic was duplicated inline inside
``app/servers/routers/import_export.py`` (the import path) and lived
nowhere reusable for the pre-flight port check the create-server path
needs.

The check only considers servers in the active operational statuses
(``running`` / ``starting``) — stopped servers are intentionally
ignored so two servers can share a port as long as they never run
concurrently. This matches the contract pinned by the existing
:mod:`tests.integration.servers.test_port_conflicts` integration
suite.
"""

from __future__ import annotations

from typing import List

from app.servers.domain.ports import ServerRepository
from app.servers.domain.value_objects import ServerStatus

# Status values that mean the server is (or is about to be) bound to
# the port. Keep in sync with the import-path heuristic — see the
# in-line comment that used to live at
# ``app/servers/routers/import_export.py``.
_ACTIVE_STATUSES: List[ServerStatus] = [
    ServerStatus.running,
    ServerStatus.starting,
]

# Hard upper bound from RFC 6335. Anything above is reserved/invalid.
_MAX_PORT = 65535


async def find_available_ports(
    repo: ServerRepository,
    start_port: int,
    *,
    count: int = 3,
) -> List[int]:
    """Return up to ``count`` free ports starting from ``start_port``.

    Walks the integer range monotonically; the search stops when
    ``count`` ports have been collected or the port space is
    exhausted. Returns an empty list when ``start_port`` is already
    past ``_MAX_PORT``.

    The function inspects the database only — it does not attempt a
    socket bind to verify the port is reachable on the host. The
    create-server path performs an additional socket-level check at
    start time, see
    :class:`app.servers.application.minecraft_server.MinecraftServerManager`.
    """
    if start_port > _MAX_PORT or count <= 0:
        return []

    used_servers = await repo.list_by_port(port=None, statuses=_ACTIVE_STATUSES)
    used_ports = {s.port for s in used_servers}

    suggestions: List[int] = []
    candidate = max(start_port, 1024)
    while candidate <= _MAX_PORT and len(suggestions) < count:
        if candidate not in used_ports:
            suggestions.append(candidate)
        candidate += 1
    return suggestions


async def port_holder(
    repo: ServerRepository,
    port: int,
) -> str | None:
    """Return the name of the active server already using ``port``, or None.

    "Active" matches :data:`_ACTIVE_STATUSES`. When multiple servers
    hold the same port (shouldn't happen but is defended against) the
    first one returned by the repository wins.
    """
    if port <= 0:
        return None
    holders = await repo.list_by_port(port=port, statuses=_ACTIVE_STATUSES)
    if not holders:
        return None
    return holders[0].name
