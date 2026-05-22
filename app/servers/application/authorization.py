"""Authorization service — framework-agnostic application-layer policy.

Originally relocated from ``app.services.authorization_service`` under
#228 (PR 2b). Refactored under #273 + #292 to:

- Remove every FastAPI import (``HTTPException``, ``Request``,
  ``status``) so the application layer no longer leaks framework
  concerns through its public signatures. Resource-resolution failures
  now raise plain Python domain exceptions
  (``ServerNotFoundError``, ``BackupNotFoundError``,
  ``BackupParentServerMissingError``); a global FastAPI exception
  handler registered in ``app.core.error_handlers`` maps them back to
  the HTTP responses the API contract requires.
- Drop the inline ``AuditService.log_permission_check`` calls. Audit
  logging is a router-side concern (it needs the ``Request`` object)
  and the two production callsites — both in
  ``app.servers.routers.control`` — re-emit the success event after the
  access check returns.
- Delete the ``require_role`` / ``require_admin_or_operator``
  decorators (#292). They were preserved only for legacy tests that
  were retired in #290; production code never bound them.

Method semantics:

- ``check_server_access`` / ``check_backup_access`` remain ``async``
  and resolve aggregates through sibling Repository Ports
  (``ServerRepository``, ``BackupRepository``). They return the domain
  entities (``ServerEntity`` / ``BackupEntity``); routers that still
  need the SQLAlchemy ``Server`` row (notably the start/restart paths,
  which hand the object to ``minecraft_server_manager.start_server``
  for mutation by ``simplified_sync_service``) refetch the ORM row
  separately as a transitional pattern until #149 finishes.
- ``AuthorizationService`` is instance-based: the constructor receives
  the three sibling Repositories so callers wire it via FastAPI
  ``Depends(get_authorization_service)`` rather than calling a
  module-level singleton.
- Boolean helpers (``is_admin``, ``can_*``) remain ``@staticmethod``
  because they read only fields of ``User`` and do not touch the
  database.
- ``can_delete_backup`` is two-argument again (``backup``, ``user``).
  The transitional three-argument form added in #228 PR 2b
  (``server=None``) was removed under #274 once ``BackupEntity``
  started carrying a denormalised ``server_owner_id`` populated by
  the repository's ``joinedload(Backup.server)``. Legacy ORM
  ``Backup`` rows still work because the static helper falls back to
  ``backup.server.owner_id`` when the input is not a ``BackupEntity``.

The legacy module path ``app.services.authorization_service`` continues
to re-export ``AuthorizationService`` for tests that have not yet been
relocated; the module-level ``authorization_service`` singleton was
removed under #228 because every router now goes through DI.
"""

from app.backups.domain.entities import BackupEntity
from app.backups.domain.exceptions import (
    BackupNotFoundError,
    BackupParentServerMissingError,
)
from app.backups.domain.ports import BackupRepository
from app.backups.models import Backup
from app.servers.domain.entities import ServerEntity
from app.servers.domain.exceptions import ServerNotFoundError
from app.servers.domain.ports import ServerRepository
from app.servers.models import Server
from app.templates.domain.ports import TemplateRepository
from app.users.domain.value_objects import Role
from app.users.models import User


