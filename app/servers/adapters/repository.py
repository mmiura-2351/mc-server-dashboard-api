"""SQLAlchemy implementation of `ServerRepository`.

The adapter is the only layer that knows about the SQLAlchemy ORM and
the `Server` / `User` columns; it converts ORM rows to/from domain
entities so the application layer never sees ORM types.

Per the UnitOfWork pattern, most repository methods **do not commit**.
They stage changes on the session and rely on the surrounding
`SqlAlchemyServersUnitOfWork` (or the caller) to commit.

The two status writes (`update_status`, `batch_update_statuses`) are
the documented exception: they own their transaction via
`app.core.database_utils.with_transaction` so the existing
backoff/retry semantics the legacy code relied on are preserved (M-8
/ D-5 in the #228 plan).

Cross-domain JOIN against `User` (for `owner_username`) is
intentionally kept inside this adapter rather than dispatched through
a `UserReadPort`: the alternative would issue one query per server row
(legacy N+1). See `docs/app/ARCHITECTURE.md` Section 4.3 — the adapter layer is
allowed to touch the ORM directly; only the **application** layer is
forbidden.
"""

from typing import List, Mapping, Optional

from sqlalchemy.orm import Session, joinedload

from app.core.database_utils import with_transaction
from app.servers.domain.entities import (
    CreateServerCommand,
    ServerEntity,
    ServerListPage,
    ServerListSpec,
    UpdateServerCommand,
)
from app.servers.models import Server, ServerStatus


def _server_to_entity(row: Server) -> ServerEntity:
    """Convert an ORM row to a `ServerEntity`.

    Reads `row.owner.username` eagerly: callers that need
    `owner_username` populated must load the row with
    `joinedload(Server.owner)` so the access does not trigger a
    separate SELECT. Callsites that intentionally skip the JOIN leave
    the field as `None`.
    """
    owner_username: Optional[str] = None
    # `row.owner` is the SQLAlchemy relationship; touching it without
    # a `joinedload` would issue a stray SELECT. The repository's
    # read methods either include the join (when the caller cares
    # about `owner_username`) or rely on the loader strategy. We
    # check `__dict__` to avoid forcing a lazy load when the
    # relationship was not eagerly populated.
    if "owner" in row.__dict__:
        owner = row.__dict__["owner"]
        if owner is not None:
            owner_username = owner.username
    return ServerEntity(
        id=row.id,
        name=row.name,
        directory_path=row.directory_path,
        minecraft_version=row.minecraft_version,
        server_type=row.server_type,
        port=row.port,
        max_memory=row.max_memory,
        max_players=row.max_players,
        owner_id=row.owner_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        description=row.description,
        # Defensive against legacy NULL rows; ORM returns bool today.
        is_deleted=bool(row.is_deleted),
        owner_username=owner_username,
    )


