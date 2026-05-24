"""Server factory helpers for test fixtures (Issue #168).

Provides `make_server(db, owner, **kw)` to standardize the inline
`Server(...)` construction blocks that previously appeared across many
integration test files. The defaults mirror the legacy `sample_server`
fixture.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.servers.models import Server, ServerStatus, ServerType
from app.users.models import User


def make_server(
    db: Session,
    owner: User,
    *,
    name: str = "Test Server",
    description: str = "A test server",
    minecraft_version: str = "1.20.1",
    server_type: ServerType = ServerType.vanilla,
    status: ServerStatus = ServerStatus.stopped,
    directory_path: str = "./servers/1",
    port: int = 25565,
    max_memory: int = 1024,
    max_players: int = 20,
    **extra: Any,
) -> Server:
    """Create and persist a `Server` row owned by `owner`.

    Extra keyword args are forwarded to the `Server` constructor for
    columns we don't model explicitly.
    """
    server = Server(
        name=name,
        description=description,
        minecraft_version=minecraft_version,
        server_type=server_type,
        status=status,
        directory_path=directory_path,
        port=port,
        max_memory=max_memory,
        max_players=max_players,
        owner_id=owner.id,
        **extra,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


__all__ = ["make_server"]
