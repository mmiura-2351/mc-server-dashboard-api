# System Architecture

> **Note**: This document defines the **target architecture and the standards that all new code must follow**, established under Issue #149 (refactor) / #153 (A-1).
>
> For the description of the system's pre-refactor implementation, see [`docs/ARCHITECTURE_LEGACY.md`](ARCHITECTURE_LEGACY.md). That document is preserved as historical context only.

This document provides the architectural blueprint for the Minecraft Server Dashboard API. It defines the layering rules, dependency directions, and standard structure that every domain must adhere to. The goal is an architecture where any external technology (persistence, authorization, real-time transport, external APIs, etc.) can be replaced without touching business logic.

---

## 1. Overview

The Minecraft Server Dashboard API is a FastAPI-based backend for managing multiple Minecraft servers. It provides authentication, role/permission-based access control, real-time WebSocket monitoring, automated backup scheduling, file management with version history, and complete server lifecycle management.

The architecture is built on **Hexagonal (Ports & Adapters)** principles so that:

- Business logic does not depend on any external framework or technology
- External technologies are accessed through abstract **Ports** (Protocols)
- Concrete **Adapters** implement those ports and are wired in via Dependency Injection
- Any adapter can be replaced (different DB, different auth strategy, different event transport) without modifying business logic

## 2. Technology Stack

- **Framework**: FastAPI (Python 3.13+) with uvicorn ASGI server
- **Database**: SQLite via SQLAlchemy 2.0 ORM (swappable through Ports)
- **Authentication**: JWT (access + refresh tokens), bcrypt password hashing
- **Real-time**: WebSockets with connection lifecycle management
- **Process Management**: Async subprocess management
- **File Operations**: aiofiles with encoding detection and security validation
- **Package Management**: uv with dependency groups and workspace support
- **Testing**: pytest with asyncio support
- **Code Quality**: Ruff (lint + format), MyPy (type checking, gradually enabled)

## 3. Architectural Style: Hexagonal (Ports & Adapters)

### 3.1 Why Hexagonal

Traditional layered architecture often lets business logic depend on framework or persistence libraries. As a result, swapping any layer (e.g., changing the authorization scheme or replacing the persistence backend) requires invasive changes throughout the codebase.

Hexagonal architecture inverts this: business logic depends only on abstractions (Ports). Concrete technologies live behind Adapters and can be swapped freely.

### 3.2 Principles

1. **The domain core is pure**. It must not import FastAPI, SQLAlchemy, httpx, or any other framework/library.
2. **External access is mediated by Ports**. A Port is a Python `Protocol` defined inside the domain layer.
3. **Adapters implement Ports**. Adapters live outside the domain core and depend on the domain (never the other way around).
4. **Wiring happens at the edge**. The `api/` layer's `dependencies.py` selects which Adapter to inject.
5. **Layers are thin and have a single responsibility**. No layer skipping, no reverse dependencies.

## 4. Layer Definitions

The system is organized into four concentric layers. Each layer has a strict responsibility and clear "may do / must not do" rules.

### 4.1 `domain/` — Pure domain

**Responsibility**: Express the business model and its invariants.

- **May contain**: entities, value objects, domain exceptions, Port (Protocol) definitions, pure functions for domain calculations
- **Must not contain**: anything that imports a framework, database driver, HTTP client, or any external library beyond the Python standard library and `typing`-style helpers

```python
# domain/entities.py
@dataclass
class Server:
    id: ServerId | None
    name: str
    owner_id: UserId
    status: ServerStatus
    created_at: datetime

    @classmethod
    def create(cls, name: str, owner_id: UserId, created_at: datetime) -> "Server":
        # Invariant checks live here; no I/O, no framework calls.
        ...
```

```python
# domain/ports.py
class ServerRepository(Protocol):
    async def get(self, server_id: ServerId) -> Server | None: ...
    async def save(self, server: Server) -> None: ...
```

#### Port method signatures: `async` by default, sync when justified

