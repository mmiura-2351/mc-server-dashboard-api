"""Integration tests for `SqlAlchemyServerGroupRepository`.

Cross-domain JOINs into `Server` are exercised here against a real
SQLAlchemy session: we hand-build minimal `Server` rows and assert
that the adapter materialises the right `AttachedGroupView` /
`AttachedServerView` shapes (priority ordering, player counts, status
passthrough).
"""

import pytest

from app.groups.adapters.repository import SqlAlchemyServerGroupRepository
from app.groups.domain.entities import AttachServerGroupCommand
from app.groups.models import Group, GroupType, ServerGroup
from app.servers.models import Server, ServerStatus
from tests.helpers.servers import make_server


@pytest.fixture
def repository(db) -> SqlAlchemyServerGroupRepository:
    return SqlAlchemyServerGroupRepository(db)


def _seed_group(db, owner_id: int, *, name: str = "g", type=GroupType.op) -> Group:
    row = Group(name=name, description=None, type=type, players=[], owner_id=owner_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_server(db, owner, *, name: str, directory_path: str = "./servers/x") -> Server:
    """Wrapper around `tests.helpers.servers.make_server` retaining the
    existing call sites' shape (name=, directory_path=)."""
    return make_server(
        db,
        owner,
        name=name,
        description=None,
        directory_path=directory_path,
    )


@pytest.mark.asyncio
async def test_attach_and_find(repository, db, admin_user):
    group = _seed_group(db, admin_user.id)
    server = _seed_server(db, admin_user, name="sA")

    entity = await repository.attach(
        AttachServerGroupCommand(server_id=server.id, group_id=group.id, priority=3)
    )
    db.commit()
    assert entity.id is not None
    assert entity.priority == 3

    found = await repository.find(server.id, group.id)
    assert found is not None
    assert found.priority == 3


@pytest.mark.asyncio
async def test_count_for_group(repository, db, admin_user):
    group = _seed_group(db, admin_user.id)
    s1 = _seed_server(db, admin_user, name="s1", directory_path="./servers/s1")
    s2 = _seed_server(db, admin_user, name="s2", directory_path="./servers/s2")

    await repository.attach(AttachServerGroupCommand(server_id=s1.id, group_id=group.id))
    await repository.attach(AttachServerGroupCommand(server_id=s2.id, group_id=group.id))
    db.commit()

    assert await repository.count_for_group(group.id) == 2


@pytest.mark.asyncio
async def test_list_server_ids_for_group(repository, db, admin_user):
    group = _seed_group(db, admin_user.id)
    s1 = _seed_server(db, admin_user, name="s1", directory_path="./servers/s1")
    s2 = _seed_server(db, admin_user, name="s2", directory_path="./servers/s2")

    await repository.attach(AttachServerGroupCommand(server_id=s1.id, group_id=group.id))
    await repository.attach(AttachServerGroupCommand(server_id=s2.id, group_id=group.id))
    db.commit()

    ids = await repository.list_server_ids_for_group(group.id)
    assert set(ids) == {s1.id, s2.id}


@pytest.mark.asyncio
async def test_list_groups_for_server_priority_desc(repository, db, admin_user):
    g_lo = _seed_group(db, admin_user.id, name="low")
    g_hi = _seed_group(db, admin_user.id, name="high")
    s = _seed_server(db, admin_user, name="srv")

    await repository.attach(
        AttachServerGroupCommand(server_id=s.id, group_id=g_lo.id, priority=1)
    )
    await repository.attach(
        AttachServerGroupCommand(server_id=s.id, group_id=g_hi.id, priority=9)
    )
    db.commit()

    groups = await repository.list_groups_for_server(s.id)
    assert [g.name for g in groups] == ["high", "low"]


@pytest.mark.asyncio
async def test_list_server_dirs_for_group(repository, db, admin_user):
    group = _seed_group(db, admin_user.id)
    s = _seed_server(db, admin_user, name="srv", directory_path="./servers/dirX")
    await repository.attach(AttachServerGroupCommand(server_id=s.id, group_id=group.id))
    db.commit()

    pairs = await repository.list_server_dirs_for_group(group.id)
    assert pairs == [(s.id, "./servers/dirX")]


@pytest.mark.asyncio
async def test_list_attachments_for_server_returns_view_with_player_count(
    repository, db, admin_user
):
    group = _seed_group(db, admin_user.id, name="ops")
    # seed players into the JSON column
    group.set_players(
        [
            {"uuid": "u1", "username": "n1"},
            {"uuid": "u2", "username": "n2"},
        ]
    )
    db.commit()
    s = _seed_server(db, admin_user, name="srv")
    await repository.attach(
        AttachServerGroupCommand(server_id=s.id, group_id=group.id, priority=4)
    )
    db.commit()

    views = await repository.list_attachments_for_server(s.id)
    assert len(views) == 1
    assert views[0].id == group.id
    assert views[0].priority == 4
    assert views[0].player_count == 2
    assert views[0].type == GroupType.op


@pytest.mark.asyncio
async def test_list_attachments_for_group_carries_server_status(
    repository, db, admin_user
):
    group = _seed_group(db, admin_user.id)
    s = _seed_server(db, admin_user, name="srvB", directory_path="./servers/srvB")
    await repository.attach(
        AttachServerGroupCommand(server_id=s.id, group_id=group.id, priority=2)
    )
    db.commit()

    views = await repository.list_attachments_for_group(group.id)
    assert len(views) == 1
    assert views[0].id == s.id
    assert views[0].name == "srvB"
    assert views[0].priority == 2
    # status is the enum, not its `.value`
    assert views[0].status == ServerStatus.stopped


@pytest.mark.asyncio
async def test_detach_returns_true_then_false(repository, db, admin_user):
    group = _seed_group(db, admin_user.id)
    s = _seed_server(db, admin_user, name="srv")
    await repository.attach(AttachServerGroupCommand(server_id=s.id, group_id=group.id))
    db.commit()

    ok = await repository.detach(s.id, group.id)
    db.commit()
    assert ok is True
    assert (
        db.query(ServerGroup)
        .filter(ServerGroup.server_id == s.id, ServerGroup.group_id == group.id)
        .first()
        is None
    )

    assert await repository.detach(s.id, group.id) is False
