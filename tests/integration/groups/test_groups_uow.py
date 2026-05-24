"""Integration tests for `SqlAlchemyGroupsUnitOfWork` semantics.

Covers commit-persists, re-entry semantics, forgot-to-commit warning, and
the "either db or session_factory" constructor contract.
"""

import pytest

from app.groups.adapters.uow import SqlAlchemyGroupsUnitOfWork
from app.groups.domain.entities import CreateGroupCommand
from app.groups.models import Group, GroupType


@pytest.mark.asyncio
async def test_commit_persists_changes(db, admin_user):
    uow = SqlAlchemyGroupsUnitOfWork(db=db)
    async with uow as bound:
        entity = await bound.groups.add(
            CreateGroupCommand(
                name="uow-commit",
                type=GroupType.op,
                owner_id=admin_user.id,
            )
        )
        await bound.commit()

    row = db.query(Group).filter(Group.id == entity.id).first()
    assert row is not None
    assert row.name == "uow-commit"


@pytest.mark.asyncio
async def test_re_entry_uses_same_session(db, admin_user):
    """Same UoW instance can be entered twice in `db=session` mode."""
    uow = SqlAlchemyGroupsUnitOfWork(db=db)
    async with uow as bound1:
        entity = await bound1.groups.add(
            CreateGroupCommand(
                name="reentry",
                type=GroupType.op,
                owner_id=admin_user.id,
            )
        )
        await bound1.commit()

    async with uow as bound2:
        got = await bound2.groups.get(entity.id)
        assert got is not None


@pytest.mark.asyncio
async def test_forgot_to_commit_warns_when_session_dirty(db, admin_user, caplog):
    """Pending session-level changes without a commit must emit a
    warning. Stage a Group through `db.add` (no flush) so
    `_has_pending_writes` sees it in `db.new`."""
    uow = SqlAlchemyGroupsUnitOfWork(db=db)
    with caplog.at_level("WARNING"):
        async with uow as _bound:
            db.add(
                Group(
                    name=f"dirty-{admin_user.id}",
                    type=GroupType.op,
                    players=[],
                    owner_id=admin_user.id,
                )
            )
            # Intentionally no flush, no commit

    assert any("exited with pending writes" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_requires_db_or_session_factory():
    with pytest.raises(ValueError, match="Either db or session_factory"):
        SqlAlchemyGroupsUnitOfWork()


@pytest.mark.asyncio
async def test_server_groups_repository_is_bound_on_enter(db, admin_user):
    """Both `groups` and `server_groups` must be bound after __aenter__."""
    uow = SqlAlchemyGroupsUnitOfWork(db=db)
    async with uow as bound:
        assert bound.groups is not None
        assert bound.server_groups is not None
