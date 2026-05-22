"""Integration tests for `SqlAlchemyVisibilityRepository` + UoW.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The repository methods stage
changes only; the UoW (or an explicit `db.commit()`) finalises.
"""

import pytest

from app.core.visibility.adapters.repository import SqlAlchemyVisibilityRepository
from app.core.visibility.adapters.uow import SqlAlchemyVisibilityUnitOfWork
from app.core.visibility.domain.entities import (
    GrantAccessCommand,
    SetVisibilityCommand,
)
from app.core.visibility.domain.exceptions import (
    DuplicateGrantError,
    InvalidVisibilityTypeError,
    VisibilityNotFoundError,
)
from app.core.visibility.models import (
    ResourceType,
    ResourceUserAccess,
    ResourceVisibility,
    VisibilityType,
)
from app.groups.models import Group, GroupType
from app.servers.models import Server, ServerType


@pytest.fixture
def repository(db) -> SqlAlchemyVisibilityRepository:
    return SqlAlchemyVisibilityRepository(db)


def _seed_server(db, owner_id: int, *, name: str = "srv", port: int = 25565) -> Server:
    row = Server(
        name=name,
        description=None,
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=port,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
        directory_path=f"/servers/{name}",
        is_deleted=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_group(db, owner_id: int, *, name: str = "g") -> Group:
    row = Group(
        name=name,
        description=None,
        type=GroupType.op,
        players=[],
        owner_id=owner_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Reads / writes
# ---------------------------------------------------------------------------


class TestVisibilityCrud:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_missing(self, repository):
        assert await repository.get(ResourceType.SERVER, 1) is None

    @pytest.mark.asyncio
    async def test_set_then_get_round_trip(self, repository, db):
        entity = await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.PUBLIC,
            )
        )
        db.commit()
        assert entity.visibility_type == VisibilityType.PUBLIC
        again = await repository.get(ResourceType.SERVER, 1)
        assert again is not None
        assert again.id == entity.id

    @pytest.mark.asyncio
    async def test_set_updates_in_place(self, repository, db):
        first = await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.PRIVATE,
            )
        )
        db.commit()
        second = await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.PUBLIC,
            )
        )
        db.commit()
        assert first.id == second.id
        # exactly one row in the DB.
        rows = db.query(ResourceVisibility).all()
        assert len(rows) == 1
        assert rows[0].visibility_type == VisibilityType.PUBLIC


class TestGrantRevoke:
    @pytest.mark.asyncio
    async def test_grant_then_revoke(self, repository, db, admin_user):
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.SPECIFIC_USERS,
            )
        )
        db.commit()
        await repository.grant_access(
            GrantAccessCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                user_id=admin_user.id,
                granted_by_user_id=admin_user.id,
            )
        )
        db.commit()
        assert db.query(ResourceUserAccess).count() == 1
        revoked = await repository.revoke_access(ResourceType.SERVER, 1, admin_user.id)
        db.commit()
        assert revoked is True
        assert db.query(ResourceUserAccess).count() == 0

    @pytest.mark.asyncio
    async def test_grant_rejects_non_specific_users(self, repository, db, admin_user):
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.PUBLIC,
            )
        )
        db.commit()
        with pytest.raises(InvalidVisibilityTypeError):
            await repository.grant_access(
                GrantAccessCommand(
                    resource_type=ResourceType.SERVER,
                    resource_id=1,
                    user_id=admin_user.id,
                    granted_by_user_id=admin_user.id,
                )
            )

    @pytest.mark.asyncio
    async def test_grant_raises_when_visibility_missing(self, repository, admin_user):
        with pytest.raises(VisibilityNotFoundError):
            await repository.grant_access(
                GrantAccessCommand(
                    resource_type=ResourceType.SERVER,
                    resource_id=999,
                    user_id=admin_user.id,
                    granted_by_user_id=admin_user.id,
                )
            )

    @pytest.mark.asyncio
    async def test_grant_rejects_duplicate(self, repository, db, admin_user):
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.SPECIFIC_USERS,
            )
        )
        db.commit()
        await repository.grant_access(
            GrantAccessCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                user_id=admin_user.id,
                granted_by_user_id=admin_user.id,
            )
        )
        db.commit()
        with pytest.raises(DuplicateGrantError):
            await repository.grant_access(
                GrantAccessCommand(
                    resource_type=ResourceType.SERVER,
                    resource_id=1,
                    user_id=admin_user.id,
                    granted_by_user_id=admin_user.id,
                )
            )

    @pytest.mark.asyncio
    async def test_set_clears_grants_when_leaving_specific_users(
        self, repository, db, admin_user
    ):
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.SPECIFIC_USERS,
            )
        )
        db.commit()
        await repository.grant_access(
            GrantAccessCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                user_id=admin_user.id,
                granted_by_user_id=admin_user.id,
            )
        )
        db.commit()
        assert db.query(ResourceUserAccess).count() == 1
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.PRIVATE,
            )
        )
        db.commit()
        assert db.query(ResourceUserAccess).count() == 0


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------


