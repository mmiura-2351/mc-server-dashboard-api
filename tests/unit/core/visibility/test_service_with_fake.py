"""Unit tests for `VisibilityService` driven by `FakeVisibilityRepository`.

These exercise the application service's behaviour without spinning up
a database — the fakes guarantee that the same Protocol contract is
honoured both by `SqlAlchemyVisibilityRepository` (production) and the
in-memory fakes (unit tests).
"""

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.visibility.application.migration import VisibilityMigrationService
from app.core.visibility.application.service import VisibilityService
from app.core.visibility.domain.exceptions import (
    DuplicateGrantError,
    InvalidVisibilityTypeError,
    VisibilityNotFoundError,
)
from app.core.visibility.models import ResourceType, VisibilityType
from app.users.domain.value_objects import Role
from tests.unit.core.visibility.fakes import (
    FakeVisibilityRepository,
    FakeVisibilityUnitOfWork,
)


def _user(user_id: int = 1, role: Role = Role.user) -> Any:
    """Lightweight stand-in for `app.users.models.User`.

    The application service only reads `.id` and `.role`, so a duck-typed
    `SimpleNamespace` is sufficient and avoids dragging the ORM in.
    """
    return SimpleNamespace(id=user_id, role=role)


def _make_service(repo: FakeVisibilityRepository | None = None):
    uow = FakeVisibilityUnitOfWork(repository=repo)
    return VisibilityService(uow=uow), uow


# ---------------------------------------------------------------------------
# Access checks
# ---------------------------------------------------------------------------


class TestCheckResourceAccess:
    @pytest.mark.asyncio
    async def test_admin_always_has_access(self):
        service, _ = _make_service()
        user = _user(user_id=1, role=Role.admin)
        assert await service.check_resource_access(
            user, ResourceType.SERVER, 1, resource_owner_id=99
        )

    @pytest.mark.asyncio
    async def test_owner_always_has_access(self):
        service, _ = _make_service()
        user = _user(user_id=42, role=Role.user)
        assert await service.check_resource_access(
            user, ResourceType.SERVER, 1, resource_owner_id=42
        )

    @pytest.mark.asyncio
    async def test_no_visibility_row_denies_non_owner(self):
        service, _ = _make_service()
        user = _user(user_id=2, role=Role.user)
        assert not await service.check_resource_access(user, ResourceType.SERVER, 1)

    @pytest.mark.asyncio
    async def test_public_visibility_allows_everyone(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PUBLIC
        )
        user = _user(user_id=2, role=Role.user)
        assert await service.check_resource_access(user, ResourceType.SERVER, 1)

    @pytest.mark.asyncio
    async def test_private_visibility_denies_non_owner(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PRIVATE
        )
        user = _user(user_id=2, role=Role.user)
        assert not await service.check_resource_access(user, ResourceType.SERVER, 1)

    @pytest.mark.asyncio
    async def test_role_based_visibility_respects_hierarchy(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER,
            1,
            VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
        )
        # A plain `user` is below the operator threshold.
        assert not await service.check_resource_access(
            _user(user_id=2, role=Role.user), ResourceType.SERVER, 1
        )
        # An operator clears it.
        assert await service.check_resource_access(
            _user(user_id=2, role=Role.operator), ResourceType.SERVER, 1
        )

    @pytest.mark.asyncio
    async def test_specific_users_only_allows_granted(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.SPECIFIC_USERS
        )
        await service.grant_user_access(
            ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
        )
        assert await service.check_resource_access(
            _user(user_id=2, role=Role.user), ResourceType.SERVER, 1
        )
        assert not await service.check_resource_access(
            _user(user_id=3, role=Role.user), ResourceType.SERVER, 1
        )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_resources_by_visibility_only_returns_accessible():
    repo = FakeVisibilityRepository()
    service, _ = _make_service(repo)
    # 1 = public, 2 = private, 3 = owned by user 7
    await service.set_resource_visibility(ResourceType.SERVER, 1, VisibilityType.PUBLIC)
    await service.set_resource_visibility(ResourceType.SERVER, 2, VisibilityType.PRIVATE)
    await service.set_resource_visibility(ResourceType.SERVER, 3, VisibilityType.PRIVATE)
    user = _user(user_id=7, role=Role.user)
    accessible = await service.filter_resources_by_visibility(
        user,
        resources=[(1, 99), (2, 99), (3, 7)],
        resource_type=ResourceType.SERVER,
    )
    assert accessible == [1, 3]


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class TestSetVisibility:
    @pytest.mark.asyncio
    async def test_set_creates_then_updates_in_place(self):
        repo = FakeVisibilityRepository()
        service, uow = _make_service(repo)
        first = await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PRIVATE
        )
        second = await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PUBLIC
        )
        assert first.id == second.id
        assert second.visibility_type == VisibilityType.PUBLIC
        assert uow.commit_count == 2

    @pytest.mark.asyncio
    async def test_set_clears_grants_when_leaving_specific_users(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.SPECIFIC_USERS
        )
        await service.grant_user_access(
            ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
        )
        updated = await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PRIVATE
        )
        assert updated.granted_users == []

    @pytest.mark.asyncio
    async def test_role_restriction_only_valid_for_role_based(self):
        service, _ = _make_service()
        with pytest.raises(ValueError):
            await service.set_resource_visibility(
                ResourceType.SERVER,
                1,
                VisibilityType.PRIVATE,
                role_restriction=Role.operator,
            )


