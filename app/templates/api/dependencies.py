"""FastAPI dependency wiring for the templates domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.domain.ports import ServerReadPort
from app.templates.adapters.uow import SqlAlchemyTemplatesUnitOfWork
from app.templates.application.service import TemplateService
from app.templates.domain.ports import TemplatesUnitOfWork


def get_templates_uow(db: Session = Depends(get_db)) -> TemplatesUnitOfWork:
    """Return a `TemplatesUnitOfWork` bound to the current request's session."""
    return SqlAlchemyTemplatesUnitOfWork(db=db)


def get_server_read_port(db: Session = Depends(get_db)) -> ServerReadPort:
    """Return the minimal cross-domain `ServerReadPort` (TBD #154-8)."""
    return SqlAlchemyServerReadPort(db)


def get_template_service(
    uow: TemplatesUnitOfWork = Depends(get_templates_uow),
    server_read: ServerReadPort = Depends(get_server_read_port),
) -> TemplateService:
    """Return a per-request `TemplateService` with its Ports wired."""
    return TemplateService(uow=uow, server_read=server_read)
