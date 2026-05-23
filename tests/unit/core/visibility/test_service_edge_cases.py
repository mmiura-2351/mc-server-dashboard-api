"""Coverage gap-filler for `VisibilityService`.

`test_service_with_fake.py` already pins the access-check / mutation /
filter happy paths. This module focuses on the branches the existing
suite left uncovered after #271/#287 deletion:

- `_check_visibility_access`: unknown visibility type fallthrough
- `_check_role_based_access`: empty `role_restriction` (grant-all)
- `get_resource_visibility_info`: present / absent + SPECIFIC_USERS
  payload-shape lane
- `migrate_existing_resources_to_public`: idempotent + zero-noise
  lanes
- `_validate_role_configuration`: every illegal combination
  enumerated by the implementation

All tests are fake-based and deterministic; no production code is
modified.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.visibility.application.service import VisibilityService
from app.core.visibility.models import ResourceType, VisibilityType
from app.users.domain.value_objects import Role
from tests.unit.core.visibility.fakes import (
    FakeVisibilityRepository,
    FakeVisibilityUnitOfWork,
)


def _user(user_id: int = 1, role: Role = Role.user) -> Any:
    return SimpleNamespace(id=user_id, role=role)


def _make_service(repo: FakeVisibilityRepository | None = None):
    uow = FakeVisibilityUnitOfWork(repository=repo)
    return VisibilityService(uow=uow), uow


# ---------------------------------------------------------------------------
# `_check_visibility_access` fallthrough — unknown visibility type
# ---------------------------------------------------------------------------


class TestCheckVisibilityAccessFallthrough:
    @pytest.mark.asyncio
    async def test_unknown_visibility_type_denies_access(self):
        """Defensive branch: an entity stored with an unrecognised
        `visibility_type` must not silently grant access."""
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PUBLIC
        )
        # Bypass the public API to mutate visibility_type into a
        # non-enum sentinel that exercises the fallthrough.
        stored = await repo.get(ResourceType.SERVER, 1)
        assert stored is not None
        repo._rows[(ResourceType.SERVER, 1)] = replace(  # noqa: SLF001
            stored,
            visibility_type="UNKNOWN_LANE",  # type: ignore[arg-type]
        )

        granted = await service.check_resource_access(
            _user(user_id=2, role=Role.user), ResourceType.SERVER, 1
        )
        assert granted is False


# ---------------------------------------------------------------------------
# `_check_role_based_access` — empty role_restriction grants everyone.
# ---------------------------------------------------------------------------


class TestRoleBasedFallback:
    @pytest.mark.asyncio
    async def test_role_based_without_restriction_allows_all_roles(self):
        """ROLE_BASED with role_restriction=None logs a warning and
        defaults to grant-all (legacy contract)."""
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        # `set_resource_visibility` permits ROLE_BASED+None and emits a
        # warning; access checks below should accept every role.
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.ROLE_BASED, role_restriction=None
        )
        for role in (Role.user, Role.operator, Role.admin):
            assert await service.check_resource_access(
                _user(user_id=2, role=role), ResourceType.SERVER, 1
            )


# ---------------------------------------------------------------------------
# `get_resource_visibility_info`
# ---------------------------------------------------------------------------


class TestGetResourceVisibilityInfo:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self):
        service, _ = _make_service()
        assert await service.get_resource_visibility_info(ResourceType.SERVER, 1) is None

    @pytest.mark.asyncio
    async def test_returns_shape_for_role_based_visibility(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER,
            1,
            VisibilityType.ROLE_BASED,
            role_restriction=Role.operator,
        )
        info = await service.get_resource_visibility_info(ResourceType.SERVER, 1)
        assert info is not None
        assert info["visibility_type"] == VisibilityType.ROLE_BASED.value
        assert info["role_restriction"] == Role.operator.value
        assert "created_at" in info
        assert "updated_at" in info
        # ROLE_BASED entries must NOT carry a `granted_users` payload.
        assert "granted_users" not in info

    @pytest.mark.asyncio
    async def test_includes_granted_users_for_specific_users_type(self):
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.SPECIFIC_USERS
        )
        await service.grant_user_access(
            ResourceType.SERVER, 1, user_id=42, granted_by_user_id=7
        )
        info = await service.get_resource_visibility_info(ResourceType.SERVER, 1)
        assert info is not None
        assert info["visibility_type"] == VisibilityType.SPECIFIC_USERS.value
        # `role_restriction` is null for non-ROLE_BASED entries.
        assert info["role_restriction"] is None
        assert info["granted_users"] == [
            {
                "user_id": 42,
                "granted_by_user_id": 7,
                "granted_at": info["granted_users"][0]["granted_at"],
            }
        ]


# ---------------------------------------------------------------------------
# `migrate_existing_resources_to_public`
# ---------------------------------------------------------------------------


class TestMigrateExistingResourcesToPublic:
    @pytest.mark.asyncio
    async def test_migrates_missing_resources_only(self):
        repo = FakeVisibilityRepository()
        service, uow = _make_service(repo)
        # Resource 2 already has a visibility row; should NOT be touched.
        await service.set_resource_visibility(
            ResourceType.SERVER, 2, VisibilityType.PRIVATE
        )
        commit_before = uow.commit_count
        migrated = await service.migrate_existing_resources_to_public(
            ResourceType.SERVER, [1, 2, 3]
        )
        assert migrated == 2
        # The migration emits a single commit when there is work to do.
        assert uow.commit_count == commit_before + 1
        # Resource 2's visibility was preserved (not overwritten).
        existing = await repo.get(ResourceType.SERVER, 2)
        assert existing is not None
        assert existing.visibility_type == VisibilityType.PRIVATE

    @pytest.mark.asyncio
    async def test_returns_zero_and_skips_commit_when_nothing_to_migrate(self):
        repo = FakeVisibilityRepository()
        service, uow = _make_service(repo)
        # Every resource already configured.
        await service.set_resource_visibility(
            ResourceType.SERVER, 1, VisibilityType.PUBLIC
        )
        commit_before = uow.commit_count
        migrated = await service.migrate_existing_resources_to_public(
            ResourceType.SERVER, [1]
        )
        assert migrated == 0
        # No-op migration must not emit a commit.
        assert uow.commit_count == commit_before

    @pytest.mark.asyncio
    async def test_empty_input_returns_zero(self):
        service, uow = _make_service()
        commit_before = uow.commit_count
        assert (
            await service.migrate_existing_resources_to_public(ResourceType.SERVER, [])
            == 0
        )
        assert uow.commit_count == commit_before


# ---------------------------------------------------------------------------
# `_validate_role_configuration` — every illegal combination.
# ---------------------------------------------------------------------------


class TestValidateRoleConfiguration:
    @pytest.mark.asyncio
    async def test_role_based_with_invalid_role_raises(self):
        service, _ = _make_service()

        # Pass a hashable duck-typed value that is NOT in the
        # `role_hierarchy` dict — exercises the explicit validation
        # path. (Real production never reaches this branch because
        # FastAPI rejects the request at parse-time, but the legacy
        # `ValueError` contract is asserted here for parity.)
        class _BogusRole:
            value = "ghost"

            def __hash__(self) -> int:  # pragma: no cover (delegated)
                return id(self)

        bogus = _BogusRole()
        with pytest.raises(ValueError, match="Invalid role restriction"):
            await service.set_resource_visibility(
                ResourceType.SERVER,
                1,
                VisibilityType.ROLE_BASED,
                role_restriction=bogus,  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_role_based_with_valid_role_succeeds(self):
        """Positive control: every real `Role` is accepted for ROLE_BASED."""
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        for role in (Role.user, Role.operator, Role.admin):
            entity = await service.set_resource_visibility(
                ResourceType.SERVER,
                role.value.__hash__(),  # unique resource id per loop
                VisibilityType.ROLE_BASED,
                role_restriction=role,
            )
            assert entity.role_restriction == role

    @pytest.mark.asyncio
    async def test_private_rejects_role_restriction(self):
        service, _ = _make_service()
        with pytest.raises(
            ValueError, match="PRIVATE visibility cannot have role restrictions"
        ):
            await service.set_resource_visibility(
                ResourceType.SERVER,
                1,
                VisibilityType.PRIVATE,
                role_restriction=Role.operator,
            )

    @pytest.mark.asyncio
    async def test_public_rejects_role_restriction(self):
        service, _ = _make_service()
        with pytest.raises(
            ValueError, match="PUBLIC visibility cannot have role restrictions"
        ):
            await service.set_resource_visibility(
                ResourceType.SERVER,
                1,
                VisibilityType.PUBLIC,
                role_restriction=Role.admin,
            )

    @pytest.mark.asyncio
    async def test_specific_users_rejects_role_restriction(self):
        service, _ = _make_service()
        with pytest.raises(
            ValueError,
            match="SPECIFIC_USERS visibility cannot have role restrictions",
        ):
            await service.set_resource_visibility(
                ResourceType.SERVER,
                1,
                VisibilityType.SPECIFIC_USERS,
                role_restriction=Role.user,
            )

    @pytest.mark.asyncio
    async def test_defensive_unknown_visibility_type_with_role_restriction(self):
        """The final ``raise ValueError`` after the four explicit lanes
        is unreachable in production (every `VisibilityType` enum value
        has an explicit branch). Pin it anyway by passing a sentinel
        that exposes the same `.value` duck-typing the message uses."""
        service, _ = _make_service()

        class _UnknownVisibility:
            value = "unknown"

        with pytest.raises(
            ValueError,
            match="role_restriction can only be used with ROLE_BASED visibility",
        ):
            await service.set_resource_visibility(
                ResourceType.SERVER,
                1,
                _UnknownVisibility(),  # type: ignore[arg-type]
                role_restriction=Role.user,
            )

    @pytest.mark.asyncio
    async def test_no_role_restriction_passes_for_non_role_based(self):
        """Sanity: every non-ROLE_BASED type without restriction is OK."""
        repo = FakeVisibilityRepository()
        service, _ = _make_service(repo)
        for i, vtype in enumerate(
            (
                VisibilityType.PUBLIC,
                VisibilityType.PRIVATE,
                VisibilityType.SPECIFIC_USERS,
            ),
            start=1,
        ):
            entity = await service.set_resource_visibility(
                ResourceType.SERVER, i, vtype, role_restriction=None
            )
            assert entity.visibility_type == vtype
