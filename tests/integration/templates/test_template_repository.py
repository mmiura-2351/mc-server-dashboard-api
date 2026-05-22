"""Integration tests for `SqlAlchemyTemplateRepository` and the
`SqlAlchemyTemplatesUnitOfWork`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not** commit
on its own (the UoW owns transactions in production), so write-path
tests call `db.commit()` explicitly after staging changes.
"""

from typing import Any, Dict, Optional

import pytest

from app.servers.models import Server, ServerStatus, ServerType
from app.templates.adapters.repository import SqlAlchemyTemplateRepository
from app.templates.adapters.uow import SqlAlchemyTemplatesUnitOfWork
from app.templates.domain.entities import (
    CreateTemplateCommand,
    TemplateListSpec,
    UpdateTemplateCommand,
)
from app.templates.models import Template
from app.users.models import User


@pytest.fixture
def repository(db) -> SqlAlchemyTemplateRepository:
    return SqlAlchemyTemplateRepository(db)


def _seed_template(
    db,
    creator: User,
    *,
    name: str = "tpl",
    is_public: bool = False,
    server_type: ServerType = ServerType.vanilla,
    minecraft_version: str = "1.20.1",
    configuration: Optional[Dict[str, Any]] = None,
) -> Template:
    row = Template(
        name=name,
        description=None,
        minecraft_version=minecraft_version,
        server_type=server_type,
        configuration=configuration if configuration is not None else {"k": "v"},
        default_groups={"op_groups": [], "whitelist_groups": []},
        created_by=creator.id,
        is_public=is_public,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ----- get / find -----


class TestTemplateRepositoryReads:
    @pytest.mark.asyncio
    async def test_get_returns_entity_with_creator_name(self, repository, db, admin_user):
        row = _seed_template(db, admin_user, name="A")
        entity = await repository.get(row.id)
        assert entity is not None
        assert entity.name == "A"
        assert entity.creator_name == admin_user.username

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown(self, repository):
        assert await repository.get(99999) is None

    @pytest.mark.asyncio
    async def test_find_by_creator_and_name(self, repository, db, admin_user, test_user):
        _seed_template(db, admin_user, name="shared")
        _seed_template(db, test_user, name="shared")  # same name, diff creator

        my_match = await repository.find_by_creator_and_name(test_user.id, "shared")
        assert my_match is not None
        assert my_match.created_by == test_user.id

        no_match = await repository.find_by_creator_and_name(admin_user.id, "ghost")
        assert no_match is None


# ----- list_paged -----


class TestTemplateRepositoryListing:
    @pytest.mark.asyncio
    async def test_list_paged_non_admin_filters_to_visible(
        self, repository, db, admin_user, test_user
    ):
        _seed_template(db, admin_user, name="admin-private", is_public=False)
        _seed_template(db, admin_user, name="admin-public", is_public=True)
        _seed_template(db, test_user, name="user-private", is_public=False)

        spec = TemplateListSpec(viewer_id=test_user.id, viewer_is_admin=False)
        page = await repository.list_paged(spec)
        names = {e.name for e in page.entities}
        # test_user sees own private + admin's public
        assert names == {"admin-public", "user-private"}
        assert page.total == 2

    @pytest.mark.asyncio
    async def test_list_paged_admin_sees_all(self, repository, db, admin_user, test_user):
        _seed_template(db, admin_user, name="a", is_public=False)
        _seed_template(db, test_user, name="b", is_public=False)
        spec = TemplateListSpec(viewer_id=admin_user.id, viewer_is_admin=True)
        page = await repository.list_paged(spec)
        assert page.total == 2

    @pytest.mark.asyncio
    async def test_list_paged_filters_by_minecraft_version(
        self, repository, db, admin_user
    ):
        _seed_template(db, admin_user, name="a", minecraft_version="1.20.1")
        _seed_template(db, admin_user, name="b", minecraft_version="1.21.0")

        spec = TemplateListSpec(
            viewer_id=admin_user.id,
            viewer_is_admin=True,
            minecraft_version="1.21.0",
        )
        page = await repository.list_paged(spec)
        assert [e.name for e in page.entities] == ["b"]

    @pytest.mark.asyncio
    async def test_list_paged_filters_by_server_type(self, repository, db, admin_user):
        _seed_template(db, admin_user, name="v", server_type=ServerType.vanilla)
        _seed_template(db, admin_user, name="p", server_type=ServerType.paper)

        spec = TemplateListSpec(
            viewer_id=admin_user.id,
            viewer_is_admin=True,
            server_type=ServerType.paper,
        )
        page = await repository.list_paged(spec)
        assert [e.name for e in page.entities] == ["p"]

    @pytest.mark.asyncio
    async def test_list_paged_filters_by_is_public(self, repository, db, admin_user):
        _seed_template(db, admin_user, name="pub", is_public=True)
        _seed_template(db, admin_user, name="priv", is_public=False)

        spec = TemplateListSpec(
            viewer_id=admin_user.id, viewer_is_admin=True, is_public=True
        )
        page = await repository.list_paged(spec)
        assert [e.name for e in page.entities] == ["pub"]

    @pytest.mark.asyncio
    async def test_list_paged_pagination(self, repository, db, admin_user):
        for i in range(5):
            _seed_template(db, admin_user, name=f"t{i}")

        spec = TemplateListSpec(
            viewer_id=admin_user.id, viewer_is_admin=True, page=1, size=2
        )
        page1 = await repository.list_paged(spec)
        assert page1.total == 5
        assert len(page1.entities) == 2

        spec = TemplateListSpec(
            viewer_id=admin_user.id, viewer_is_admin=True, page=3, size=2
        )
        page3 = await repository.list_paged(spec)
        assert page3.total == 5
        assert len(page3.entities) == 1


# ----- counts -----


class TestTemplateRepositoryCounts:
    @pytest.mark.asyncio
    async def test_count_visible(self, repository, db, admin_user, test_user):
        _seed_template(db, admin_user, name="a", is_public=False)
        _seed_template(db, admin_user, name="b", is_public=True)
        _seed_template(db, test_user, name="c", is_public=False)

        assert await repository.count_visible(test_user.id, False) == 2
        assert await repository.count_visible(admin_user.id, True) == 3

    @pytest.mark.asyncio
    async def test_count_visible_public(self, repository, db, admin_user, test_user):
        _seed_template(db, admin_user, name="a", is_public=False)
        _seed_template(db, admin_user, name="b", is_public=True)

        assert await repository.count_visible_public(test_user.id, False) == 1

    @pytest.mark.asyncio
    async def test_count_owned_by(self, repository, db, admin_user, test_user):
        _seed_template(db, admin_user, name="a")
        _seed_template(db, admin_user, name="b")
        _seed_template(db, test_user, name="c")

        assert await repository.count_owned_by(admin_user.id) == 2
        assert await repository.count_owned_by(test_user.id) == 1

    @pytest.mark.asyncio
    async def test_count_visible_by_server_type(self, repository, db, admin_user):
        _seed_template(db, admin_user, name="v", server_type=ServerType.vanilla)
        _seed_template(db, admin_user, name="p", server_type=ServerType.paper)
        _seed_template(db, admin_user, name="p2", server_type=ServerType.paper)

        stats = await repository.count_visible_by_server_type(admin_user.id, True)
        # Every ServerType is initialised to 0 by the adapter
        assert stats[ServerType.vanilla] == 1
        assert stats[ServerType.paper] == 2
        assert stats[ServerType.forge] == 0


class TestTemplateRepositoryDependentServers:
    @pytest.mark.asyncio
    async def test_count_active_dependent_servers(self, repository, db, admin_user):
        tpl = _seed_template(db, admin_user, name="dep-tpl")

        # Active server using the template
        s_active = Server(
            name="A",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/dep-a",
            owner_id=admin_user.id,
            template_id=tpl.id,
        )
        # Soft-deleted server using the template (should be ignored)
        s_deleted = Server(
            name="B",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            directory_path="./servers/dep-b",
            owner_id=admin_user.id,
            template_id=tpl.id,
            is_deleted=True,
        )
        db.add_all([s_active, s_deleted])
        db.commit()

        assert await repository.count_active_dependent_servers(tpl.id) == 1


# ----- writes -----


class TestTemplateRepositoryWrites:
    @pytest.mark.asyncio
    async def test_add_returns_entity_with_id_and_creator_name(
        self, repository, db, admin_user
    ):
        command = CreateTemplateCommand(
            name="created",
            description="d",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            configuration={"k": "v"},
            default_groups={"op_groups": [1], "whitelist_groups": []},
            is_public=True,
            created_by=admin_user.id,
        )
        entity = await repository.add(command)
        db.commit()
        assert entity.id is not None
        assert entity.creator_name == admin_user.username
        assert entity.is_public is True
        assert entity.configuration == {"k": "v"}
        assert entity.default_groups == {"op_groups": [1], "whitelist_groups": []}

        persisted = db.query(Template).filter(Template.id == entity.id).first()
        assert persisted is not None
        assert persisted.name == "created"

    @pytest.mark.asyncio
    async def test_update_applies_only_set_fields(self, repository, db, admin_user):
        row = _seed_template(db, admin_user, name="old", is_public=False)
        original_desc = row.description

        command = UpdateTemplateCommand(name="new", is_public=True)
        updated = await repository.update(row.id, command)
        db.commit()
        assert updated is not None
        assert updated.name == "new"
        assert updated.is_public is True
        # description was not set in the command — should still be the
        # original value
        assert updated.description == original_desc

    @pytest.mark.asyncio
    async def test_update_returns_none_for_unknown(self, repository):
        assert await repository.update(99999, UpdateTemplateCommand(name="x")) is None

    @pytest.mark.asyncio
    async def test_delete_returns_true_then_false(self, repository, db, admin_user):
        row = _seed_template(db, admin_user, name="to-del")
        ok = await repository.delete(row.id)
        db.commit()
        assert ok is True
        assert db.query(Template).filter(Template.id == row.id).first() is None

        assert await repository.delete(99999) is False


# ----- UoW semantics -----


class TestSqlAlchemyTemplatesUnitOfWork:
    @pytest.mark.asyncio
    async def test_commit_persists_changes(self, db, admin_user):
        uow = SqlAlchemyTemplatesUnitOfWork(db=db)
        async with uow as bound:
            entity = await bound.templates.add(
                CreateTemplateCommand(
                    name="uow-commit",
                    minecraft_version="1.20.1",
                    server_type=ServerType.vanilla,
                    configuration={},
                    default_groups={"op_groups": [], "whitelist_groups": []},
                    is_public=False,
                    created_by=admin_user.id,
                )
            )
            await bound.commit()

        row = db.query(Template).filter(Template.id == entity.id).first()
        assert row is not None
        assert row.name == "uow-commit"

    @pytest.mark.asyncio
    async def test_re_entry_uses_same_session(self, db, admin_user):
        """Same UoW instance can be entered twice in `db=session` mode."""
        uow = SqlAlchemyTemplatesUnitOfWork(db=db)
        async with uow as bound1:
            entity = await bound1.templates.add(
                CreateTemplateCommand(
                    name="reentry",
                    minecraft_version="1.20.1",
                    server_type=ServerType.vanilla,
                    configuration={},
                    default_groups={"op_groups": [], "whitelist_groups": []},
                    is_public=False,
                    created_by=admin_user.id,
                )
            )
            await bound1.commit()

        async with uow as bound2:
            got = await bound2.templates.get(entity.id)
            assert got is not None

    @pytest.mark.asyncio
    async def test_forgot_to_commit_warns_when_session_dirty(
        self, db, admin_user, caplog
    ):
        """Pending session-level changes without a commit must emit a
        warning. We stage a Template through `db.add` (no flush) so
        `_has_pending_writes` sees it in `db.new`.

        NOTE: `Repository.add` calls `db.flush()` to assign the id,
        which then moves the object out of `db.new`. This is the
        legacy contract — the warning catches the "callers who built
        up changes without flushing then forgot to commit" footgun.
        The `db=session` mode shares the transaction with the caller,
        so flushed-but-uncommitted rows roll back when the *caller's*
        transaction ends, not when this UoW exits.
        """
        uow = SqlAlchemyTemplatesUnitOfWork(db=db)
        with caplog.at_level("WARNING"):
            async with uow as _bound:
                # Stage a row without flushing
                db.add(
                    Template(
                        name=f"dirty-{admin_user.id}",
                        minecraft_version="1.20.1",
                        server_type=ServerType.vanilla,
                        configuration={},
                        default_groups={
                            "op_groups": [],
                            "whitelist_groups": [],
                        },
                        is_public=False,
                        created_by=admin_user.id,
                    )
                )
                # Intentionally no flush, no commit

        assert any("exited with pending writes" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_requires_db_or_session_factory(self):
        with pytest.raises(ValueError, match="Either db or session_factory"):
            SqlAlchemyTemplatesUnitOfWork()
