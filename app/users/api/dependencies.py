"""FastAPI dependency wiring for the users domain.

This is the only file in `app/users/api/` allowed to import from
`adapters/`. It binds the SQLAlchemy adapters to the abstract Ports.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.users.adapters.read_port import SqlAlchemyUserReadPort
from app.users.adapters.uow import SqlAlchemyUsersUnitOfWork
from app.users.application.service import UserService
from app.users.domain.ports import UserReadPort, UsersUnitOfWork


def get_users_unit_of_work(db: Session = Depends(get_db)) -> UsersUnitOfWork:
    """Return a `UsersUnitOfWork` bound to the current request's session."""
    return SqlAlchemyUsersUnitOfWork(db=db)


def get_user_service(
    uow: UsersUnitOfWork = Depends(get_users_unit_of_work),
) -> UserService:
    """Return a `UserService` wired with the UoW."""
    return UserService(uow=uow)


def get_user_read_port(db: Session = Depends(get_db)) -> UserReadPort:
    """Return a read-only `UserReadPort` for other domains to depend on."""
    return SqlAlchemyUserReadPort(db=db)
