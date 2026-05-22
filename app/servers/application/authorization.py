"""Authorization service — relocated from `app.services.authorization_service`.

Migrated under #228 (PR 2b/?):

- ``check_server_access`` / ``check_backup_access`` are now ``async def``
  and resolve resources through sibling Repository Ports
  (``ServerRepository``, ``BackupRepository``) instead of bare
  ``db.query`` calls. They return the domain entities
  (``ServerEntity`` / ``BackupEntity``); the routers that still need
  the SQLAlchemy ``Server`` row (notably the start/restart paths,
  which hand the object to ``minecraft_server_manager.start_server``
  for mutation by ``simplified_sync_service``) refetch the ORM row
  separately as a transitional pattern until #149 finishes.
- ``AuthorizationService`` is now instance-based: the constructor
  receives the three sibling Repositories so callers wire it via
  FastAPI ``Depends(get_authorization_service)`` rather than calling a
  module-level singleton.
- Boolean helpers (``is_admin``, ``can_*``) remain ``@staticmethod``
  because they read only fields of ``User`` and do not touch the
  database.
- ``can_delete_backup`` now accepts the parent ``ServerEntity`` (its
  one previous caller used to pass an ORM ``Backup`` and reach through
  ``backup.server.owner_id``; that path is no longer available off the
  domain entity, so the caller passes the server explicitly).

The legacy module path ``app.services.authorization_service`` continues
to re-export ``AuthorizationService`` for tests that have not yet been
relocated; the module-level ``authorization_service`` singleton has
been removed because every router now goes through DI.
"""

from functools import wraps
from typing import Optional

from fastapi import HTTPException, Request, status

from app.backups.domain.entities import BackupEntity
from app.backups.domain.ports import BackupRepository
from app.servers.domain.entities import ServerEntity
from app.servers.domain.ports import ServerRepository
from app.servers.models import Backup, Server
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
        request: Optional[Request] = None,
        log_access: bool = True,
    ) -> ServerEntity:
        """Verify ``user`` may access the server identified by ``server_id``.

        Returns the ``ServerEntity`` on success. Raises ``HTTPException``
        with status 404 if the server is missing. All authenticated users
        may access every server today (Phase 1 model from the legacy
        implementation); the audit-log event is preserved for parity.

        ``include_deleted=True`` matches the legacy ``db.query(Server)``
        which returned soft-deleted rows — the backup-restore paths rely
        on that behaviour.
        """
        server = await self._server_repo.get(server_id, include_deleted=True)
        if server is None:
            if log_access and request:
                from app.audit.service import AuditService

                AuditService.log_permission_check(
                    request=request,
                    resource_type="server",
                    resource_id=server_id,
                    permission="access",
                    granted=False,
                    user_id=user.id,
                    details={"reason": "server_not_found"},
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        # Phase 1: every authenticated user may access every server.
        if log_access and request:
            from app.audit.service import AuditService

            AuditService.log_permission_check(
                request=request,
                resource_type="server",
                resource_id=server_id,
                permission="access",
                granted=True,
                user_id=user.id,
                details={
                    "server_name": server.name,
                    "owner_id": server.owner_id,
                    "user_role": user.role.value,
                },
            )

        return server

    async def check_backup_access(
        self,
        backup_id: int,
        user: User,
        request: Optional[Request] = None,
    ) -> BackupEntity:
        """Verify ``user`` may access the backup identified by ``backup_id``.

        Returns the ``BackupEntity`` on success. Mirrors the legacy
        behaviour: 404 on missing backup, 404 on missing parent server,
        otherwise allowed (Phase 1).
        """
        backup = await self._backup_repo.get(backup_id)
        if backup is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found"
            )

        server = await self._server_repo.get(backup.server_id, include_deleted=True)
        if server is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found for backup",
            )

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
    def can_delete_backup(backup, user: User, server=None) -> bool:
        """Admin or owner of the backup's parent server may delete the backup.

        Accepts either a legacy ORM ``Backup`` (whose ``backup.server``
        relationship still resolves) or a domain ``BackupEntity`` plus
        the parent ``ServerEntity`` passed explicitly via ``server``.
        The two-argument legacy form is preserved for tests that pre-date
        #228.
        """
        if user.role == Role.admin:
            return True
        if server is not None:
            return getattr(server, "owner_id", None) == user.id
        # Legacy ORM path: ``backup.server`` is a relationship.
        if isinstance(backup, Backup):
            return backup.server.owner_id == user.id
        # Domain entity without explicit server — caller bug.
        raise ValueError(
            "can_delete_backup requires the parent server when called with a BackupEntity"
        )

    @staticmethod
    def require_role(required_role: Role):
        """Decorator preserved for parity with the legacy class.

        Production code does not use this decorator — the only callers
        are tests under ``tests/unit/services/test_authorization_service``.
        """

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                current_user = kwargs.get("current_user")
                if not current_user:
                    for arg in args:
                        if isinstance(arg, User):
                            current_user = arg
                            break
                if not current_user:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Current user not found in request",
                    )
                if current_user.role != required_role and current_user.role != Role.admin:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Requires {required_role.value} role or higher",
                    )
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    @staticmethod
    def require_admin_or_operator():
        """Decorator preserved for parity with the legacy class (test-only)."""

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                current_user = kwargs.get("current_user")
                if not current_user:
                    for arg in args:
                        if isinstance(arg, User):
                            current_user = arg
                            break
                if not current_user:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Current user not found in request",
                    )
                if current_user.role == Role.user:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only operators and admins can perform this action",
                    )
                return await func(*args, **kwargs)

            return wrapper

        return decorator

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