class AuthorizationService:
    """Centralised authorization checks.

    Resource-access methods are ``async`` and resolve aggregates via
    Repository Ports. Boolean role helpers stay synchronous because
    they do not touch the database.
    """

    def __init__(
        self,
        server_repo: ServerRepository,
        backup_repo: BackupRepository,
        template_repo: TemplateRepository,
    ) -> None:
        self._server_repo = server_repo
        self._backup_repo = backup_repo
        # ``template_repo`` is injected for parity with the sibling-domain
        # wiring (#228) so a future ``check_template_access`` can land
        # without re-touching every router; it is unused today.
        self._template_repo = template_repo

    # ----- Async resource-access checks -----

    async def check_server_access(
        self,
        server_id: int,
        user: User,
    ) -> ServerEntity:
        """Verify ``user`` may access the server identified by ``server_id``.

        Returns the ``ServerEntity`` on success. Raises
        ``ServerNotFoundError`` (mapped to HTTP 404 by the global
        exception handler) when the server is missing. All
        authenticated users may access every server today (Phase 1
        policy from the legacy implementation).

        ``include_deleted=True`` matches the legacy ``db.query(Server)``
        which returned soft-deleted rows — the backup-restore paths
        rely on that behaviour.

        Audit logging is intentionally **not** performed here. Callers
        that need to emit a ``permission_check`` audit event must do
        so after this method returns (the only two such callsites live
        in ``app.servers.routers.control``).
        """
        server = await self._server_repo.get(server_id, include_deleted=True)
        if server is None:
            raise ServerNotFoundError("Server not found")

        # Phase 1: every authenticated user may access every server.
        return server

    async def check_backup_access(
        self,
        backup_id: int,
        user: User,
    ) -> BackupEntity:
        """Verify ``user`` may access the backup identified by ``backup_id``.

        Returns the ``BackupEntity`` on success. Mirrors the legacy
        behaviour: ``BackupNotFoundError`` on missing backup,
        ``BackupParentServerMissingError`` on missing parent server,
        otherwise allowed (Phase 1).
        """
        backup = await self._backup_repo.get(backup_id)
        if backup is None:
            raise BackupNotFoundError("Backup not found")

        server = await self._server_repo.get(backup.server_id, include_deleted=True)
        if server is None:
            raise BackupParentServerMissingError("Server not found for backup")

        return backup

    # ----- Sync boolean helpers (no DB access) -----

    @staticmethod
    def can_create_server(user: User) -> bool:
        """Phase 1: every authenticated user may create servers."""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_modify_files(user: User) -> bool:
        """Phase 1: every authenticated user may edit server files."""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_create_backup(user: User) -> bool:
        """Phase 1: every authenticated user may create backups."""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_restore_backup(user: User) -> bool:
        """Phase 1: every authenticated user may restore backups."""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_create_group(user: User) -> bool:
        """Phase 1: every authenticated user may create groups."""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_create_template(user: User) -> bool:
        """Phase 1: every authenticated user may create templates."""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_schedule_backups(user: User) -> bool:
        """Only admins may schedule backups."""
        return user.role == Role.admin

    @staticmethod
    def is_admin(user: User) -> bool:
        return user.role == Role.admin

    @staticmethod
    def is_operator_or_admin(user: User) -> bool:
        return user.role in [Role.admin, Role.operator]

    @staticmethod
    def can_delete_server(server, user: User) -> bool:
        """Admin or server owner may delete the server.

        ``server`` is typed loosely because production routers pass a
        ``ServerEntity`` (post-#228) and the legacy tests still pass an
        ORM ``Server``; both expose ``owner_id`` so the check is safe.
        """
        if isinstance(server, (Server, ServerEntity)):
            return user.role == Role.admin or server.owner_id == user.id
        # Defensive: accept anything with an ``owner_id`` attribute, as
        # several tests pass a ``Mock(spec=Server)``.
        return user.role == Role.admin or getattr(server, "owner_id", None) == user.id

    @staticmethod
    def can_delete_backup(backup, user: User) -> bool:
        """Admin or owner of the backup's parent server may delete the backup.

        Accepts either a domain ``BackupEntity`` (reads the
        ``server_owner_id`` field denormalised by the repository under
        #274) or a legacy ORM ``Backup`` (reaches through the
        ``backup.server`` relationship; preserved for tests that pre-date
        #228).
        """
        if user.role == Role.admin:
            return True
        if isinstance(backup, BackupEntity):
            return backup.server_owner_id == user.id
        # Legacy ORM path: ``backup.server`` is a relationship.
        if isinstance(backup, Backup):
            return backup.server.owner_id == user.id
        # Defensive: anything else with a usable attribute.
        owner_id = getattr(backup, "server_owner_id", None)
        if owner_id is None:
            server = getattr(backup, "server", None)
            owner_id = getattr(server, "owner_id", None) if server is not None else None
        return owner_id == user.id

    @staticmethod
    def filter_servers_for_user(user: User, servers, db=None) -> list:
        """Return ``servers`` unchanged — every user sees every server today.

        ``db`` kept for parity with the legacy signature; some tests pass
        ``None`` and expect a ``ValueError`` to flag the misuse, others
        pass a session.
        """
        if user is None:
            raise AttributeError("'NoneType' object has no attribute 'role'")
        if db is None:
            raise ValueError(
                "Database session is required for security filtering - cannot be None"
            )
        return servers
