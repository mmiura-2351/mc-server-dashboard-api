"""Behavioural tests for `GroupService` using in-memory fakes.

Exercises the use cases without a real DB or filesystem. The fakes
act as the persistence layer; the file syncer is wired with a real
`GroupFileSyncer` but pointed at a `tmp_path`-rooted server
directory so we can assert on ops.json / whitelist.json content
correctness.
"""

from pathlib import Path
from typing import Any

import pytest

from app.groups.application.file_syncer import GroupFileSyncer
from app.groups.application.service import GroupService
from app.groups.domain.entities import AttachServerGroupCommand
from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupHasAttachmentsError,
    GroupNotFoundError,
    PlayerNotFoundInGroup,
    ServerGroupAttachmentExistsError,
    ServerGroupAttachmentNotFoundError,
    ServerNotFoundForAttachment,
)
from app.groups.models import GroupType
from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerStatus, ServerType
from tests.unit.audit.fakes import FakeAuditWriter
from tests.unit.files.fakes import FakeServerReadPort
from tests.unit.groups.fakes import (
    FakeGroupRepository,
    FakeGroupsUnitOfWork,
    FakeServerGroupRepository,
    RecordingRealTimeCommands,
    make_group_entity,
)

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
def uow(
    group_repo: FakeGroupRepository,
    server_group_repo: FakeServerGroupRepository,
) -> FakeGroupsUnitOfWork:
    return FakeGroupsUnitOfWork(groups=group_repo, server_groups=server_group_repo)


@pytest.fixture
def server_read() -> FakeServerReadPort:
    return FakeServerReadPort()


@pytest.fixture
def audit() -> FakeAuditWriter:
    return FakeAuditWriter()


@pytest.fixture
def rt_commands() -> RecordingRealTimeCommands:
    return RecordingRealTimeCommands()


@pytest.fixture(autouse=True)
def _stub_path_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """The file syncer guards against directory traversal with
    `PathValidator.validate_safe_path`, anchored at CWD-relative
    `servers/`. `tmp_path` lives elsewhere on disk, so stub the
    validator for these unit tests. The validator's behaviour itself is
    covered separately in `test_file_syncer`."""
    monkeypatch.setattr(
        "app.groups.application.file_syncer.PathValidator.validate_safe_path",
        lambda *a, **k: None,
    )


@pytest.fixture
def file_syncer(
    server_group_repo: FakeServerGroupRepository,
    server_read: FakeServerReadPort,
    rt_commands: RecordingRealTimeCommands,
) -> GroupFileSyncer:
    return GroupFileSyncer(
        server_groups=server_group_repo,
        server_read=server_read,
        real_time_commands=rt_commands,
    )


@pytest.fixture
def service(
    uow: FakeGroupsUnitOfWork,
    server_read: FakeServerReadPort,
    audit: FakeAuditWriter,
    file_syncer: GroupFileSyncer,
) -> GroupService:
    return GroupService(
        uow=uow,
        server_read=server_read,
        audit=audit,
        file_syncer=file_syncer,
    )


def _register_server(
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
    *,
    server_id: int = 1,
    owner_id: int = 1,
    name: str = "srv",
    status: ServerStatus = ServerStatus.stopped,
) -> Path:
    """Register a server in the ServerReadPort + ServerGroup fake, and
    create its on-disk directory so the syncer can write files."""
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
            owner_id=owner_id,
        )
    )
    server_group_repo.register_server(server_id, name, str(server_dir), status)
    return server_dir


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_group_happy_path(
    service: GroupService, uow: FakeGroupsUnitOfWork, audit: FakeAuditWriter
):
    entity = await service.create_group(
        actor_id=1, name="ops", group_type=GroupType.op, description="d"
    )
    assert entity.id is not None
    assert entity.name == "ops"
    assert entity.type == GroupType.op
    assert uow.committed == 1
    assert len(audit.events) == 1
    assert audit.events[0].action == "group_created"


@pytest.mark.asyncio
async def test_create_group_duplicate_name_raises(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="dup"))
    with pytest.raises(GroupAlreadyExistsError):
        await service.create_group(
            actor_id=1, name="dup", group_type=GroupType.op
        )


@pytest.mark.asyncio
async def test_create_group_same_name_different_owner_allowed(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(make_group_entity(id=1, owner_id=99, name="shared"))
    entity = await service.create_group(
        actor_id=1, name="shared", group_type=GroupType.op
    )
    assert entity.owner_id == 1


@pytest.mark.asyncio
async def test_list_groups_passthrough_no_filter(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="a", type=GroupType.op))
    group_repo.seed(
        make_group_entity(id=2, owner_id=99, name="b", type=GroupType.whitelist)
    )
    out = await service.list_groups(actor_id=1)
    assert {e.id for e in out} == {1, 2}


