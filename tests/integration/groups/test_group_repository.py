"""Integration tests for `SqlAlchemyGroupRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not** commit
on its own (the UoW owns transactions in production), so write-path
tests call `db.commit()` explicitly after staging changes.
"""

import pytest

from app.groups.adapters.repository import SqlAlchemyGroupRepository
from app.groups.domain.entities import (
    CreateGroupCommand,
    GroupListSpec,
    UpdateGroupCommand,
)
from app.groups.domain.exceptions import (
    GroupNotFoundError,
    PlayerNotFoundInGroup,
)
from app.groups.models import Group, GroupType


@pytest.fixture
def repository(db) -> SqlAlchemyGroupRepository:
    return SqlAlchemyGroupRepository(db)


def _seed_group(
    db,
    owner_id: int,
    *,
    name: str = "g",
    type: GroupType = GroupType.op,
    players: list | None = None,
) -> Group:
    row = Group(
        name=name,
        description=None,
        type=type,
        players=players if players is not None else [],
        owner_id=owner_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ----- Reads -----


class TestGroupRepositoryReads:
    @pytest.mark.asyncio
    async def test_get_returns_entity(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id, name="A")
        entity = await repository.get(row.id)
        assert entity is not None
        assert entity.name == "A"
        assert entity.owner_id == admin_user.id

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self, repository):
        assert await repository.get(99999) is None

    @pytest.mark.asyncio
    async def test_find_by_owner_and_name(self, repository, db, admin_user, test_user):
        _seed_group(db, admin_user.id, name="shared")
        _seed_group(db, test_user.id, name="shared")

        mine = await repository.find_by_owner_and_name(test_user.id, "shared")
        assert mine is not None
        assert mine.owner_id == test_user.id

        miss = await repository.find_by_owner_and_name(admin_user.id, "ghost")
        assert miss is None

    @pytest.mark.asyncio
    async def test_list_filters_by_type(self, repository, db, admin_user):
        _seed_group(db, admin_user.id, name="o", type=GroupType.op)
        _seed_group(db, admin_user.id, name="w", type=GroupType.whitelist)

        op_page = await repository.list(GroupListSpec(type=GroupType.op))
        assert [e.name for e in op_page.entities] == ["o"]
        assert op_page.total == 1

        all_page = await repository.list(GroupListSpec())
        assert {e.name for e in all_page.entities} == {"o", "w"}
        assert all_page.total == 2

    @pytest.mark.asyncio
    async def test_list_paginates_with_offset_limit(self, repository, db, admin_user):
        for i in range(5):
            _seed_group(db, admin_user.id, name=f"g{i}", type=GroupType.op)

        page1 = await repository.list(GroupListSpec(page=1, size=2))
        assert len(page1.entities) == 2
        assert page1.total == 5
        assert page1.page == 1
        assert page1.size == 2

        page3 = await repository.list(GroupListSpec(page=3, size=2))
        assert len(page3.entities) == 1
        assert page3.total == 5


# ----- Writes -----


class TestGroupRepositoryWrites:
    @pytest.mark.asyncio
    async def test_add_returns_entity_with_id(self, repository, db, admin_user):
        entity = await repository.add(
            CreateGroupCommand(
                name="created",
                type=GroupType.op,
                owner_id=admin_user.id,
                description="d",
            )
        )
        db.commit()
        assert entity.id is not None
        assert entity.name == "created"
        assert entity.players == []

        persisted = db.query(Group).filter(Group.id == entity.id).first()
        assert persisted is not None

    @pytest.mark.asyncio
    async def test_update_applies_only_set_fields(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id, name="old")
        # Set a description so we can verify only `name` changed
        row.description = "original"
        db.commit()

        updated = await repository.update(row.id, UpdateGroupCommand(name="new"))
        db.commit()
        assert updated is not None
        assert updated.name == "new"
        assert updated.description == "original"

    @pytest.mark.asyncio
    async def test_update_unknown_returns_none(self, repository):
        assert await repository.update(99999, UpdateGroupCommand(name="x")) is None

    @pytest.mark.asyncio
    async def test_delete_returns_true_then_false(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id, name="to-del")
        ok = await repository.delete(row.id)
        db.commit()
        assert ok is True
        assert db.query(Group).filter(Group.id == row.id).first() is None
        assert await repository.delete(99999) is False


# ----- Player operations -----


class TestGroupRepositoryPlayers:
    @pytest.mark.asyncio
    async def test_add_player_persists_to_json(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id)
        entity = await repository.add_player(row.id, "uuid-1", "alice")
        db.commit()
        # Round-trip through ORM
        db.refresh(row)
        players = row.get_players()
        assert len(players) == 1
        assert players[0]["uuid"] == "uuid-1"
        assert players[0]["username"] == "alice"
        # Entity returned with same data
        assert len(entity.players) == 1

    @pytest.mark.asyncio
    async def test_add_player_upserts_on_duplicate_uuid(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id)
        await repository.add_player(row.id, "uuid-1", "alice")
        db.commit()
        entity = await repository.add_player(row.id, "uuid-1", "alice-renamed")
        db.commit()
        assert len(entity.players) == 1
        assert entity.players[0]["username"] == "alice-renamed"

    @pytest.mark.asyncio
    async def test_add_player_unknown_group_raises(self, repository):
        with pytest.raises(GroupNotFoundError):
            await repository.add_player(99999, "u", "n")

    @pytest.mark.asyncio
    async def test_remove_player_removes_from_json(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id)
        await repository.add_player(row.id, "u1", "n1")
        await repository.add_player(row.id, "u2", "n2")
        db.commit()
        entity = await repository.remove_player(row.id, "u1")
        db.commit()
        assert [p["uuid"] for p in entity.players] == ["u2"]

    @pytest.mark.asyncio
    async def test_remove_player_unknown_player_raises(self, repository, db, admin_user):
        row = _seed_group(db, admin_user.id)
        await repository.add_player(row.id, "u1", "n1")
        db.commit()
        with pytest.raises(PlayerNotFoundInGroup):
            await repository.remove_player(row.id, "ghost")

    @pytest.mark.asyncio
    async def test_remove_player_unknown_group_raises(self, repository):
        with pytest.raises(GroupNotFoundError):
            await repository.remove_player(99999, "u")
