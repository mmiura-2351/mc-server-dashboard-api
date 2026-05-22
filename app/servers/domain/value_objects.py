"""Domain-pure value objects for the servers / backups modules.

Per `docs/ARCHITECTURE.md` §4.1, this module must not import from any
framework, database driver, or HTTP client. Only the Python standard
library is allowed.

`ServerType`, `ServerStatus`, `BackupType`, and `BackupStatus` live here
so that adjacent domain modules (`app.servers.domain`,
`app.backups.domain`, `app.templates.domain`, `app.groups.domain`,
`app.versions.domain`) can reference them without transitively loading
SQLAlchemy. The SQLAlchemy ORM tables in `app.servers.models` re-import
these enums so the on-disk column types remain unchanged.
"""

import enum


class ServerStatus(enum.Enum):
    stopped = "stopped"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    error = "error"


class ServerType(enum.Enum):
    vanilla = "vanilla"
    forge = "forge"
    paper = "paper"


class BackupType(enum.Enum):
    manual = "manual"
    scheduled = "scheduled"
    pre_update = "pre_update"


class BackupStatus(enum.Enum):
    creating = "creating"
    completed = "completed"
    failed = "failed"


__all__ = ["ServerStatus", "ServerType", "BackupType", "BackupStatus"]