class TestMigrationHelpers:
    @pytest.mark.asyncio
    async def test_list_missing_server_and_group_ids(self, repository, db, admin_user):
        s1 = _seed_server(db, admin_user.id, name="s1", port=25566)
        s2 = _seed_server(db, admin_user.id, name="s2", port=25567)
        g1 = _seed_group(db, admin_user.id, name="g1")
        # `s1` already has a visibility row.
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=s1.id,
                visibility_type=VisibilityType.PUBLIC,
            )
        )
        db.commit()
        assert await repository.list_missing_server_ids() == [s2.id]
        assert await repository.list_missing_group_ids() == [g1.id]

    @pytest.mark.asyncio
    async def test_add_many_public_inserts_rows(self, repository, db, admin_user):
        s1 = _seed_server(db, admin_user.id, name="s1", port=25566)
        s2 = _seed_server(db, admin_user.id, name="s2", port=25567)
        added = await repository.add_many_public(ResourceType.SERVER, [s1.id, s2.id])
        db.commit()
        assert added == 2
        rows = db.query(ResourceVisibility).all()
        assert {r.resource_id for r in rows} == {s1.id, s2.id}
        assert all(r.visibility_type == VisibilityType.PUBLIC for r in rows)

    @pytest.mark.asyncio
    async def test_count_resources_and_visibility(self, repository, db, admin_user):
        _seed_server(db, admin_user.id, name="s1", port=25566)
        _seed_server(db, admin_user.id, name="s2", port=25567)
        assert await repository.count_resources(ResourceType.SERVER) == 2
        assert await repository.count_visibility(ResourceType.SERVER) == 0

    @pytest.mark.asyncio
    async def test_count_by_visibility_type_groups_correctly(self, repository, db):
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=1,
                visibility_type=VisibilityType.PUBLIC,
            )
        )
        await repository.set(
            SetVisibilityCommand(
                resource_type=ResourceType.SERVER,
                resource_id=2,
                visibility_type=VisibilityType.PRIVATE,
            )
        )
        db.commit()
        distribution = await repository.count_by_visibility_type()
        assert distribution[ResourceType.SERVER][VisibilityType.PUBLIC] == 1
        assert distribution[ResourceType.SERVER][VisibilityType.PRIVATE] == 1


# ---------------------------------------------------------------------------
# UoW behaviour
# ---------------------------------------------------------------------------


class TestUnitOfWork:
    @pytest.mark.asyncio
    async def test_commit_persists_changes(self, db):
        async with SqlAlchemyVisibilityUnitOfWork(db=db) as uow:
            await uow.visibility.set(
                SetVisibilityCommand(
                    resource_type=ResourceType.SERVER,
                    resource_id=1,
                    visibility_type=VisibilityType.PUBLIC,
                )
            )
            await uow.commit()
        assert db.query(ResourceVisibility).count() == 1

    @pytest.mark.asyncio
    async def test_pending_writes_without_commit_roll_back(self, db, caplog):
        # Build the UoW with its own session so the rollback path closes
        # the connection cleanly; the legacy `db` fixture is read here
        # only to verify the table stays empty.
        async with SqlAlchemyVisibilityUnitOfWork.from_session_factory(lambda: db) as uow:
            await uow.visibility.set(
                SetVisibilityCommand(
                    resource_type=ResourceType.SERVER,
                    resource_id=1,
                    visibility_type=VisibilityType.PUBLIC,
                )
            )
            # no commit
        assert db.query(ResourceVisibility).count() == 0