@pytest.mark.asyncio
async def test_list_groups_filter_by_type(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="a", type=GroupType.op))
    group_repo.seed(
        make_group_entity(id=2, owner_id=1, name="b", type=GroupType.whitelist)
    )
    out = await service.list_groups(actor_id=1, group_type=GroupType.op)
    assert {e.id for e in out} == {1}


@pytest.mark.asyncio
async def test_get_group_not_found(service: GroupService):
    with pytest.raises(GroupNotFoundError):
        await service.get_group(actor_id=1, group_id=999)


@pytest.mark.asyncio
async def test_update_group_renames_and_audits(
    service: GroupService,
    group_repo: FakeGroupRepository,
    audit: FakeAuditWriter,
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="old"))
    updated = await service.update_group(actor_id=1, group_id=1, name="new")
    assert updated.name == "new"
    assert any(e.action == "group_updated" for e in audit.events)


@pytest.mark.asyncio
async def test_update_group_name_collision_raises(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="a"))
    group_repo.seed(make_group_entity(id=2, owner_id=1, name="b"))
    with pytest.raises(GroupAlreadyExistsError):
        await service.update_group(actor_id=1, group_id=2, name="a")


@pytest.mark.asyncio
async def test_update_group_same_name_is_noop_no_collision_check(
    service: GroupService,
    group_repo: FakeGroupRepository,
):
    """Legacy contract: same-name update bypasses the rename collision
    check, and (because the name did not actually change) no rename
    audit fires."""
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="keep"))
    # Even with a name collision present for ANOTHER group with the
    # same name, the same-name update must succeed.
    group_repo.seed(make_group_entity(id=2, owner_id=1, name="keep"))
    updated = await service.update_group(actor_id=1, group_id=1, name="keep")
    assert updated.name == "keep"


@pytest.mark.asyncio
async def test_delete_group_refuses_when_attached(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_group_repo: FakeServerGroupRepository,
):
    group_repo.seed(make_group_entity(id=1, owner_id=1))
    await server_group_repo.attach(
        AttachServerGroupCommand(server_id=1, group_id=1, priority=0)
    )
    with pytest.raises(GroupHasAttachmentsError):
        await service.delete_group(actor_id=1, group_id=1)


@pytest.mark.asyncio
async def test_delete_group_unknown_raises(service: GroupService):
    with pytest.raises(GroupNotFoundError):
        await service.delete_group(actor_id=1, group_id=999)


@pytest.mark.asyncio
async def test_delete_group_happy_path(
    service: GroupService,
    group_repo: FakeGroupRepository,
    audit: FakeAuditWriter,
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, name="x"))
    await service.delete_group(actor_id=1, group_id=1)
    assert await group_repo.get(1) is None
    assert any(e.action == "group_deleted" for e in audit.events)


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_player_with_uuid_and_username(
    service: GroupService,
    group_repo: FakeGroupRepository,
    audit: FakeAuditWriter,
):
    group_repo.seed(make_group_entity(id=1, owner_id=1, type=GroupType.op))
    entity = await service.add_player(
        actor_id=1,
        group_id=1,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        username="alice",
    )
    assert len(entity.players) == 1
    assert entity.players[0]["username"] == "alice"
    assert any(e.action == "player_added_to_group" for e in audit.events)


@pytest.mark.asyncio
async def test_add_player_requires_uuid_or_username(service: GroupService):
    with pytest.raises(ValueError):
        await service.add_player(actor_id=1, group_id=1)


