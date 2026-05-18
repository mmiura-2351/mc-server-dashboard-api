"""Integration tests for `SqlAlchemyUserRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database. The adapter does not commit on its own (the UoW owns
transactions in production), so each write-path test calls `db.commit()`
after staging changes.
"""

import pytest

from app.users.adapters.repository import SqlAlchemyUserRepository
from app.users.domain.entities import CreateUserCommand, UpdateUserCommand
from app.users.models import Role, User


@pytest.fixture
def repository(db):
    return SqlAlchemyUserRepository(db)


@pytest.fixture
def existing_user(db):
    user = User(
        username="existing",
        email="existing@example.com",
        hashed_password="hashed",
        role=Role.user,
        is_active=True,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ----- Reads -----


@pytest.mark.asyncio
async def test_get_by_id(repository, existing_user):
    found = await repository.get_by_id(existing_user.id)
    assert found is not None
    assert found.username == "existing"


@pytest.mark.asyncio
async def test_get_by_id_missing(repository):
    assert await repository.get_by_id(9999) is None


@pytest.mark.asyncio
async def test_get_by_username(repository, existing_user):
    found = await repository.get_by_username("existing")
    assert found is not None
    assert found.email == "existing@example.com"


@pytest.mark.asyncio
async def test_get_by_email(repository, existing_user):
    found = await repository.get_by_email("existing@example.com")
    assert found is not None
    assert found.username == "existing"


@pytest.mark.asyncio
async def test_email_exists_for_other_user(repository, existing_user):
    assert (
        await repository.email_exists_for_other_user(
            "existing@example.com", exclude_user_id=existing_user.id + 1
        )
        is True
    )
    assert (
        await repository.email_exists_for_other_user(
            "existing@example.com", exclude_user_id=existing_user.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_count_and_count_by_role(repository, existing_user, db):
    db.add(
        User(
            username="admin1",
            email="admin@example.com",
            hashed_password="h",
            role=Role.admin,
            is_active=True,
            is_approved=True,
        )
    )
    db.commit()
    assert await repository.count() == 2
    assert await repository.count_by_role(Role.admin) == 1
    assert await repository.count_by_role(Role.user) == 1


# ----- Writes -----


@pytest.mark.asyncio
async def test_create(repository, db):
    created = await repository.create(
        CreateUserCommand(
            username="new",
            email="new@example.com",
            hashed_password="h",
            role=Role.user,
            is_approved=False,
        )
    )
    db.commit()
    assert created.id is not None
    assert created.is_approved is False
    again = await repository.get_by_username("new")
    assert again is not None


@pytest.mark.asyncio
async def test_update_sparse(repository, existing_user, db):
    updated = await repository.update(
        existing_user.id,
        UpdateUserCommand(email="new-email@example.com", is_approved=False),
    )
    db.commit()
    assert updated is not None
    assert updated.email == "new-email@example.com"
    assert updated.is_approved is False
    # Untouched fields preserved
    assert updated.username == "existing"


@pytest.mark.asyncio
async def test_update_missing_returns_none(repository):
    assert (
        await repository.update(9999, UpdateUserCommand(email="x@example.com")) is None
    )


@pytest.mark.asyncio
async def test_delete(repository, existing_user, db):
    deleted = await repository.delete(existing_user.id)
    db.commit()
    assert deleted is True
    assert await repository.get_by_id(existing_user.id) is None


@pytest.mark.asyncio
async def test_delete_missing(repository):
    assert await repository.delete(9999) is False
