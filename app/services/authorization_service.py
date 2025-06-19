from functools import wraps
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.visibility import ResourceType
from app.servers.models import Backup, Server
from app.services.visibility_service import VisibilityService
from app.users.models import Role, User


class AuthorizationService:
    """Service for handling authorization and access control"""

    @staticmethod
    def check_server_access(
        server_id: int,
        user: User,
        db: Session,
        request: Optional[Request] = None,
        log_access: bool = True,
    ) -> Server:
        """Check if user has access to the server"""
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            if log_access and request:
                from app.audit.service import AuditService

                AuditService.log_permission_check(
                    db=db,
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

        # Phase 2: Visibility-based access control using the new visibility system
        visibility_service = VisibilityService(db)
        has_access = visibility_service.check_resource_access(
            user=user,
            resource_type=ResourceType.SERVER,
            resource_id=server_id,
            resource_owner_id=server.owner_id,
        )

        if log_access and request:
            from app.audit.service import AuditService

            AuditService.log_permission_check(
                db=db,
                request=request,
                resource_type="server",
                resource_id=server_id,
                permission="access",
                granted=has_access,
                user_id=user.id,
                details={
                    "server_name": server.name,
                    "owner_id": server.owner_id,
                    "user_role": user.role.value,
                },
            )

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this server",
            )

        return server

    @staticmethod
    def check_backup_access(backup_id: int, user: User, db: Session) -> Backup:
        """Check if user has access to the backup"""
        backup = db.query(Backup).filter(Backup.id == backup_id).first()
        if not backup:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found"
            )

        # Check if user has access to the server that owns this backup using visibility system
        visibility_service = VisibilityService(db)
        server = db.query(Server).filter(Server.id == backup.server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found for backup",
            )

        has_access = visibility_service.check_resource_access(
            user=user,
            resource_type=ResourceType.SERVER,
            resource_id=backup.server_id,
            resource_owner_id=server.owner_id,
        )

        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this backup",
            )

        return backup

    @staticmethod
    def require_role(required_role: Role):
        """Decorator to require specific role for endpoint access"""

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Find the current_user parameter
                current_user = kwargs.get("current_user")
                if not current_user:
                    # Try to find it in args if not in kwargs
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
        """Decorator to require admin or operator role"""

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Find the current_user parameter
                current_user = kwargs.get("current_user")
                if not current_user:
                    # Try to find it in args if not in kwargs
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
    def can_create_server(user: User) -> bool:
        """Check if user can create servers - Phase 1: All users can create servers"""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_modify_files(user: User) -> bool:
        """Check if user can modify server files - Phase 1: All users can edit files"""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_create_backup(user: User) -> bool:
        """Check if user can create backups - Phase 1: All users can create backups"""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_restore_backup(user: User) -> bool:
        """Check if user can restore backups - Phase 1: All users can restore backups"""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_create_group(user: User) -> bool:
        """Check if user can create groups - Phase 1: All users can create groups"""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_create_template(user: User) -> bool:
        """Check if user can create templates - Phase 1: All users can create templates"""
        return user.role in [Role.admin, Role.operator, Role.user]

    @staticmethod
    def can_schedule_backups(user: User) -> bool:
        """Check if user can manage scheduled backups"""
        return user.role == Role.admin

    @staticmethod
    def filter_servers_for_user(user: User, servers, db: Session = None) -> list:
        """Filter servers list based on user permissions using visibility system"""
        # Maintain validation to prevent None user for backward compatibility
        if user is None:
            raise AttributeError("'NoneType' object has no attribute 'role'")

        # If no database session provided, fall back to returning all servers for compatibility
        if db is None:
            return servers

        # Phase 2: Use visibility-based filtering
        visibility_service = VisibilityService(db)

        # Convert servers to (id, owner_id) tuples for visibility filtering
        resource_tuples = [(server.id, server.owner_id) for server in servers]

        # Get accessible server IDs
        accessible_ids = visibility_service.filter_resources_by_visibility(
            user=user, resources=resource_tuples, resource_type=ResourceType.SERVER
        )

        # Filter servers to only include accessible ones
        accessible_servers = [server for server in servers if server.id in accessible_ids]

        return accessible_servers

    @staticmethod
    def is_admin(user: User) -> bool:
        """Check if user is an admin"""
        return user.role == Role.admin

    @staticmethod
    def is_operator_or_admin(user: User) -> bool:
        """Check if user is an operator or admin"""
        return user.role in [Role.admin, Role.operator]


authorization_service = AuthorizationService()