@pytest.mark.asyncio
async def test_add_player_resolves_username_from_uuid(
    service: GroupService,
    group_repo: FakeGroupRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    """If username missing, fall through to MinecraftAPIService;
    if that returns None, fall back to the first-8-chars-of-UUID
    placeholder."""
    group_repo.seed(make_group_entity(id=1, owner_id=1))

    from app.services import minecraft_api_service as mapi

    async def _fake_get_username_from_uuid(uuid: str) -> Any:
        return None  # simulate API miss

    monkeypatch.setattr(
        mapi.MinecraftAPIService,
        "get_username_from_uuid",
        _fake_get_username_from_uuid,
    )

    entity = await service.add_player(
        actor_id=1,
        group_id=1,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    # Offline fallback: first 8 chars of UUID become the username
    assert entity.players[0]["username"] == "aaaaaaaa"


@pytest.mark.asyncio
async def test_add_player_offline_uuid_fallback_from_username(
    service: GroupService,
    group_repo: FakeGroupRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    """If only `username` is supplied and Mojang returns None, the
    service falls back to `generate_offline_uuid`."""
    group_repo.seed(make_group_entity(id=1, owner_id=1))

    from app.services import minecraft_api_service as mapi

    async def _fake_get_uuid_from_username(name: str) -> Any:
        return None  # simulate API miss

    monkeypatch.setattr(
        mapi.MinecraftAPIService,
        "get_uuid_from_username",
        _fake_get_uuid_from_username,
    )

    entity = await service.add_player(
        actor_id=1, group_id=1, username="alice"
    )
    # Got SOMETHING as a uuid (offline-generated)
    assert entity.players[0]["uuid"]
    assert entity.players[0]["username"] == "alice"


@pytest.mark.asyncio
async def test_add_player_to_missing_group_raises(service: GroupService):
    with pytest.raises(GroupNotFoundError):
        await service.add_player(
            actor_id=1,
            group_id=999,
            uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            username="alice",
        )


@pytest.mark.asyncio
async def test_remove_player_happy_path(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(
        make_group_entity(
            id=1,
            owner_id=1,
            players=[
                {"uuid": "u1", "username": "n1"},
                {"uuid": "u2", "username": "n2"},
            ],
        )
    )
    entity = await service.remove_player(actor_id=1, group_id=1, uuid="u1")
    assert [p["uuid"] for p in entity.players] == ["u2"]


@pytest.mark.asyncio
async def test_remove_player_unknown_uuid_raises(
    service: GroupService, group_repo: FakeGroupRepository
):
    group_repo.seed(
        make_group_entity(
            id=1, owner_id=1, players=[{"uuid": "u1", "username": "n1"}]
        )
    )
    with pytest.raises(PlayerNotFoundInGroup):
        await service.remove_player(actor_id=1, group_id=1, uuid="ghost")


@pytest.mark.asyncio
async def test_remove_player_missing_group_raises(service: GroupService):
    with pytest.raises(GroupNotFoundError):
        await service.remove_player(actor_id=1, group_id=999, uuid="u1")


@pytest.mark.asyncio
async def test_add_player_sync_failure_does_not_rollback(
    service: GroupService,
    group_repo: FakeGroupRepository,
    file_syncer: GroupFileSyncer,
    monkeypatch: pytest.MonkeyPatch,
    audit: FakeAuditWriter,
):
    """Legacy contract: file-sync failure after a successful player
    add must NOT roll back the DB write; the audit event still fires."""
    group_repo.seed(make_group_entity(id=1, owner_id=1))

    async def _explode(*a: Any, **k: Any) -> None:
        raise RuntimeError("sync exploded")

    monkeypatch.setattr(
        file_syncer, "update_all_affected_servers_with_retry", _explode
    )

    entity = await service.add_player(
        actor_id=1,
        group_id=1,
        uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        username="alice",
    )
    assert len(entity.players) == 1
    # DB write was kept
    persisted = await group_repo.get(1)
    assert persisted is not None
    assert len(persisted.players) == 1
    # Audit still emitted post-commit
    assert any(e.action == "player_added_to_group" for e in audit.events)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_requires_owner_or_admin(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    group_repo.seed(make_group_entity(id=1, owner_id=99))
    _register_server(
        server_read,
        server_group_repo,
        tmp_path,
        server_id=1,
        owner_id=42,
        name="srv-not-mine",
    )
    with pytest.raises(GroupAccessError):
        await service.attach_group_to_server(
            actor_id=99,
            actor_is_admin=False,
            server_id=1,
            group_id=1,
        )


@pytest.mark.asyncio
async def test_attach_allows_server_owner(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
    audit: FakeAuditWriter,
):
    group_repo.seed(make_group_entity(id=1, owner_id=42, type=GroupType.op))
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    await service.attach_group_to_server(
        actor_id=42, actor_is_admin=False, server_id=1, group_id=1, priority=5
    )
    attached = await server_group_repo.find(1, 1)
    assert attached is not None
    assert attached.priority == 5
    assert any(e.action == "group_attached_to_server" for e in audit.events)


@pytest.mark.asyncio
async def test_attach_admin_allowed_regardless_of_owner(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    group_repo.seed(make_group_entity(id=1, owner_id=99))
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    # admin viewer who does not own anything
    await service.attach_group_to_server(
        actor_id=99, actor_is_admin=True, server_id=1, group_id=1
    )
    assert await server_group_repo.find(1, 1) is not None


@pytest.mark.asyncio
async def test_attach_server_not_found(
    service: GroupService,
    group_repo: FakeGroupRepository,
):
    group_repo.seed(make_group_entity(id=1, owner_id=42))
    with pytest.raises(ServerNotFoundForAttachment):
        await service.attach_group_to_server(
            actor_id=42, actor_is_admin=True, server_id=999, group_id=1
        )


@pytest.mark.asyncio
async def test_attach_group_not_found(
    service: GroupService,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    with pytest.raises(GroupNotFoundError):
        await service.attach_group_to_server(
            actor_id=42, actor_is_admin=True, server_id=1, group_id=999
        )


@pytest.mark.asyncio
async def test_attach_duplicate_raises(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    group_repo.seed(make_group_entity(id=1, owner_id=42))
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    await service.attach_group_to_server(
        actor_id=42, actor_is_admin=True, server_id=1, group_id=1
    )
    with pytest.raises(ServerGroupAttachmentExistsError):
        await service.attach_group_to_server(
            actor_id=42, actor_is_admin=True, server_id=1, group_id=1
        )


@pytest.mark.asyncio
async def test_attach_file_sync_failure_does_not_rollback(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    file_syncer: GroupFileSyncer,
    tmp_path: Path,
    audit: FakeAuditWriter,
    monkeypatch: pytest.MonkeyPatch,
):
    """attach() commit succeeds → file sync raises → attachment persists,
    audit still fires. Mirrors `add_player` behaviour and the legacy
    contract."""
    group_repo.seed(make_group_entity(id=1, owner_id=42, type=GroupType.op))
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )

    async def _explode(*a: Any, **k: Any) -> None:
        raise RuntimeError("sync exploded")

    monkeypatch.setattr(
        file_syncer, "update_single_server_with_retry", _explode
    )

    await service.attach_group_to_server(
        actor_id=42, actor_is_admin=False, server_id=1, group_id=1
    )
    # attachment persisted
    assert await server_group_repo.find(1, 1) is not None
    assert any(e.action == "group_attached_to_server" for e in audit.events)


@pytest.mark.asyncio
async def test_detach_unknown_attachment_raises(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    group_repo.seed(make_group_entity(id=1, owner_id=42))
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    with pytest.raises(ServerGroupAttachmentNotFoundError):
        await service.detach_group_from_server(
            actor_id=42, actor_is_admin=False, server_id=1, group_id=1
        )


@pytest.mark.asyncio
async def test_detach_op_group_carries_removed_players(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    file_syncer: GroupFileSyncer,
    rt_commands: RecordingRealTimeCommands,
    tmp_path: Path,
):
    """Legacy contract: when detaching an OP group, the removed-players
    list must be passed to the real-time deop broadcast."""
    group_repo.seed(
        make_group_entity(
            id=1,
            owner_id=42,
            type=GroupType.op,
            players=[{"uuid": "u1", "username": "n1"}],
        )
    )
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    await service.attach_group_to_server(
        actor_id=42, actor_is_admin=False, server_id=1, group_id=1
    )
    rt_commands.calls.clear()
    await service.detach_group_from_server(
        actor_id=42, actor_is_admin=False, server_id=1, group_id=1
    )
    handle_calls = [c for c in rt_commands.calls if c[0] == "handle_group_change_commands"]
    assert handle_calls, "real-time detach broadcast was not invoked"
    last = handle_calls[-1]
    assert last[2]["removed_players"] == [{"uuid": "u1", "username": "n1"}]


@pytest.mark.asyncio
async def test_get_server_groups_returns_attached_views(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    group_repo.seed(
        make_group_entity(
            id=1,
            owner_id=42,
            name="ops",
            players=[{"uuid": "u1", "username": "n1"}],
        )
    )
    _register_server(
        server_read, server_group_repo, tmp_path, server_id=1, owner_id=42
    )
    await service.attach_group_to_server(
        actor_id=42, actor_is_admin=False, server_id=1, group_id=1, priority=7
    )

    views = await service.get_server_groups(actor_id=42, server_id=1)
    assert len(views) == 1
    assert views[0].id == 1
    assert views[0].priority == 7
    assert views[0].player_count == 1


@pytest.mark.asyncio
async def test_get_group_servers_returns_attached_views(
    service: GroupService,
    group_repo: FakeGroupRepository,
    server_read: FakeServerReadPort,
    server_group_repo: FakeServerGroupRepository,
    tmp_path: Path,
):
    group_repo.seed(make_group_entity(id=1, owner_id=42))
    _register_server(
        server_read,
        server_group_repo,
        tmp_path,
        server_id=1,
        owner_id=42,
        name="alpha",
    )
    await service.attach_group_to_server(
        actor_id=42, actor_is_admin=False, server_id=1, group_id=1, priority=3
    )

    views = await service.get_group_servers(actor_id=42, group_id=1)
    assert [v.name for v in views] == ["alpha"]
    assert views[0].priority == 3
    assert views[0].status == ServerStatus.stopped


@pytest.mark.asyncio
async def test_get_group_servers_unknown_group(
    service: GroupService,
):
    with pytest.raises(GroupNotFoundError):
        await service.get_group_servers(actor_id=1, group_id=999)