class TestGrantAccess:
    @pytest.mark.asyncio
    async def test_grant_requires_specific_users_visibility(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PUBLIC
        )
        with pytest.raises(InvalidVisibilityTypeError):
            await service.grant_user_access(
                ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
            )

    @pytest.mark.asyncio
    async def test_grant_raises_when_visibility_missing(self):
        service, _ = _make_service()
        with pytest.raises(VisibilityNotFoundError):
            await service.grant_user_access(
                ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
            )

    @pytest.mark.asyncio
    async def test_grant_rejects_duplicate(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.SPECIFIC_USERS
        )
        await service.grant_user_access(
            ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
        )
        with pytest.raises(DuplicateGrantError):
            await service.grant_user_access(
                ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
            )


class TestRevokeAccess:
    @pytest.mark.asyncio
    async def test_revoke_returns_false_when_missing(self):
        service, _ = _make_service()
        revoked = await service.revoke_user_access(ResourceType.SERVER, 1, user_id=2)
        assert revoked is False

    @pytest.mark.asyncio
    async def test_revoke_returns_true_when_present(self):
        repo = FakeVisibilityRepository()
        service, uow = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.SPECIFIC_USERS
        )
        await service.grant_user_access(
            ResourceType.SERVER, 1, user_id=2, granted_by_user_id=99
        )
        commit_before = uow.commit_count
        assert await service.revoke_user_access(ResourceType.SERVER, 1, user_id=2)
        assert uow.commit_count == commit_before + 1


# ---------------------------------------------------------------------------
# Migration service
# ---------------------------------------------------------------------------


class TestMigration:
    @pytest.mark.asyncio
    async def test_migrate_all_resources_creates_public_rows(self):
        repo = FakeVisibilityRepository(server_ids=[1, 2], group_ids=[10])
        migration = VisibilityMigrationService(
            uow=FakeVisibilityUnitOfWork(repository=repo)
        )
        counts = await migration.migrate_all_resources()
        assert counts == {"servers": 2, "groups": 1, "total": 3}
        assert (await repo.get(ResourceType.SERVER, 1)).visibility_type == (
            VisibilityType.PUBLIC
        )
        assert (await repo.get(ResourceType.GROUP, 10)).visibility_type == (
            VisibilityType.PUBLIC
        )

    @pytest.mark.asyncio
    async def test_migrate_idempotent_after_first_pass(self):
        repo = FakeVisibilityRepository(server_ids=[1], group_ids=[])
        migration = VisibilityMigrationService(
            uow=FakeVisibilityUnitOfWork(repository=repo)
        )
        first = await migration.migrate_all_resources()
        second = await migration.migrate_all_resources()
        assert first["total"] == 1
        assert second["total"] == 0

    @pytest.mark.asyncio
    async def test_verify_migration_completeness_reports_gaps(self):
        repo = FakeVisibilityRepository(server_ids=[1, 2], group_ids=[10])
        migration = VisibilityMigrationService(
            uow=FakeVisibilityUnitOfWork(repository=repo)
        )
        verification = await migration.verify_migration_completeness()
        assert verification["complete"] is False
        assert verification["stats"]["servers"]["missing"] == 2
        assert verification["stats"]["groups"]["missing"] == 1

    @pytest.mark.asyncio
    async def test_set_default_visibility_is_idempotent(self):
        repo = FakeVisibilityRepository()
        migration = VisibilityMigrationService(
            uow=FakeVisibilityUnitOfWork(repository=repo)
        )
        first = await migration.set_default_visibility_for_new_resource(
            ResourceType.SERVER, 1
        )
        second = await migration.set_default_visibility_for_new_resource(
            ResourceType.SERVER, 1
        )
        assert first.id == second.id
