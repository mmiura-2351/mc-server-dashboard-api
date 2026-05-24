"""Coverage for `app.servers.application.authorization.AuthorizationService`.

PR #290 (#228 PR 3) removed the legacy
`tests/unit/services/test_authorization_service*.py` files (they were
``pytest.mark.skip``-only and contributed 0% coverage). This module
re-pins the public surface of the post-#273/#292 application service
through the existing fake Repositories so the error branches and the
``@staticmethod`` boolean helpers regain coverage.

Tests are fake-based and deterministic; no production code is touched.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from app.backups.domain.exceptions import (
    BackupNotFoundError,
    BackupParentServerMissingError,
)
from app.backups.models import Backup, BackupStatus, BackupType
from app.servers.application.authorization import AuthorizationService
from app.servers.domain.exceptions import ServerNotFoundError
from app.servers.models import Server, ServerStatus, ServerType
from app.users.domain.value_objects import Role
from tests.unit.backups.fakes import FakeBackupRepository, make_backup_entity
from tests.unit.servers.fakes import FakeServerRepository, make_server_entity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(user_id: int = 1, role: Role = Role.user) -> Any:
    """Duck-typed `User` — the service only reads `.id` and `.role`."""
    return SimpleNamespace(id=user_id, role=role)


def _make_service(
    server_repo: FakeServerRepository | None = None,
    backup_repo: FakeBackupRepository | None = None,
) -> AuthorizationService:
    return AuthorizationService(
        server_repo=server_repo or FakeServerRepository(),
        backup_repo=backup_repo or FakeBackupRepository(),
    )


# ---------------------------------------------------------------------------
# check_server_access
# ---------------------------------------------------------------------------


class TestCheckServerAccess:
    @pytest.mark.asyncio
    async def test_returns_entity_when_present(self):
        repo = FakeServerRepository()
        entity = repo.seed(make_server_entity(id=10, owner_id=7))
        svc = _make_service(server_repo=repo)
        result = await svc.check_server_access(10, _user(user_id=99, role=Role.user))
        assert result.id == entity.id

    @pytest.mark.asyncio
    async def test_includes_soft_deleted_rows(self):
        """`include_deleted=True` is the documented behaviour (legacy parity).

        The backup-restore path depends on soft-deleted servers staying
        resolvable through this helper.
        """
        repo = FakeServerRepository()
        repo.seed(make_server_entity(id=11, owner_id=1, is_deleted=True))
        svc = _make_service(server_repo=repo)
        result = await svc.check_server_access(11, _user(role=Role.admin))
        assert result.id == 11
        assert result.is_deleted is True

    @pytest.mark.asyncio
    async def test_raises_server_not_found_when_missing(self):
        svc = _make_service()
        with pytest.raises(ServerNotFoundError):
            await svc.check_server_access(404, _user())


# ---------------------------------------------------------------------------
# check_backup_access
# ---------------------------------------------------------------------------


class TestCheckBackupAccess:
    @pytest.mark.asyncio
    async def test_returns_entity_when_backup_and_server_present(self):
        server_repo = FakeServerRepository()
        server_repo.seed(make_server_entity(id=5, owner_id=2))
        backup_repo = FakeBackupRepository()
        # `FakeBackupRepository.add` allocates ids, but we need a
        # specific id; insert directly.
        entity = make_backup_entity(id=77, server_id=5, server_owner_id=2)
        backup_repo._records[77] = entity  # noqa: SLF001 (test-only seed)
        backup_repo._next_id = 78  # noqa: SLF001
        svc = _make_service(server_repo=server_repo, backup_repo=backup_repo)
        result = await svc.check_backup_access(77, _user(user_id=2))
        assert result.id == 77

    @pytest.mark.asyncio
    async def test_raises_backup_not_found(self):
        svc = _make_service()
        with pytest.raises(BackupNotFoundError):
            await svc.check_backup_access(999, _user())

    @pytest.mark.asyncio
    async def test_raises_parent_server_missing(self):
        """Backup row resolves but the server fk is dangling."""
        backup_repo = FakeBackupRepository()
        backup_repo._records[1] = make_backup_entity(  # noqa: SLF001
            id=1, server_id=42
        )
        backup_repo._next_id = 2  # noqa: SLF001
        # ``server_repo`` is empty, so the parent lookup returns None.
        svc = _make_service(backup_repo=backup_repo)
        with pytest.raises(BackupParentServerMissingError):
            await svc.check_backup_access(1, _user())


# ---------------------------------------------------------------------------
# Sync boolean helpers — every role lane must be pinned.
# ---------------------------------------------------------------------------


class TestPhase1BooleanHelpers:
    """Phase 1 helpers all allow every authenticated role.

    A parametrized table would obscure that the helpers diverge from
    ``can_schedule_backups`` (admin-only) and ``is_admin`` /
    ``is_operator_or_admin``; the helpers are listed explicitly so the
    intent is readable.
    """

    @pytest.mark.parametrize("role", [Role.admin, Role.operator, Role.user])
    def test_phase1_helpers_allow_every_role(self, role: Role):
        u = _user(role=role)
        assert AuthorizationService.can_create_server(u)
        assert AuthorizationService.can_modify_files(u)
        assert AuthorizationService.can_create_backup(u)
        assert AuthorizationService.can_restore_backup(u)
        assert AuthorizationService.can_create_group(u)


class TestRestrictedRoleHelpers:
    def test_can_schedule_backups_admin_only(self):
        assert AuthorizationService.can_schedule_backups(_user(role=Role.admin))
        assert not AuthorizationService.can_schedule_backups(_user(role=Role.operator))
        assert not AuthorizationService.can_schedule_backups(_user(role=Role.user))

    def test_is_admin(self):
        assert AuthorizationService.is_admin(_user(role=Role.admin))
        assert not AuthorizationService.is_admin(_user(role=Role.operator))
        assert not AuthorizationService.is_admin(_user(role=Role.user))

    def test_is_operator_or_admin(self):
        assert AuthorizationService.is_operator_or_admin(_user(role=Role.admin))
        assert AuthorizationService.is_operator_or_admin(_user(role=Role.operator))
        assert not AuthorizationService.is_operator_or_admin(_user(role=Role.user))


# ---------------------------------------------------------------------------
# can_delete_server — exercises every type-dispatch branch.
# ---------------------------------------------------------------------------


class TestCanDeleteServer:
    def test_admin_can_delete_any_server_entity(self):
        entity = make_server_entity(id=1, owner_id=42)
        admin = _user(user_id=1, role=Role.admin)
        assert AuthorizationService.can_delete_server(entity, admin)

    def test_owner_can_delete_own_server_entity(self):
        entity = make_server_entity(id=1, owner_id=7)
        owner = _user(user_id=7, role=Role.user)
        assert AuthorizationService.can_delete_server(entity, owner)

    def test_non_owner_non_admin_cannot_delete_server_entity(self):
        entity = make_server_entity(id=1, owner_id=7)
        stranger = _user(user_id=8, role=Role.user)
        assert not AuthorizationService.can_delete_server(entity, stranger)

    def test_works_with_orm_server_via_mock_spec(self):
        """Legacy code paths pass `Mock(spec=Server)` — the helper
        treats ``Server`` instances the same as ``ServerEntity``."""
        orm = Mock(spec=Server)
        orm.owner_id = 5
        # `isinstance(orm, Server)` is True because of `spec=Server`.
        assert AuthorizationService.can_delete_server(
            orm, _user(user_id=5, role=Role.user)
        )
        assert not AuthorizationService.can_delete_server(
            orm, _user(user_id=6, role=Role.user)
        )

    def test_defensive_path_accepts_owner_id_attribute(self):
        """Falls back to ``getattr(server, 'owner_id', None)`` for
        anything that is neither a `Server` nor a `ServerEntity`."""
        bag = SimpleNamespace(owner_id=11)
        assert AuthorizationService.can_delete_server(
            bag, _user(user_id=11, role=Role.user)
        )
        assert not AuthorizationService.can_delete_server(
            bag, _user(user_id=12, role=Role.user)
        )
        # Admin override works on the defensive path too.
        assert AuthorizationService.can_delete_server(
            bag, _user(user_id=999, role=Role.admin)
        )


# ---------------------------------------------------------------------------
# can_delete_backup — same matrix on the backup side.
# ---------------------------------------------------------------------------


class TestCanDeleteBackup:
    def test_admin_can_delete_any_backup(self):
        backup = make_backup_entity(id=1, server_id=1, server_owner_id=99)
        admin = _user(user_id=1, role=Role.admin)
        assert AuthorizationService.can_delete_backup(backup, admin)

    def test_owner_can_delete_via_server_owner_id_denormalized(self):
        """Post-#274 ``BackupEntity`` carries ``server_owner_id``."""
        backup = make_backup_entity(id=1, server_id=1, server_owner_id=7)
        owner = _user(user_id=7, role=Role.user)
        assert AuthorizationService.can_delete_backup(backup, owner)

    def test_non_owner_cannot_delete_backup_entity(self):
        backup = make_backup_entity(id=1, server_id=1, server_owner_id=7)
        stranger = _user(user_id=8, role=Role.user)
        assert not AuthorizationService.can_delete_backup(backup, stranger)

    def test_legacy_orm_backup_reaches_through_relationship(self):
        """Mock(spec=Backup).server.owner_id is the legacy path."""
        orm = Mock(spec=Backup)
        # The helper does `backup.server.owner_id`, so set up the
        # nested attr explicitly.
        orm.server = SimpleNamespace(owner_id=4)
        assert AuthorizationService.can_delete_backup(
            orm, _user(user_id=4, role=Role.user)
        )
        assert not AuthorizationService.can_delete_backup(
            orm, _user(user_id=5, role=Role.user)
        )

    def test_defensive_path_uses_server_owner_id_attribute(self):
        """For arbitrary objects, prefer denormalised ``server_owner_id``."""
        bag = SimpleNamespace(server_owner_id=12)
        assert AuthorizationService.can_delete_backup(
            bag, _user(user_id=12, role=Role.user)
        )
        assert not AuthorizationService.can_delete_backup(
            bag, _user(user_id=13, role=Role.user)
        )

    def test_defensive_path_falls_back_to_server_relationship(self):
        """When ``server_owner_id`` is None, reach through ``.server``."""
        bag = SimpleNamespace(server_owner_id=None, server=SimpleNamespace(owner_id=21))
        assert AuthorizationService.can_delete_backup(
            bag, _user(user_id=21, role=Role.user)
        )
        assert not AuthorizationService.can_delete_backup(
            bag, _user(user_id=22, role=Role.user)
        )

    def test_defensive_path_handles_missing_server(self):
        """No ``server_owner_id`` and no ``.server`` -> permission denied."""
        bag = SimpleNamespace()
        assert not AuthorizationService.can_delete_backup(
            bag, _user(user_id=1, role=Role.user)
        )