Public methods on `domain/ports.py` Protocols are `async def` by default. This keeps the application layer compatible with future migration to async SQLAlchemy and matches the FastAPI route-handler shape.

A Port **may** declare **sync** methods if all three of the following hold:

1. The operation is fire-and-forget — callers do not need to await a result and the operation does not yield to other tasks.
2. The underlying I/O is sync and migration to async is not on the roadmap for that adapter.
3. Every existing callsite is already sync, so declaring `async def` would force `asyncio.run` shims at the call sites with no payoff.

If only some of the above hold, default to `async def`.

The canonical exception today is `AuditWriter.record` in `app/audit/domain/ports.py`: audit writes are fire-and-forget against a sync SQLAlchemy session, issued from 30+ existing sync callsites that already live inside `async def` route handlers. The rationale is documented in that Port's docstring, and `tests/unit/audit/test_protocol_conformance.py::test_writer_methods_are_sync` pins the choice so a future refactor cannot silently flip it.

When introducing a new sync Port, mirror that pattern: explain the three-condition justification in the Port's docstring, and add a conformance test that asserts the sync shape.

### 4.2 `application/` — Use cases

**Responsibility**: Orchestrate domain logic into application use cases.

- **May depend on**: `domain/` only
- **Must not depend on**: `adapters/`, `api/`, or any framework
- **Pattern**: One use case per class with a single `execute()` method (or a small, cohesive set of methods)
- **Receives**: Ports as constructor arguments (Dependency Inversion)

```python
# application/use_cases.py
class CreateServer:
    def __init__(self, repo: ServerRepository, clock: Clock):
        self._repo = repo
        self._clock = clock

    async def execute(self, name: str, owner_id: UserId) -> Server:
        server = Server.create(name=name, owner_id=owner_id, created_at=self._clock.now())
        await self._repo.save(server)
        return server
```

### 4.3 `adapters/` — Concrete implementations of Ports

**Responsibility**: Provide concrete implementations for the Ports defined in `domain/`.

- **May depend on**: `domain/` (for Port definitions and types) and any framework/library
- **Must not be imported by**: `domain/` or `application/`
- **Examples**: SQLAlchemy repositories, HTTP client adapters, WebSocket event publishers, system clock

```python
# adapters/sqlalchemy_server_repository.py
class SqlAlchemyServerRepository:  # implements ServerRepository Protocol
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, server_id: ServerId) -> Server | None:
        # ... SQLAlchemy specific code
```

### 4.4 `api/` — HTTP boundary

**Responsibility**: Translate HTTP requests into use case invocations and translate use case results into HTTP responses.

- **May depend on**: `application/` (use cases), FastAPI, and — only inside `dependencies.py` — `adapters/` for DI wiring
- **Components**:
  - `router.py` — FastAPI router with endpoint definitions. **Must only import from `application/` and `.schemas` / `.dependencies`.** It must not import any module under `adapters/`.
  - `schemas.py` — Pydantic models for request/response (DTOs). **Must only import from `domain/` (for entity-to-DTO mapping types) and standard libraries.** It must not import from `adapters/` or `application/`.
  - `dependencies.py` — The **only** file in `api/` allowed to import from `adapters/`. It wires concrete Adapters to the Ports that use cases require.
- **Must not contain**: business logic, database access, or domain rules. A router that holds a SQLAlchemy session, calls an ORM model, or branches on roles is a violation.

```python
# api/router.py
@router.post("/", response_model=ServerResponse)
async def create_server(
    request: CreateServerRequest,
    user: User = Depends(get_current_user),
    use_case: CreateServer = Depends(get_create_server),
) -> ServerResponse:
    server = await use_case.execute(name=request.name, owner_id=user.id)
    return ServerResponse(
        id=server.id, name=server.name, status=server.status,
    )
```

```python
# api/dependencies.py
def get_server_repo(session: AsyncSession = Depends(get_session)) -> ServerRepository:
    return SqlAlchemyServerRepository(session)

def get_create_server(
    repo: ServerRepository = Depends(get_server_repo),
    clock: Clock = Depends(get_clock),
) -> CreateServer:
    return CreateServer(repo, clock)
```

