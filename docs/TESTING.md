# Testing Policy

This document defines the **test hierarchy** for the Minecraft Server Dashboard API: where each test belongs, how to classify a new test, which pytest markers to use, and how to keep the suite fast and meaningful.

It is the canonical reference superseding the brief sketch in [`ARCHITECTURE.md` §13.3](./ARCHITECTURE.md). When the two disagree, this document wins.

> **Scope.** This document is about the *layering* of tests, not about coverage targets or code-review rules. Coverage policy lives in CI and `CLAUDE.md` (Rule 3 — Test Code Development Process).

---

## 1. Three Layers

Tests live under `tests/<layer>/<domain>/` and are classified into exactly one of three layers:

| Layer | Directory | What it covers | I/O policy | Typical speed |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | `domain/`, `application/` use cases, pure helpers | All Ports replaced by in-memory **Fakes/stubs**. No real DB, filesystem, subprocess, sockets, or HTTP. | < 100 ms / test |
| **Integration** | `tests/integration/` | `adapters/` and the `api/` boundary | **Real DB** (worker-scoped SQLite) and FastAPI `TestClient` allowed. No real subprocess, no real network. | 100 ms – 1 s / test |
| **Infrastructure** | `tests/infrastructure/` | Behaviour that depends on real OS resources — subprocesses, filesystem layout, sockets, WebSockets at the transport level, real HTTP through `aiohttp` | Real I/O allowed. May spawn processes (e.g. Minecraft server JAR) or bind ports. | ≥ 1 s / test, often more |

Each layer mirrors the production layout: `tests/<layer>/<domain>/test_<thing>.py`. For example, the application service `app/servers/application/...` is tested in `tests/unit/servers/...`; its SQLAlchemy adapter is tested in `tests/integration/servers/...`.

> **During the Issue #149 / #170 refactor**, some legacy tests are still organized by topic rather than by layer (e.g. `tests/unit/services/test_minecraft_server.py` exercises a god-class spanning all layers). They are accepted in place and migrated as their target services are split. **New tests must follow the layered structure.**

---

## 2. Classification Decision

Use this in order. The **first** rule that matches wins.

1. **Does the test touch a real subprocess, socket, real filesystem path outside `tmp_path`, or make a real HTTP/network call?**
   → `infrastructure/`.
2. **Does the test go through a FastAPI router (`TestClient`) or hit a real DB session (`db` fixture, SQLAlchemy `Session`)?**
   → `integration/`.
3. **Otherwise** (pure logic, or all dependencies replaced by Fakes / `Mock` / in-memory doubles):
   → `unit/`.

### Examples

| Test does… | Layer |
|---|---|
| Asserts that `Server.create()` raises on invalid name | `unit/` |
| Verifies `AuthorizationService` permission logic with a `Mock` user repository | `unit/` |
| Hits `POST /api/v1/users/register` via `TestClient` and reads the DB row back | `integration/` |
| Persists and re-reads a `Server` via `SqlAlchemyServerRepository` with the worker SQLite DB | `integration/` |
| Spawns a real `java -jar` Minecraft process and asserts it daemonizes | `infrastructure/` |
| Drives an `aiohttp` mock against the real `ClientSession` to verify chunked-download logic | `infrastructure/` |
| Verifies xdist worker DB isolation by reading `tempfile.gettempdir()` | `infrastructure/` |

### What a "Fake" looks like

A Fake is an in-memory implementation of a Port (a `Protocol` defined in `domain/`). It replaces a real Adapter in unit tests so the use case can run without DB or I/O.

```python
class FakeServerRepository:
    def __init__(self) -> None:
        self._store: dict[int, Server] = {}
        self._next_id = 1

    async def add(self, server: Server) -> Server:
        server.id = self._next_id
        self._next_id += 1
        self._store[server.id] = server
        return server

    async def get(self, server_id: int) -> Server | None:
        return self._store.get(server_id)
```

Place Fakes in `tests/unit/<domain>/fakes.py` and reuse across tests in that domain. They are **not** test code generators — keep them small and behavioural, not over-engineered.

---

## 3. Pytest Markers

The project uses **pytest-xdist** with `--dist loadscope` for parallel execution. The marker set is intentionally small; add a new marker only when an existing one cannot express the constraint.

| Marker | Meaning | When to apply | Effect |
|---|---|---|---|
| `@pytest.mark.asyncio` | Async test function | Auto-applied via `asyncio_mode = auto` in `pytest.ini`. **You generally do not need to write this explicitly.** | Runs the coroutine on the asyncio loop. |
| `@pytest.mark.slow` | Test takes ≥ 1 s or spawns a subprocess | Any infrastructure test that boots a real process; any test that intentionally sleeps or waits on a real timeout | Skipped from quick local runs (`-m 'not slow'`); always run in CI full suite. |
| `@pytest.mark.requires_java` | Needs a working JRE on `PATH` | Real Minecraft lifecycle tests | Skipped automatically when Java is not detected (see `tests/conftest.py`). |

