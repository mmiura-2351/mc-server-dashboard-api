"""FastAPI dependency wiring for the auth domain.

Only file in `app/auth/api/` allowed to import from `adapters/`. Wires
the SQLAlchemy adapters to the abstract Ports defined in
`app.auth.domain.ports`.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.adapters.uow import SqlAlchemyAuthUnitOfWork
from app.auth.application.brute_force_service import BruteForceService
from app.auth.application.service import AuthService
from app.auth.domain.ports import AuthUnitOfWork
from app.core.database import get_db


def get_auth_unit_of_work(db: Session = Depends(get_db)) -> AuthUnitOfWork:
    """Return an `AuthUnitOfWork` bound to the current request's session."""
    return SqlAlchemyAuthUnitOfWork(db=db)


def get_auth_service(
    uow: AuthUnitOfWork = Depends(get_auth_unit_of_work),
) -> AuthService:
    """Return an `AuthService` wired with the UoW."""
    return AuthService(uow=uow)


def get_brute_force_service(db: Session = Depends(get_db)) -> BruteForceService:
    """Return a `BruteForceService` bound to the request session."""
    return BruteForceService(db=db)
