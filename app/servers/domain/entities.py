"""Pure domain entities for the servers domain (minimal seed).

This is a stub introduced for #225 (templates) so that the
cross-domain `ServerReadPort.get` method can return a typed value
without the templates use case knowing about SQLAlchemy.

TBD(#154-8): the full `ServerEntity` and accompanying `ServerRepository`
land in Issue #228. Only the fields the templates domain genuinely
consumes today are included here; do not speculatively expand the
surface.
"""

from dataclasses import dataclass

from app.servers.models import ServerType  # known deviation, see #235 / #228


@dataclass(frozen=True)
class ServerEntity:
    """Read-only cross-domain view of a Server row.

    Only the fields consumed by `TemplateService.create_template_from_server`
    are exposed. When #228 finalises the servers domain, this dataclass
    will be replaced (or absorbed) by the proper `ServerEntity`.
    """

    id: int
    name: str
    directory_path: str
    minecraft_version: str
    server_type: ServerType
    port: int
    max_memory: int
    max_players: int
