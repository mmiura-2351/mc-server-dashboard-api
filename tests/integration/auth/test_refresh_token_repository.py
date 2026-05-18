"""Integration tests for `SqlAlchemyRefreshTokenRepository`."""

from datetime import datetime, timedelta, timezone

import pytest

from app.auth.adapters.repository import SqlAlchemyRefreshTokenRepository


@pytest.fixture
def repository(db):
    return SqlAlchemyRefreshTokenRepository(db)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


@pytest.mark.asyncio
async def test_create_and_get(repository, admin_user, db):
    created = await repository.create("tok-1", admin_user.id, _future())
    db.commit()
    assert created.id is not None
    assert created.is_revoked is False
    fetched = await repository.get_by_token("tok-1")
    assert fetched is not None
    assert fetched.user_id == admin_user.id


@pytest.mark.asyncio
async def test_get_missing(repository):
    assert await repository.get_by_token("no-such-token") is None


@pytest.mark.asyncio
async def test_revoke(repository, admin_user, db):
    await repository.create("tok-2", admin_user.id, _future())
    db.commit()

    ok = await repository.revoke("tok-2")
    db.commit()
    assert ok is True
    fetched = await repository.get_by_token("tok-2")
    assert fetched is not None and fetched.is_revoked is True


@pytest.mark.asyncio
async def test_revoke_missing(repository):
    assert await repository.revoke("no-such-token") is False


@pytest.mark.asyncio
async def test_revoke_active_for_user(repository, admin_user, db):
    await repository.create("a", admin_user.id, _future())
    await repository.create("b", admin_user.id, _future())
    db.commit()

    count = await repository.revoke_active_for_user(admin_user.id)
    db.commit()
    assert count == 2
    fetched_a = await repository.get_by_token("a")
    fetched_b = await repository.get_by_token("b")
    assert fetched_a is not None and fetched_a.is_revoked
    assert fetched_b is not None and fetched_b.is_revoked