# ---------------------------------------------------------------------------
# filter_servers_for_user — the legacy misuse contract.
# ---------------------------------------------------------------------------


class TestFilterServersForUser:
    def test_returns_servers_unchanged_when_db_provided(self):
        """Phase 1: no filtering. ``db`` may be any truthy object."""
        servers = [object(), object()]
        result = AuthorizationService.filter_servers_for_user(
            _user(), servers, db=object()
        )
        assert result is servers

    def test_none_user_raises_attribute_error(self):
        with pytest.raises(AttributeError):
            AuthorizationService.filter_servers_for_user(None, [], db=object())

    def test_none_db_raises_value_error(self):
        """Mirrors the legacy contract: callers must pass a DB session."""
        with pytest.raises(ValueError):
            AuthorizationService.filter_servers_for_user(_user(), [], db=None)


# ---------------------------------------------------------------------------
# Defensive: ensure the FakeBackupRepository seeded backups round-trip
# the ``server_owner_id`` field correctly. Catches accidental drift in
# the fixture helper that would otherwise mask real coverage gaps.
# ---------------------------------------------------------------------------


def test_make_backup_entity_round_trips_server_owner_id():
    backup = make_backup_entity(
        id=1,
        server_id=2,
        status=BackupStatus.completed,
        backup_type=BackupType.manual,
        server_owner_id=5,
    )
    assert backup.server_owner_id == 5


def test_make_server_entity_round_trips_owner_id_and_status():
    srv = make_server_entity(
        id=1,
        owner_id=3,
        status=ServerStatus.running,
        server_type=ServerType.paper,
    )
    assert srv.owner_id == 3
    assert srv.status == ServerStatus.running
