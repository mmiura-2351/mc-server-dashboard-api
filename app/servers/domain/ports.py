"""Port (Protocol) definitions for the servers domain.

Per `docs/ARCHITECTURE.md` §4.1, this module **must not import** from
SQLAlchemy, Pydantic, FastAPI, or any other framework. All types
crossing these Protocols are pure domain entities defined in
`entities.py`.

Three Ports are defined here:

- `ServerReadPort` (seed): minimal cross-domain read view introduced
  for #224 (files) and extended for #225 (templates). Other domains
  depend on it; PR #1 keeps the surface untouched to preserve the
  invariant. PR #2 will fill in `list_by_owner` and friends.
- `ServerRepository`: full persistence Port for the `Server`
  aggregate, introduced under #228. Concrete impl:
  `SqlAlchemyServerRepository`; unit-test impl: `FakeServerRepository`.
- `ServersUnitOfWork`: transactional boundary Port. Application code
  wraps a set of repository calls in `async with uow:` and calls
  `await uow.commit()` to finalise. Symmetric with `BackupsUnitOfWork`
  / `GroupsUnitOfWork` / `TemplatesUnitOfWork` (#225/#226/#227): the
  UoW intentionally carries only `commit` / `rollback`, with no
  retry-aware variant — retry lives inside the repository's status
  writes via `app.core.database_utils.with_transaction`.

`ServerRepository` deliberately does **not** expose sibling-aggregate
accessors (D-1 in the #228 plan): callers wire `BackupRepository` /
`TemplateRepository` directly through DI rather than fan everything
through the servers Port.
"""

from types import TracebackType
from typing import List, Mapping, Optional, Protocol

from app.servers.domain.entities import (
    CreateServerCommand,
    ServerEntity,
    ServerListPage,
    ServerListSpec,
    UpdateServerCommand,
)
from app.servers.domain.value_objects import ServerStatus


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


class ServerRepository(Protocol):
    """Persistence port for the `Server` aggregate.

    Concrete implementations: `SqlAlchemyServerRepository` (production),
    `FakeServerRepository` (unit tests).

    Repository methods **do not commit** by default. Wrap calls in a
    `ServersUnitOfWork` context and call `await uow.commit()` once you
    are done. The two status-write methods (`update_status`,
    `batch_update_statuses`) are the only exception — they own their
    transaction internally via `with_transaction` to inherit the
    backoff/retry semantics the legacy code expected (M-8 / D-5 in
    the plan).
    """

    # ----- Reads -----

    async def get(
        self, server_id: int, *, include_deleted: bool = False
    ) -> Optional[ServerEntity]: ...

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[ServerEntity]: ...

    async def list_paged(self, spec: ServerListSpec) -> ServerListPage: ...

    async def list_by_status(
        self, status: ServerStatus, *, include_deleted: bool = False
    ) -> List[ServerEntity]: ...

    async def list_by_port(
        self,
        port: Optional[int],
        *,
        statuses: Optional[List[ServerStatus]] = None,
        exclude_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> List[ServerEntity]:
        """Return servers matching the port + status filter.

        `port=None` returns all servers matching the status filter (the
        en-passant fix for the H-3 / D-4 bug at
        `app/servers/routers/import_export.py:249`, where the legacy
        code intended "any running/starting server" but accidentally
        filtered on a Column boolean).

        `exclude_id` excludes a given server id — used by the
        port-conflict check to ignore the server being mutated.
        """
        ...

    async def list_by_ids(
        self, server_ids: List[int], *, include_deleted: bool = False
    ) -> List[ServerEntity]: ...

    async def list_by_owner(
        self, owner_id: int, *, include_deleted: bool = False
    ) -> List[ServerEntity]: ...

    # ----- Writes (stage-only; UoW commits) -----

    async def add(self, command: CreateServerCommand) -> ServerEntity: ...

    async def update(
        self, server_id: int, command: UpdateServerCommand
    ) -> Optional[ServerEntity]: ...

    async def soft_delete(self, server_id: int) -> bool: ...

    # ----- Status writes (own-transaction via with_transaction) -----

    async def update_status(
        self, server_id: int, status: ServerStatus
    ) -> Optional[ServerEntity]:
        """Set a server's status. Owns its transaction (retry inside)."""
        ...

    async def batch_update_statuses(
        self, updates: Mapping[int, ServerStatus]
    ) -> Mapping[int, Optional[ServerEntity]]:
        """Bulk status update keyed by server id. Owns its transaction."""
        ...


class ServersUnitOfWork(Protocol):
    """Transactional boundary Port for the servers domain.

    Application services enter a UoW context, perform repository
    operations through the same session, then call `commit()` to
    persist atomically. Exiting the context without committing rolls
    back.

    The UoW carries no retry-aware commit variant (D-5): retry lives
    at the persistence boundary inside the repository's own status
    writes, where the SQL is small enough to be safely re-issued.
    Multi-step business writes do not auto-retry.
    """

    servers: ServerRepository

    async def __aenter__(self) -> "ServersUnitOfWork": ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