### Markers we have deliberately *not* introduced

- **`@pytest.mark.unit` / `@pytest.mark.integration` / `@pytest.mark.infrastructure`** — redundant with the directory layout. Selection is done with `-k` / path filters (`uv run pytest tests/unit`), not markers.
- **`@pytest.mark.serial`** — `--dist loadscope` already groups tests by module, and the worker-scoped DB (`get_worker_db_path()` in `tests/conftest.py`) handles isolation. If a test genuinely cannot run in parallel, fix the isolation issue rather than serializing.

### Registration

Markers must be declared in `pyproject.toml` (or `pytest.ini`) under `[tool.pytest.ini_options].markers` to prevent typos becoming silent no-ops:

```ini
markers =
    slow: test is slow (>= 1s) or spawns a subprocess
    requires_java: test needs a working JRE on PATH
```

> **Note:** `slow` and `requires_java` are introduced by this document. Wiring them up in `pytest.ini` and adding the Java-detection skip helper is tracked by Issue #171 (pre-commit test scope) since both Issues share the goal of making the quick-feedback loop fast.

---

## 4. Running the Suite

| Goal | Command |
|---|---|
| Fast local feedback (unit only) | `uv run pytest tests/unit` |
| API & adapter contracts | `uv run pytest tests/integration` |
| Real-process / OS-resource tests | `uv run pytest tests/infrastructure -m slow` |
| Everything except slow | `uv run pytest -m 'not slow'` |
| Full suite (CI) | `just test` |
| Single test by path | `uv run pytest tests/unit/services/test_authorization_service.py::TestAuthorizationServiceServerAccess::test_admin_can_access` |

`just test` runs the full suite with the project's standard options (`-n auto --dist loadscope`). Use the path-scoped commands when iterating locally to keep the loop tight; rely on CI to catch slow-test regressions.

---

## 5. Sample Tests

### 5.1 Unit — use case with a Fake port

```python
# tests/unit/notes/test_create_note.py
import pytest
from datetime import datetime
from app.notes.application.use_cases import CreateNote
from app.notes.domain.entities import Note
from tests.unit.notes.fakes import FakeNoteRepository


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, 12, 0, 0)


async def test_create_note_persists_and_returns_entity():
    repo = FakeNoteRepository()
    use_case = CreateNote(notes=repo, clock=FixedClock())

    note = await use_case.execute(owner_id=42, title="hello", body="world")

    assert note.id is not None
    assert await repo.get(note.id) == note


async def test_create_note_rejects_empty_title():
    use_case = CreateNote(notes=FakeNoteRepository(), clock=FixedClock())

    with pytest.raises(ValueError):
        await use_case.execute(owner_id=42, title="", body="world")
```

### 5.2 Integration — API + real DB

```python
# tests/integration/notes/test_notes_router.py
from fastapi import status


def test_create_note_via_api(client, normal_user_token):
    response = client.post(
        "/api/v1/notes",
        json={"title": "first", "body": "hello"},
        headers={"Authorization": f"Bearer {normal_user_token}"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["title"] == "first"
```

The `client` and `*_token` fixtures are defined in `tests/conftest.py` and back onto the worker-scoped SQLite DB.

### 5.3 Infrastructure — real subprocess

```python
# tests/infrastructure/servers/test_jar_launch.py
import pytest
from app.servers.infrastructure.process import launch_server_process


@pytest.mark.slow
@pytest.mark.requires_java
async def test_launch_server_writes_pid_file(tmp_path):
    pid_path = tmp_path / "server.pid"

    proc = await launch_server_process(
        jar_path=tmp_path / "fake-server.jar",
        cwd=tmp_path,
        pid_path=pid_path,
    )
    try:
        assert pid_path.exists()
        assert int(pid_path.read_text()) == proc.pid
    finally:
        proc.terminate()
        await proc.wait()
```

---

## 6. Authoring Checklist

When adding a test, verify in order:

- [ ] Decided the layer with §2 (the first matching rule wins)
- [ ] Placed the file at `tests/<layer>/<domain>/test_<thing>.py`
- [ ] Replaced every Port with a Fake (unit) **or** is honest about touching real I/O (integration / infrastructure)
- [ ] Applied `@pytest.mark.slow` if the test takes ≥ 1 s or spawns a subprocess
- [ ] Applied `@pytest.mark.requires_java` if it needs a JRE
- [ ] Avoided redundant `@pytest.mark.asyncio` (auto-mode handles it)
- [ ] The test name describes the **observable behaviour**, not the implementation (e.g. `test_rejects_empty_title`, not `test_validate_title_raises_value_error`)

---

## 7. Related Issues

- **#149** — Layered refactor (the target layout this policy mirrors)
- **#151** — Testing redesign (parent issue)
- **#167** — This policy (test hierarchy documentation)
- **#170** — Migrating existing tests to the layered layout
- **#171** — pre-commit / CI test scope (introduces the marker wiring)
