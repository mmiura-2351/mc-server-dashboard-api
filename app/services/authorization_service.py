from functools import wraps

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.servers.models import Backup, Server
from app.users.models import Role, User


class AuthorizationService:
    """Service for handling authorization and access control"""

    @staticmethod
    def check_server_access(server_id: int, user: User, db: Session) -> Server:
        """Check if user has access to the server"""
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Server not found"
            )

        if user.role != Role.admin and server.owner_id != user.id:
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

        # Check if user has access to the server that owns this backup
        AuthorizationService.check_server_access(backup.server_id, user, db)
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
        """Check if user can create servers"""
        return user.role in [Role.admin, Role.operator]

    @staticmethod
    def can_modify_files(user: User) -> bool:
        """Check if user can modify server files"""
        return user.role in [Role.admin, Role.operator]

    @staticmethod
    def can_restore_backup(user: User) -> bool:
        """Check if user can restore backups"""
        return user.role in [Role.admin, Role.operator]

    @staticmethod
    def can_create_template(user: User) -> bool:
        """Check if user can create templates"""
        return user.role in [Role.admin, Role.operator]

    @staticmethod
    def can_schedule_backups(user: User) -> bool:
        """Check if user can manage scheduled backups"""
        return user.role == Role.admin

    @staticmethod
    def filter_servers_for_user(user: User, servers) -> list:
        """Filter servers list based on user permissions"""
        if user.role == Role.admin:
            return servers
        else:
            return [server for server in servers if server.owner_id == user.id]


authorization_service = AuthorizationService()
