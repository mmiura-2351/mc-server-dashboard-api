from enum import Enum
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.users.models import User


class FileType(str, Enum):
    text = "text"
    directory = "directory"
    binary = "binary"
    other = "other"


# Common type definitions
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
