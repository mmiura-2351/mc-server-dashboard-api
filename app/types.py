from enum import Enum
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.users.models import User


class FileType(str, Enum):
    directory = "directory"
    config = "config"
    world = "world"
    plugin = "plugin"
    mod = "mod"
    log = "log"
    other = "other"


# 共通の型定義
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