## 5. Dependency Direction

```
   ┌──────────────────────────────────────┐
   │ api/                                  │
   └──────────────────────────────────────┘
                  ↓ depends on
   ┌──────────────────────────────────────┐
   │ application/                          │
   └──────────────────────────────────────┘
                  ↓ depends on
   ┌──────────────────────────────────────┐
   │ domain/                               │  ← knows nothing of the outside
   └──────────────────────────────────────┘
                  ↑ implements Ports of
   ┌──────────────────────────────────────┐
   │ adapters/                             │
   └──────────────────────────────────────┘
```

### 5.1 Rules

- `domain/` imports nothing from the project's other layers
- `application/` imports only from `domain/` (its own or — for cross-domain types such as Ports, entities, value objects, and exceptions — another domain's `domain/`, or `app/core/ports`)
- `adapters/` imports from `domain/` (Port definitions) and external libraries; it must not import from `application/` or `api/`
- `api/` imports from `application/`, and from `adapters/` **only** in `dependencies.py`

### 5.2 Forbidden patterns

The patterns below are violations regardless of the rationale offered. CI tooling (e.g., import-linter contracts) should enforce them mechanically as the codebase migrates.

- A use case in `application/` instantiating a concrete adapter directly (instead of receiving a Port)
- `domain/` importing SQLAlchemy, Pydantic, FastAPI, or any external library beyond the Python standard library
- `application/` importing FastAPI, SQLAlchemy, Pydantic, or any module under `adapters/` or `api/`
- `adapters/` importing from `application/` or `api/`
- `api/router.py` or `api/schemas.py` importing from `adapters/`. Only `api/dependencies.py` may bridge those two
- `api/router.py` running business logic, opening a database session, or branching on user roles
- One domain's `application/` directly importing another domain's `adapters/` (use a Port — see §5.3)
- One domain's `adapters/` reaching into another domain's `domain/` internals to bypass its Ports

### 5.3 Cross-domain use cases

When a use case needs functionality from another domain, it should depend on a Port defined in either the current domain or a shared `app/core/` location, not on another domain's concrete adapter.

## 6. Per-Domain Structure

Every domain in `app/` must follow this layout. Deviations require explicit justification documented in the directory.

```
app/<domain>/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── entities.py        # Entities and aggregates
│   ├── value_objects.py   # Value objects (optional)
│   ├── ports.py           # Protocol definitions for external dependencies
│   └── exceptions.py      # Domain-specific exceptions
├── application/
│   ├── __init__.py
│   └── use_cases.py       # One use case per class
├── adapters/
│   ├── __init__.py
│   ├── repository.py      # Concrete repository (SQLAlchemy)
│   └── <other_adapters>.py
└── api/
    ├── __init__.py
    ├── router.py          # FastAPI router
    ├── schemas.py         # Pydantic DTOs
    └── dependencies.py    # DI wiring
```

### 6.1 When to split a file

| File | Threshold for splitting into a subdirectory |
|---|---|
| `use_cases.py` | >800 lines or >8 distinct use cases → split into `application/use_cases/` |
| `router.py` | >300 lines or >10 endpoints → split into `api/routers/` |
| `schemas.py` | >300 lines → split into `api/schemas/` |
| `entities.py` | Multiple aggregates → split per aggregate |

### 6.2 Shared cross-cutting code

Code that is genuinely shared across domains lives in `app/core/`:

- `app/core/database.py` — SQLAlchemy engine and session factory
- `app/core/config.py` — application settings
- `app/core/exceptions.py` — base exception types
- `app/core/ports.py` — cross-cutting Ports (e.g., `Clock`, `EventPublisher`, `PermissionChecker`)
- `app/core/dependencies.py` — DI factories for cross-cutting Ports (e.g., `get_clock`, `get_permission_checker`)
- `app/core/error_handlers.py` — FastAPI exception handlers

### 6.3 Boundary enforcement

The rules in §4 and §5 are mechanically checkable. As the migration under Issue #149 progresses, the project should add import-direction contracts (e.g., [import-linter](https://import-linter.readthedocs.io/)) to CI so the following are flagged automatically:

- `app/<domain>/domain/` may not import from `app/<domain>/application/`, `app/<domain>/adapters/`, or `app/<domain>/api/`, nor from any third-party framework
- `app/<domain>/application/` may not import from `app/<domain>/adapters/` or `app/<domain>/api/`
- `app/<domain>/adapters/` may not import from `app/<domain>/application/` or `app/<domain>/api/`
- Inside `app/<domain>/api/`, only `dependencies.py` may import from `app/<domain>/adapters/`

Until those contracts are in place, reviewers are responsible for enforcing the boundaries listed in §5.2.

## 7. Cross-cutting Concerns via Ports

Cross-cutting concerns are not embedded in the domain core. They are exposed as Ports and implemented by Adapters, the same way persistence is. Switching implementation is then a matter of swapping the DI binding.

| Concern | Port | Default Adapter | Notes |
|---|---|---|---|
| Persistence | `<Entity>Repository` | SQLAlchemy adapter | One Port per aggregate root |
| Transactions / UoW | `UnitOfWork` | SQLAlchemy-backed | Spans multiple repositories within a use case |
| Event publication | `RealTimeServerCommands` collaborator (no abstract Port yet — see §7.2) | WebSocket-backed publisher | Used for real-time updates |
| External APIs | `<Service>Client` (e.g., `MinecraftApiClient`) | aiohttp-backed | Retry / fallback handled at the adapter |
| Permission checks | `PermissionChecker` | Role-based adapter | Decoupled so it can later switch to per-operation user grants without touching use cases |
| Time | `Clock` | `SystemClock` | Test code injects `FixedClock` |
| File system | `FileStorage` | Local FS adapter | Path traversal protection inside the adapter |
| Process management | `ServerProcessRunner` | Subprocess adapter | Isolates use cases from `asyncio.subprocess` details |

> **On authorization**: It is one Port among many. The current default is role-based; the architecture does not assume that. Use cases call `checker.can(user, "<operation>")` and remain unaware of how the answer is computed.

### 7.1 Audit Logging Pattern

Audit logging is a cross-cutting concern that every domain emits but no domain owns. The target shape consists of a Port, a request-scoped middleware that batches writes, and a fire-after-commit rule on the caller side.

- **Port** — `AuditWriter` in `app/audit/domain/ports.py` exposes a single `record(command: AuditEventCommand) -> None` method. The method is **sync** by design (see §4.1's discussion of sync Ports), and the Port's docstring states the **"must not raise"** contract: an audit failure must never block the calling business operation; errors are logged and swallowed inside the adapter.
- **Request-scoped batching** — `app/middleware/audit_middleware.py` installs an `AuditTracker` on `request.state` for every auditable request. Calls to `AuditWriter.record(...)` are buffered into that tracker and flushed to the database once, at the end of the request lifecycle (`AuditTracker.flush_events`). This keeps audit writes off the hot path of the business transaction and means audit failures cannot poison the business commit.
- **DI wiring** — Use cases receive the writer through their constructor. `app/groups/api/dependencies.py::get_audit_writer` is the reference factory: it pulls the request's `AuditTracker` and returns a `SqlAlchemyAuditWriter` bound to it, falling back to a direct-write path when no tracker is present (e.g. background tasks).
- **Fire-after-commit** — Use cases must record the audit event **after** the domain transaction has committed, never inside the unit-of-work block. See `app/groups/application/service.py::GroupService.create_group` (around line 126) for the canonical shape: `await uow.commit()` first, then `self._audit.record(...)` outside the `async with` block. This guarantees we never log an event for a transaction that was rolled back.

New domains adopting this pattern should: (a) inject `AuditWriter` via the domain's `api/dependencies.py`, (b) call `record` only after commit, and (c) rely on the Port's "must not raise" contract — wrapping each call in `try/except` at the use-case level is redundant.

Migration of the remaining legacy `AuditService.log_*` static-facade callsites (in `app/auth/`, `app/users/`, `app/files/`) is tracked separately; new code must not introduce new callsites of that facade.

### 7.2 Real-time Event Emission Pattern

WebSocket-driven side effects (running-server commands, log broadcast) are not yet expressed as an abstract Port. Today they follow a collaborator-injection pattern that keeps domain code free of direct `websocket_service` imports.

- **Collaborator, not Port** — `app/servers/application/real_time_server_commands.py` exposes a `RealTimeServerCommandService` (singleton: `real_time_server_commands`) that owns the in-process channel to running Minecraft servers. Domains that need to fire a real-time effect receive this collaborator as a constructor argument rather than importing it at module top.
- **Injection with a lazy default** — `app/groups/application/file_syncer.py::GroupFileSyncer.__init__` accepts `real_time_commands: Any = None` and, when no override is supplied, lazy-imports the production singleton inside the constructor body. The lazy import is deliberate: it lets unit tests construct `GroupFileSyncer` with an in-memory fake without ever loading the websocket-service chain.
- **Public wrapper, not attribute access** — Callers go through `GroupFileSyncer.broadcast_group_change(...)`, which forwards to `_real_time_commands.handle_group_change_commands(...)`. Reaching into the private `_real_time_commands` attribute from outside the syncer is a violation (see Issue #262 in the rationale comment).
- **Restricted direct-import surface** — Direct imports of `app.websockets.application.service.websocket_service` are confined to: `app/main.py` (lifecycle / startup / shutdown), `app/websockets/router.py` (the WS router), and `app/health/adapters/websocket_check.py` (the health adapter). No `application/` or `domain/` module imports `websocket_service` directly.

When a future Port is introduced (`EventPublisher` or equivalent), it will replace the collaborator type at the use-case constructor; the call-site shape (`await collaborator.broadcast_*(...)`) is already correct and will not need to change.

## 8. Application Lifecycle

The FastAPI application uses a `lifespan` context manager that orchestrates startup and shutdown of all infrastructure adapters. Critical services must be initialized successfully; optional services degrade gracefully.

### 8.1 Startup sequence

1. **Database (critical)** — engine and session factory initialization; failure aborts startup
2. **Database integration adapter (important)** — initial state sync; degrades gracefully on failure
3. **Backup scheduler adapter (optional)** — automated backups; continues without if startup fails
4. **WebSocket service adapter (optional)** — real-time monitoring; continues without if startup fails
5. **Use case factories** — wired with their selected Adapters and exposed via FastAPI Depends

### 8.2 Graceful degradation

- Database issues → use cases that don't need DB still operate; affected ones raise a domain exception that the API layer translates to HTTP 503
- Backup scheduler failure → manual backup use cases still work
- WebSocket failure → REST endpoints continue; clients see no real-time updates
- External API failure → adapter falls back to cached data or raises a domain exception

### 8.3 Shutdown sequence

In reverse order of startup, each adapter releases its resources (connections, subprocesses, file handles).

## 9. Security Architecture

### 9.1 Authentication

- JWT access tokens (short-lived) and refresh tokens (long-lived)
- Implemented as an Adapter behind an `AuthTokenService` Port so the token format can evolve
- bcrypt password hashing with salt
- Refresh token invalidation on logout

### 9.2 Authorization

- Performed through the `PermissionChecker` Port
- Default Adapter maps users' roles to a fixed set of permissions
- Application use cases call `checker.can(user, permission, resource=...)`; they do not know about roles
- See Section 7 — the Port is what gives us the freedom to evolve the underlying scheme

### 9.3 Defensive controls

- Path traversal protection inside the `FileStorage` adapter
- Pydantic models enforce request validation at the API boundary
- Audit logging through an `AuditLogger` Port (decorator-style usage in use cases)
- Rate limiting on sensitive endpoints (middleware at the API layer)
- All secrets read from environment variables via `app/core/config.py`

## 10. Data Architecture

### 10.1 Core entities

| Entity | Responsibility |
|---|---|
| User | Authentication identity, role, approval status |
| Server | Minecraft server configuration, state, ownership |
| Group | OP/whitelist player collection with multi-server attachment |
| Backup | Backup metadata, statistics, restoration info |
| FileEditHistory | File version tracking with rollback |
| AuditLog | Activity trail for security/compliance |
| BackupSchedule | Cron-based schedule with execution history |
| RefreshToken | Persisted refresh token for session management |
| Permission (planned) | Per-user operation grants when migrating away from pure role-based auth |

### 10.2 Relationships (high level)

```
User (1:N) ──┬─ Server (1:N) ── Backup
             ├─ Group (N:M) ─── Server (via GroupServerAttachment)
             └─ RefreshToken

Server (1:N) ── FileEditHistory
All Entities ── AuditLog
```

### 10.3 Persistence principles

- Repositories return domain entities, not ORM rows. Mapping happens inside the adapter
- Referential integrity is enforced at the DB schema level; domain invariants are enforced in entities
- Soft deletes where retention matters; otherwise hard delete
- Migrations are explicit (an Alembic-like flow is planned; the current schema uses SQLAlchemy auto-create)

## 11. Integration Patterns

### 11.1 Internal communication

- Use cases never call FastAPI routers; the flow is always inbound from `api/` to `application/`
- Cross-domain coordination happens through Ports defined in the consuming domain or in `app/core/`
- Real-time updates (status changes, log streams) are emitted via the `EventPublisher` Port; the WebSocket Adapter delivers them to clients

### 11.2 External APIs

External services are accessed through Adapters that implement a domain-defined Port:

- **Minecraft Official API** — version manifests, JAR downloads (with retry + cache fallback in the adapter)
- **Mojang API** — player UUID / username resolution (rate limiting handled in the adapter)

The use case asks the Port for what it needs; failure modes (timeout, cache hit) are the adapter's concern, surfaced as domain exceptions.

## 12. Performance Architecture

- **Database**: connection pooling and query-level optimization inside the repository adapter
- **File operations**: async I/O via aiofiles; the storage adapter encapsulates streaming and encoding detection
- **Process management**: the `ServerProcessRunner` adapter pools subprocess handles and enforces resource limits
- **WebSocket**: per-server connection pooling and message queuing inside the WebSocket adapter
- **Caching**: JAR file caching (`JarCache` Port + filesystem adapter)
- **Monitoring**: a performance middleware records request duration and slow-request thresholds. Slow-query detection lives inside the persistence adapter

## 13. Development Standards

### 13.1 Code style

- Ruff formatting (Black-compatible), 90-character line length
- Ruff lint with import sorting (`I`)
- Type hints required for all new code
- MyPy strict typing is being enabled gradually

### 13.2 Naming

| Item | Convention | Example |
|---|---|---|
| Module file | `snake_case.py` | `server_repository.py` |
| Class | `PascalCase` | `CreateServer`, `SqlAlchemyServerRepository` |
| Function / method | `snake_case` | `create_server`, `find_by_id` |
| Port (Protocol) | `<Noun>` (no `I`/`Abstract` prefix) | `ServerRepository`, `Clock` |
| Adapter | `<Tech><Port>` | `SqlAlchemyServerRepository`, `WebSocketEventPublisher` |
| Use case | Verb in present tense, no `UseCase` suffix | `CreateServer`, `RestoreBackup` |
| Permission code | `"<resource>:<action>"` | `"server:create"`, `"backup:restore"` |
| Pydantic request schema | `<UseCase>Request` | `CreateServerRequest` |
| Pydantic response schema | `<Entity>Response` | `ServerResponse` |

### 13.3 Testing

Testing follows the layered structure. The full policy — classification rules, marker usage, and sample tests — is in [`docs/TESTING.md`](./TESTING.md), which is the canonical source. The summary below exists only so this document is readable standalone.

- **Unit tests** (`tests/unit/`) target `domain/` and `application/`, with all Ports replaced by in-memory Fakes or stubs
- **Integration tests** (`tests/integration/`) exercise `adapters/` and the `api/` boundary with a real (worker-scoped SQLite) database
- **Infrastructure tests** (`tests/infrastructure/`) verify behavior that depends on real processes, filesystem, sockets, or external HTTP

Each Port should have a `FakeXxx` test double under `tests/unit/<domain>/fakes.py` so use case tests stay fast and isolated.

## 14. New Domain Checklist

When introducing a new domain, follow these steps in order. Skipping any step is treated as a deviation from the architecture.

1. Create the directory `app/<domain>/` with the four subdirectories: `domain/`, `application/`, `adapters/`, `api/`
2. Define entities, value objects, and Ports in `domain/`
3. Define domain exceptions in `domain/exceptions.py`
4. Implement the use cases in `application/use_cases.py`, accepting Ports as constructor arguments
5. Implement the concrete Adapters in `adapters/`
6. Define request / response Pydantic schemas in `api/schemas.py`
7. Wire Ports to Adapters in `api/dependencies.py`
8. Implement the FastAPI router in `api/router.py`, using `Depends` to inject use cases
9. Register the router in `app/main.py` under `/api/v1/<domain>`
10. Add tests for each layer (unit for `domain/` and `application/`, integration for `adapters/` and `api/`)
11. Update `docs/ARCHITECTURE.md` Section 16 (Use Case Coverage) with the new use cases
12. Verify dependency direction against §5.2: `domain/` imports nothing from this project; `application/` imports only from `domain/`; `api/router.py` and `api/schemas.py` do not import from `adapters/`

## 15. Sample Domain: `notes/`

A complete minimal example of the standard layout. This is a hypothetical "user notes" feature that demonstrates every layer.

### 15.1 `app/notes/domain/entities.py`

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Note:
    id: int | None
    owner_id: int
    title: str
    body: str
    created_at: datetime

    @classmethod
    def create(cls, owner_id: int, title: str, body: str, now: datetime) -> "Note":
        if not title:
            raise ValueError("title is required")
        return cls(id=None, owner_id=owner_id, title=title, body=body, created_at=now)
```

### 15.2 `app/notes/domain/ports.py`

```python
from typing import Protocol
from .entities import Note

class NoteRepository(Protocol):
    async def add(self, note: Note) -> Note: ...
    async def get(self, note_id: int) -> Note | None: ...
    async def list_for_owner(self, owner_id: int) -> list[Note]: ...
```

### 15.3 `app/notes/domain/exceptions.py`

```python
class NoteError(Exception):
    """Base class for note domain errors."""

class NotePermissionDenied(NoteError):
    """Raised when a user lacks permission for a note operation."""
```

### 15.4 `app/notes/application/use_cases.py`

```python
from app.core.ports import Clock, PermissionChecker
from app.users.domain.entities import User
from ..domain.entities import Note
from ..domain.exceptions import NotePermissionDenied
from ..domain.ports import NoteRepository

class CreateNote:
    def __init__(
        self,
        repo: NoteRepository,
        clock: Clock,
        checker: PermissionChecker,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._checker = checker

    async def execute(self, user: User, title: str, body: str) -> Note:
        if not self._checker.can(user, "note:create"):
            raise NotePermissionDenied("note:create")
        note = Note.create(user.id, title, body, self._clock.now())
        return await self._repo.add(note)
```

### 15.5 `app/notes/adapters/repository.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from ..domain.entities import Note

class SqlAlchemyNoteRepository:  # implements NoteRepository
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, note: Note) -> Note:
        # ... map domain entity to ORM, insert, return updated entity
        ...
```

### 15.6 `app/notes/api/schemas.py`

```python
from pydantic import BaseModel
from datetime import datetime

class CreateNoteRequest(BaseModel):
    title: str
    body: str

class NoteResponse(BaseModel):
    id: int
    title: str
    body: str
    created_at: datetime
```

### 15.7 `app/notes/api/dependencies.py`

> This is the **only** file in `app/notes/api/` that may import from `app/notes/adapters/`. Routers and schemas must depend on use cases and Ports, never on concrete adapters.

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.dependencies import get_clock, get_permission_checker
from app.core.ports import Clock, PermissionChecker
from ..application.use_cases import CreateNote
from ..adapters.repository import SqlAlchemyNoteRepository
from ..domain.ports import NoteRepository

def get_note_repo(
    session: AsyncSession = Depends(get_session),
) -> NoteRepository:
    return SqlAlchemyNoteRepository(session)

def get_create_note(
    repo: NoteRepository = Depends(get_note_repo),
    clock: Clock = Depends(get_clock),
    checker: PermissionChecker = Depends(get_permission_checker),
) -> CreateNote:
    return CreateNote(repo, clock, checker)
```

### 15.8 `app/notes/api/router.py`

```python
from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user
from app.users.domain.entities import User
from ..application.use_cases import CreateNote
from .schemas import CreateNoteRequest, NoteResponse
from .dependencies import get_create_note

router = APIRouter()

@router.post("/", response_model=NoteResponse)
async def create_note(
    request: CreateNoteRequest,
    user: User = Depends(get_current_user),
    use_case: CreateNote = Depends(get_create_note),
) -> NoteResponse:
    note = await use_case.execute(user, request.title, request.body)
    return NoteResponse(
        id=note.id, title=note.title, body=note.body, created_at=note.created_at,
    )
```

## 16. Use Case Coverage

The system implements functionality grouped into the following areas. Each is implemented as one or more use cases in the corresponding domain's `application/` layer.

| Area | Domain(s) | Examples |
|---|---|---|
| Server Management | `servers/` | Create, configure, start, stop, restart, import, export |
| Player Management | `groups/` | Create group, attach to servers, manage OP/whitelist |
| Real-time Monitoring | `websockets/`, `servers/` | Stream logs, broadcast status |
| Backup Management | `backups/` | Create, restore, schedule, list |
| File Management | `files/` | Read, write, history, rollback, search |
| User Account | `users/`, `auth/` | Register, approve, change password, manage role |
| Auditing | `audit/` | Record activity, query logs |
| Version Management | `versions/` | List supported versions, refresh, download JAR |

Detailed use case lists per domain are maintained inside each domain's `application/use_cases.py` (one class per use case, named with a present-tense verb).

## 17. Migration Guide

This architecture is the **target state**. The codebase is migrating toward it under Issue #149 (parent) and its sub-issues. Migration is incremental.

### 17.1 General principles for migration

- Every refactor PR must maintain API backward compatibility (endpoints, request/response shapes) unless a breaking change is explicitly approved
- A domain may be migrated one layer at a time, starting from the persistence layer (introduce a Repository Port + Adapter, then move use cases off direct ORM access)
- Until a domain is fully migrated, its old structure remains valid; this document is the target, not a description of every file's current state

### 17.2 Migration order (recommended)

1. **Introduce Ports** for the most volatile dependencies (persistence, permission checks)
2. **Move business logic** from existing fat services into use cases that depend on Ports
3. **Replace direct framework calls** in routers with use case invocations
4. **Split large modules** following Section 6.1 thresholds
5. **Reorganize** files into the standard layout once the logic is in place

### 17.3 Tracking

Migration progress is tracked under Issue #149 and its sub-issues (#153–#160). Refer to those issues for the current scope and assigned owners.

---

## References

- Historical implementation: [`docs/ARCHITECTURE_LEGACY.md`](ARCHITECTURE_LEGACY.md)
- Dependency management policy: [`docs/DEPENDENCIES.md`](DEPENDENCIES.md)
- Refactor parent issue: [#149](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/149)
- This document's authoring issue: [#153](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/153)
