"""Coverage tests for `GroupFileSyncer`.

These cover branches the legacy `GroupFileService` mock-coupled tests
used to assert on, restated against the new in-memory fakes:

- `_build_ops_and_whitelist` content correctness (ops.json / whitelist.json)
- `PathValidator.validate_safe_path` SecurityError → FileOperationException
- 3-attempt × exponential backoff retry semantics
  (success / fail-then-succeed / all-fail)
- Single-server retry path used by `attach_group_to_server`
- `batch_update_server_files` partial failure aggregation
- Real-time command failures are swallowed
"""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.core.exceptions import FileOperationException
from app.groups.application.file_syncer import (
    GroupFileSyncer,
    _build_ops_and_whitelist,
)
from app.groups.domain.entities import AttachServerGroupCommand
from app.groups.models import GroupType
from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerType
from tests.unit.files.fakes import FakeServerReadPort
from tests.unit.groups.fakes import (
    FakeGroupRepository,
    FakeServerGroupRepository,
    RecordingRealTimeCommands,
    make_group_entity,
)

# ---------------------------------------------------------------------------
# Pure-function content correctness
# ---------------------------------------------------------------------------


def test_build_ops_and_whitelist_op_group_only():
    op_group = make_group_entity(
        id=1,
        owner_id=1,
        type=GroupType.op,
        players=[{"uuid": "u1", "username": "n1"}],
    )
    ops, whitelist = _build_ops_and_whitelist([op_group])
    assert ops == [
        {"uuid": "u1", "name": "n1", "level": 4, "bypassesPlayerLimit": True}
    ]
    assert whitelist == []


def test_build_ops_and_whitelist_whitelist_group_only():
    wl_group = make_group_entity(
        id=1,
        owner_id=1,
        type=GroupType.whitelist,
        players=[{"uuid": "u1", "username": "n1"}],
    )
    ops, whitelist = _build_ops_and_whitelist([wl_group])
    assert ops == []
    assert whitelist == [{"uuid": "u1", "name": "n1"}]


def test_build_ops_and_whitelist_dedup_on_uuid():
    """Two groups containing the same player UUID should only emit
    one entry in each output list."""
    g1 = make_group_entity(
        id=1, owner_id=1, type=GroupType.op,
        players=[{"uuid": "u1", "username": "n1"}],
    )
    g2 = make_group_entity(
        id=2, owner_id=1, type=GroupType.op,
        players=[{"uuid": "u1", "username": "n1-different"}],
    )
    ops, _ = _build_ops_and_whitelist([g1, g2])
    assert len(ops) == 1
    assert ops[0]["name"] == "n1"  # first wins


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def group_repo() -> FakeGroupRepository:
    return FakeGroupRepository()


@pytest.fixture
def server_group_repo(group_repo: FakeGroupRepository) -> FakeServerGroupRepository:
    return FakeServerGroupRepository(group_repo)


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort()


@pytest.fixture
def rt_commands() -> RecordingRealTimeCommands:
    return RecordingRealTimeCommands()


@pytest.fixture
def syncer(
    server_group_repo: FakeServerGroupRepository,
    server_read: FakeServerReadPort,
    rt_commands: RecordingRealTimeCommands,
) -> GroupFileSyncer:
    return GroupFileSyncer(
        server_groups=server_group_repo,
        server_read=server_read,
        real_time_commands=rt_commands,
    )


def _register_server(
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
    *,
    server_id: int = 1,
    name: str = "srv",
) -> Path:
    server_dir = tmp_path / "servers" / name
    server_dir.mkdir(parents=True, exist_ok=True)
    server_read.set_server(
        ServerEntity(
            id=server_id,
            name=name,
            directory_path=str(server_dir),
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=1,
        )
    )
    server_group_repo.register_server(server_id, name, str(server_dir))
    return server_dir


# ---------------------------------------------------------------------------
# update_server_files content correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_server_files_writes_ops_and_whitelist(
    syncer: GroupFileSyncer,
    group_repo: FakeGroupRepository,
    server_group_repo: FakeServerGroupRepository,
    server_read: FakeServerReadPort,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # PathValidator is anchored at CWD-relative `servers/`; tmp_path
    # lives elsewhere on disk, so stub the validator out for this test.
    monkeypatch.setattr(
        "app.groups.application.file_syncer.PathValidator.validate_safe_path",
        lambda *a, **k: None,
    )
    server_dir = _register_server(server_read, server_group_repo, tmp_path)
    op_group = group_repo.seed(
        make_group_entity(
            id=1, owner_id=1, type=GroupType.op,
            players=[{"uuid": "u1", "username": "n1"}],
        )
    )
    wl_group = group_repo.seed(
        make_group_entity(
            id=2, owner_id=1, type=GroupType.whitelist,
            players=[{"uuid": "u2", "username": "n2"}],
        )
    )
    await server_group_repo.attach(
        AttachServerGroupCommand(server_id=1, group_id=op_group.id, priority=1)
    )
    await server_group_repo.attach(
        AttachServerGroupCommand(server_id=1, group_id=wl_group.id, priority=0)
    )

    await syncer.update_server_files(1)

    ops_path = server_dir / "ops.json"
    wl_path = server_dir / "whitelist.json"
    assert ops_path.exists()
    assert wl_path.exists()
    ops_payload = json.loads(ops_path.read_text())
    wl_payload = json.loads(wl_path.read_text())
    assert ops_payload == [
        {"uuid": "u1", "name": "n1", "level": 4, "bypassesPlayerLimit": True}
    ]
    assert wl_payload == [{"uuid": "u2", "name": "n2"}]