class SqlAlchemyServerRepository:
    """SQLAlchemy-backed implementation of the servers persistence Port."""

    def __init__(self, db: Session):
        self._db = db

    # ===================
    # Internal helpers
    # ===================

    def _base_query(self, *, with_owner: bool = True):
        query = self._db.query(Server)
        if with_owner:
            query = query.options(joinedload(Server.owner))
        return query

    def _exclude_deleted(self, query, include_deleted: bool):
        if include_deleted:
            return query
        return query.filter(Server.is_deleted.is_(False))

    # ===================
    # Reads
    # ===================

    async def get(
        self, server_id: int, *, include_deleted: bool = False
    ) -> Optional[ServerEntity]:
        query = self._base_query().filter(Server.id == server_id)
        query = self._exclude_deleted(query, include_deleted)
        row = query.one_or_none()
        return _server_to_entity(row) if row is not None else None

    async def get_by_name(
        self, name: str, *, include_deleted: bool = False
    ) -> Optional[ServerEntity]:
        query = self._base_query().filter(Server.name == name)
        query = self._exclude_deleted(query, include_deleted)
        row = query.first()
        return _server_to_entity(row) if row is not None else None

    async def list_paged(self, spec: ServerListSpec) -> ServerListPage:
        query = self._base_query()
        query = self._exclude_deleted(query, spec.include_deleted)

        if spec.owner_id is not None:
            query = query.filter(Server.owner_id == spec.owner_id)
        if spec.status is not None:
            query = query.filter(Server.status == spec.status)
        if spec.server_type is not None:
            query = query.filter(Server.server_type == spec.server_type)

        query = query.order_by(Server.created_at.desc())

        total = query.count()
        rows = query.offset((spec.page - 1) * spec.size).limit(spec.size).all()
        return ServerListPage(
            entities=[_server_to_entity(r) for r in rows],
            total=total,
            page=spec.page,
            size=spec.size,
        )

    async def list_by_status(
        self, status: ServerStatus, *, include_deleted: bool = False
    ) -> List[ServerEntity]:
        query = self._base_query().filter(Server.status == status)
        query = self._exclude_deleted(query, include_deleted)
        return [_server_to_entity(r) for r in query.all()]

    async def list_by_port(
        self,
        port: Optional[int],
        *,
        statuses: Optional[List[ServerStatus]] = None,
        exclude_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> List[ServerEntity]:
        """See `ServerRepository.list_by_port`."""
        query = self._base_query()
        query = self._exclude_deleted(query, include_deleted)
        if port is not None:
            query = query.filter(Server.port == port)
        if statuses:
            query = query.filter(Server.status.in_(statuses))
        if exclude_id is not None:
            query = query.filter(Server.id != exclude_id)
        return [_server_to_entity(r) for r in query.all()]

    async def list_by_ids(
        self, server_ids: List[int], *, include_deleted: bool = False
    ) -> List[ServerEntity]:
        if not server_ids:
            return []
        query = self._base_query().filter(Server.id.in_(server_ids))
        query = self._exclude_deleted(query, include_deleted)
        return [_server_to_entity(r) for r in query.all()]

    async def list_by_owner(
        self, owner_id: int, *, include_deleted: bool = False
    ) -> List[ServerEntity]:
        query = self._base_query().filter(Server.owner_id == owner_id)
        query = self._exclude_deleted(query, include_deleted)
        return [_server_to_entity(r) for r in query.all()]

    # ===================
    # Writes (stage-only)
    # ===================

    async def add(self, command: CreateServerCommand) -> ServerEntity:
        row = Server(
            name=command.name,
            description=command.description,
            minecraft_version=command.minecraft_version,
            server_type=command.server_type,
            directory_path=command.directory_path,
            port=command.port,
            max_memory=command.max_memory,
            max_players=command.max_players,
            owner_id=command.owner_id,
        )
        self._db.add(row)
        self._db.flush()
        # Populate the server-side defaults (`status`, `created_at`,
        # `updated_at`) and the `owner` relation so `_server_to_entity`
        # does not trigger a stray lazy SELECT.
        self._db.refresh(
            row, attribute_names=["status", "created_at", "updated_at", "owner"]
        )
        return _server_to_entity(row)

    async def update(
        self, server_id: int, command: UpdateServerCommand
    ) -> Optional[ServerEntity]:
        row = (
            self._db.query(Server)
            .options(joinedload(Server.owner))
            .filter(Server.id == server_id)
            .one_or_none()
        )
        if row is None:
            return None
        for field_name, value in command.applied_fields().items():
            setattr(row, field_name, value)
        self._db.flush()
        return _server_to_entity(row)

    async def soft_delete(self, server_id: int) -> bool:
        row = self._db.query(Server).filter(Server.id == server_id).one_or_none()
        if row is None:
            return False
        row.is_deleted = True
        row.status = ServerStatus.stopped
        self._db.flush()
        return True

    # ===================
    # Status writes (own-transaction)
    # ===================

    async def update_status(
        self, server_id: int, status: ServerStatus
    ) -> Optional[ServerEntity]:
        """Set a single server's status atomically (with retry).

        Owns its transaction via `with_transaction` so the call inherits
        the legacy backoff/retry semantics (D-5: the UoW carries no
        retry-aware commit variant — retry is local).
        """

        def _do(session: Session) -> Optional[ServerEntity]:
            row = (
                session.query(Server)
                .options(joinedload(Server.owner))
                .filter(Server.id == server_id)
                .one_or_none()
            )
            if row is None:
                return None
            row.status = status
            session.flush()
            return _server_to_entity(row)

        return with_transaction(self._db, _do)

    async def update_port(self, server_id: int, port: int) -> Optional[ServerEntity]:
        """Set a single server's port atomically (with retry).

        Owns its transaction via `with_transaction`, mirroring
        `update_status`. Introduced for #272 so the
        `simplified_sync_service` can flush a manually-edited
        ``server.properties`` port back to the DB through the Port
        instead of mutating a SQLAlchemy `Server` row in place.
        """

        def _do(session: Session) -> Optional[ServerEntity]:
            row = (
                session.query(Server)
                .options(joinedload(Server.owner))
                .filter(Server.id == server_id)
                .one_or_none()
            )
            if row is None:
                return None
            row.port = port
            session.flush()
            return _server_to_entity(row)

        return with_transaction(self._db, _do)

    async def batch_update_statuses(
        self, updates: Mapping[int, ServerStatus]
    ) -> Mapping[int, Optional[ServerEntity]]:
        """Apply many status updates inside one transaction (with retry).

        Returns a mapping from input id to the resulting entity (or
        `None` if no such server existed). Callers commonly use this
        for startup synchronisation between the filesystem and the
        database.
        """
        if not updates:
            return {}

        ids = list(updates.keys())

        def _do(session: Session) -> Mapping[int, Optional[ServerEntity]]:
            rows = (
                session.query(Server)
                .options(joinedload(Server.owner))
                .filter(Server.id.in_(ids))
                .all()
            )
            row_by_id = {r.id: r for r in rows}
            result: dict = {}
            for sid, new_status in updates.items():
                row = row_by_id.get(sid)
                if row is None:
                    result[sid] = None
                    continue
                row.status = new_status
                result[sid] = row
            session.flush()
            # Convert after flush so we observe persisted state
            return {
                sid: (
                    _server_to_entity(row_by_id[sid])
                    if row_by_id.get(sid) is not None
                    else None
                )
                for sid in updates.keys()
            }

        return with_transaction(self._db, _do)
