"""FastAPI dependency wiring for the files domain.

This is the only file in `api/` allowed to import from `adapters/`. It
binds the SQLAlchemy adapters to the abstract Ports the application
layer requires.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.files.adapters.uow import SqlAlchemyFilesUnitOfWork
from app.files.application.service import FileHistoryService
from app.files.domain.ports import FilesUnitOfWork
from app.servers.adapters.read_port import SqlAlchemyServerReadPort
from app.servers.domain.ports import ServerReadPort


def get_files_uow(db: Session = Depends(get_db)) -> FilesUnitOfWork:
    """Return a `FilesUnitOfWork` bound to the current request's session."""
    return SqlAlchemyFilesUnitOfWork(db=db)


def get_server_read_port(db: Session = Depends(get_db)) -> ServerReadPort:
    """Return the minimal cross-domain `ServerReadPort` (TBD #154-8)."""
    return SqlAlchemyServerReadPort(db)


def get_file_history_service(
    uow: FilesUnitOfWork = Depends(get_files_uow),
    server_read: ServerReadPort = Depends(get_server_read_port),
) -> FileHistoryService:
    """Return a per-request `FileHistoryService` with its Ports wired."""
    return FileHistoryService(uow=uow, server_read=server_read)