@pytest.mark.asyncio
async def test_update_server_files_unknown_server_is_noop(
    syncer: GroupFileSyncer,
):
    # No exception, just a debug log line; nothing to assert except absence of raise
    await syncer.update_server_files(999)


@pytest.mark.asyncio
async def test_update_server_files_security_error_wraps_to_file_op_exception(
    syncer: GroupFileSyncer,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    """`PathValidator.validate_safe_path` raises `SecurityError` for
    bogus directory paths; the syncer must convert to
    `FileOperationException`. Patch the validator so we don't depend on
    the real path-juggling rules."""
    _register_server(server_read, server_group_repo, tmp_path)
    from app.core.security import SecurityError

    with patch(
        "app.groups.application.file_syncer.PathValidator.validate_safe_path",
        side_effect=SecurityError("bad path"),
    ):
        with pytest.raises(FileOperationException):
            await syncer.update_server_files(1)


@pytest.mark.asyncio
async def test_update_server_files_realtime_failure_swallowed(
    syncer: GroupFileSyncer,
    group_repo: FakeGroupRepository,
    server_group_repo: FakeServerGroupRepository,
    server_read: FakeServerReadPort,
    rt_commands: RecordingRealTimeCommands,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A real-time command failure must not propagate — the file sync
    has already succeeded and the broadcast is best-effort."""
    monkeypatch.setattr(
        "app.groups.application.file_syncer.PathValidator.validate_safe_path",
        lambda *a, **k: None,
    )
    _register_server(server_read, server_group_repo, tmp_path)
    op_group = group_repo.seed(
        make_group_entity(
            id=1, owner_id=1, type=GroupType.op,
            players=[{"uuid": "u1", "username": "n1"}],
        )
    )
    await server_group_repo.attach(
        AttachServerGroupCommand(server_id=1, group_id=op_group.id, priority=0)
    )

    rt_commands.sync_op_should_raise = RuntimeError("boom")
    # Must not raise
    await syncer.update_server_files(1)


# ---------------------------------------------------------------------------
# batch_update_server_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_update_collects_partial_failures(
    syncer: GroupFileSyncer,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    """One server succeeds (writes files), a second is unknown (no-op)
    — so no exception. To force a failure, patch the path validator on
    one of two registered servers."""
    _register_server(server_read, server_group_repo, tmp_path, server_id=1, name="a")
    _register_server(server_read, server_group_repo, tmp_path, server_id=2, name="b")

    from app.core.security import SecurityError

    call_count = {"n": 0}

    def _selective(path: Any, base: Any) -> None:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise SecurityError("forced")

    with patch(
        "app.groups.application.file_syncer.PathValidator.validate_safe_path",
        side_effect=_selective,
    ):
        with pytest.raises(FileOperationException) as exc_info:
            await syncer.batch_update_server_files([1, 2])
    assert "Server 2" in str(exc_info.value) or "Server 1" in str(exc_info.value)


@pytest.mark.asyncio
async def test_batch_update_empty_list_is_noop(syncer: GroupFileSyncer):
    await syncer.batch_update_server_files([])


# ---------------------------------------------------------------------------
# Retry semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_succeeds_on_first_attempt(
    syncer: GroupFileSyncer,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
    server_read: FakeServerReadPort,
):
    """No attached servers → `update_all_affected_servers` is a no-op,
    so retry returns on first attempt without sleeping."""
    await syncer.update_all_affected_servers_with_retry(group_id=999)


@pytest.mark.asyncio
async def test_retry_fail_then_succeed(
    syncer: GroupFileSyncer,
    monkeypatch: pytest.MonkeyPatch,
):
    """First attempt raises; the second succeeds. Confirms the
    exponential-backoff branch is hit and the call eventually returns
    normally."""
    attempts = {"n": 0}

    async def _flaky(group_id: int) -> None:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")

    monkeypatch.setattr(syncer, "update_all_affected_servers", _flaky)

    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    await syncer.update_all_affected_servers_with_retry(group_id=1)
    assert attempts["n"] == 2
    # one backoff sleep (1.0 * (0 + 1) = 1.0) between attempts
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_retry_all_attempts_fail(
    syncer: GroupFileSyncer, monkeypatch: pytest.MonkeyPatch
):
    """All three attempts raise → `FileOperationException` with the
    last exception's message."""

    async def _always_explode(group_id: int) -> None:
        raise RuntimeError("doom")

    monkeypatch.setattr(syncer, "update_all_affected_servers", _always_explode)

    async def _record_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    with pytest.raises(FileOperationException) as exc_info:
        await syncer.update_all_affected_servers_with_retry(group_id=1)
    assert "after 3 attempts" in str(exc_info.value)


@pytest.mark.asyncio
async def test_single_server_retry_all_fail_reraises(
    syncer: GroupFileSyncer, monkeypatch: pytest.MonkeyPatch
):
    """update_single_server_with_retry re-raises the last exception
    (not wrapped) after all attempts fail."""

    async def _explode(server_id: int) -> None:
        raise RuntimeError("nope")

    monkeypatch.setattr(syncer, "update_server_files", _explode)

    async def _record_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    with pytest.raises(RuntimeError, match="nope"):
        await syncer.update_single_server_with_retry(server_id=1)


@pytest.mark.asyncio
async def test_single_server_retry_succeeds_after_failure(
    syncer: GroupFileSyncer, monkeypatch: pytest.MonkeyPatch
):
    """First attempt raises, second succeeds — must not re-raise."""
    attempts = {"n": 0}

    async def _flaky(server_id: int) -> None:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")

    monkeypatch.setattr(syncer, "update_server_files", _flaky)

    async def _record_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    await syncer.update_single_server_with_retry(server_id=1)
    assert attempts["n"] == 2
