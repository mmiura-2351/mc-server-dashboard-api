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

    Only the fields consumed by today's cross-domain callers are
    exposed. When #228 finalises the servers domain, this dataclass
    will be replaced (or absorbed) by the proper `ServerEntity`.

    `owner_id` was added in #226 (groups) so the groups application
    layer can enforce the "only the server owner + admins may
    attach/detach groups" rule without the router doing business
    logic. Carries the `TBD(#154-8)` marker like the surrounding
    fields.
    """

    id: int
    name: str
    directory_path: str
    minecraft_version: str
    server_type: ServerType
    port: int
    max_memory: int
    max_players: int
    # TBD(#154-8): added for #226 (groups). Needed so the groups
    # application service can apply `can_manage_server_groups`
    # (admin OR server-owner) without leaking ORM rows through the
    # router. See `app.groups.application.service`.
    owner_id: int
