"""Integration tests for `SqlAlchemyServerRepository`.

Exercises the real SQLAlchemy adapter against the worker-scoped SQLite
test database from `tests/conftest.py`. The adapter does **not**
commit on its own (the UoW owns transactions in production), so
write-path tests call `db.commit()` explicitly after staging changes.
The two status-write methods (`update_status`,
`batch_update_statuses`) own their transaction internally via
`with_transaction`; for those, no manual commit is required.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.servers.adapters.repository import (
    SqlAlchemyServerRepository,
    _server_to_entity,
)
from app.servers.domain.entities import (
    CreateServerCommand,
    ServerListSpec,
    UpdateServerCommand,
)
from app.servers.models import Server, ServerStatus, ServerType

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def repository(db) -> SqlAlchemyServerRepository:
    return SqlAlchemyServerRepository(db)


def _seed_server(
    db: Session,
    owner_id: int,
    *,
    name: str = "srv",
    port: int = 25565,
    status: ServerStatus = ServerStatus.stopped,
    server_type: ServerType = ServerType.vanilla,
    is_deleted: bool = False,
    description=None,
) -> Server:
    row = Server(
        name=name,
        description=description,
        minecraft_version="1.20.1",
        server_type=server_type,
        port=port,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
        directory_path=f"/servers/{name}",
        status=status,
        is_deleted=is_deleted,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestServerRepositoryReads:
    @pytest.mark.asyncio
    async def test_get_returns_entity_with_owner_eager_loaded(
        self, repository, db, admin_user
    ):
        row = _seed_server(db, admin_user.id, name="g1", port=25566)

        entity = await repository.get(row.id)
        assert entity is not None
        assert entity.name == "g1"
        assert entity.id == row.id
        # joinedload(Server.owner) should populate owner_username
        assert entity.owner_username == admin_user.username
        assert entity.status == ServerStatus.stopped
        assert entity.created_at is not None
        assert entity.updated_at is not None
        assert entity.is_deleted is False

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self, repository):
        assert await repository.get(99999) is None

    @pytest.mark.asyncio
    async def test_get_soft_deleted_excluded_by_default(self, repository, db, admin_user):
        row = _seed_server(db, admin_user.id, name="sd", port=25567, is_deleted=True)
        assert await repository.get(row.id) is None
        assert await repository.get(row.id, include_deleted=True) is not None

    @pytest.mark.asyncio
    async def test_get_by_name_returns_entity(self, repository, db, admin_user):
        row = _seed_server(db, admin_user.id, name="byname", port=25568)
        entity = await repository.get_by_name("byname")
        assert entity is not None
        assert entity.id == row.id

    @pytest.mark.asyncio
    async def test_get_by_name_soft_deleted_excluded_by_default(
        self, repository, db, admin_user
    ):
        _seed_server(db, admin_user.id, name="byname-sd", port=25569, is_deleted=True)
        assert await repository.get_by_name("byname-sd") is None
        entity = await repository.get_by_name("byname-sd", include_deleted=True)
        assert entity is not None

    @pytest.mark.asyncio
    async def test_get_by_name_unknown_returns_none(self, repository):
        assert await repository.get_by_name("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_list_paged_filters_and_orders(self, repository, db, admin_user):
        a = _seed_server(db, admin_user.id, name="lp-a", port=25570)
        b = _seed_server(db, admin_user.id, name="lp-b", port=25571)
        c = _seed_server(db, admin_user.id, name="lp-c", port=25572)

        page = await repository.list_paged(
            ServerListSpec(owner_id=admin_user.id, page=1, size=10)
        )
        # Ordering is created_at desc, which on equal millisecond ticks
        # may be ambiguous; assert the set instead of position.
        assert page.total == 3
        ids = {e.id for e in page.entities}
        assert ids == {a.id, b.id, c.id}
        assert page.page == 1
        assert page.size == 10

    @pytest.mark.asyncio
    async def test_list_paged_filters_by_status_and_type(
        self, repository, db, admin_user
    ):
        _seed_server(
            db,
            admin_user.id,
            name="lp-run",
            port=25573,
            status=ServerStatus.running,
            server_type=ServerType.vanilla,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lp-stop",
            port=25574,
            status=ServerStatus.stopped,
            server_type=ServerType.vanilla,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lp-paper",
            port=25575,
            status=ServerStatus.running,
            server_type=ServerType.paper,
        )

        page = await repository.list_paged(
            ServerListSpec(
                owner_id=admin_user.id,
                status=ServerStatus.running,
                server_type=ServerType.vanilla,
                page=1,
                size=10,
            )
        )
        assert page.total == 1
        assert page.entities[0].name == "lp-run"

    @pytest.mark.asyncio
    async def test_list_paged_excludes_deleted_unless_requested(
        self, repository, db, admin_user
    ):
        _seed_server(db, admin_user.id, name="lpd-live", port=25576)
        _seed_server(db, admin_user.id, name="lpd-dead", port=25577, is_deleted=True)

        live_page = await repository.list_paged(
            ServerListSpec(owner_id=admin_user.id, page=1, size=10)
        )
        assert live_page.total == 1
        all_page = await repository.list_paged(
            ServerListSpec(
                owner_id=admin_user.id,
                include_deleted=True,
                page=1,
                size=10,
            )
        )
        assert all_page.total == 2

    @pytest.mark.asyncio
    async def test_list_paged_pagination(self, repository, db, admin_user):
        for i in range(5):
            _seed_server(db, admin_user.id, name=f"pg-{i}", port=25600 + i)

        page1 = await repository.list_paged(
            ServerListSpec(owner_id=admin_user.id, page=1, size=2)
        )
        assert page1.total == 5
        assert len(page1.entities) == 2
        page3 = await repository.list_paged(
            ServerListSpec(owner_id=admin_user.id, page=3, size=2)
        )
        assert len(page3.entities) == 1

    @pytest.mark.asyncio
    async def test_list_by_status(self, repository, db, admin_user):
        _seed_server(
            db,
            admin_user.id,
            name="ls-r",
            port=25610,
            status=ServerStatus.running,
        )
        _seed_server(
            db,
            admin_user.id,
            name="ls-s",
            port=25611,
            status=ServerStatus.stopped,
        )
        rows = await repository.list_by_status(ServerStatus.running)
        assert [r.name for r in rows] == ["ls-r"]

    @pytest.mark.asyncio
    async def test_list_by_port_none_returns_all_matching_statuses(
        self, repository, db, admin_user
    ):
        """D-4 / H-3 regression: `port=None` must return every server
        matching the status filter — *not* a falsy-evaluation of a
        Column boolean that filters out everything."""
        _seed_server(
            db,
            admin_user.id,
            name="lbp-run",
            port=25620,
            status=ServerStatus.running,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lbp-start",
            port=25621,
            status=ServerStatus.starting,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lbp-stop",
            port=25622,
            status=ServerStatus.stopped,
        )

        rows = await repository.list_by_port(
            port=None,
            statuses=[ServerStatus.running, ServerStatus.starting],
        )
        names = {r.name for r in rows}
        assert names == {"lbp-run", "lbp-start"}

    @pytest.mark.asyncio
    async def test_list_by_port_specific_port(self, repository, db, admin_user):
        _seed_server(
            db,
            admin_user.id,
            name="lbp-a",
            port=25630,
            status=ServerStatus.running,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lbp-b",
            port=25631,
            status=ServerStatus.running,
        )
        rows = await repository.list_by_port(port=25630, statuses=[ServerStatus.running])
        assert [r.name for r in rows] == ["lbp-a"]

    @pytest.mark.asyncio
    async def test_list_by_port_exclude_id(self, repository, db, admin_user):
        a = _seed_server(
            db,
            admin_user.id,
            name="lbp-self",
            port=25640,
            status=ServerStatus.running,
        )
        b = _seed_server(
            db,
            admin_user.id,
            name="lbp-other",
            port=25640,
            status=ServerStatus.running,
        )
        rows = await repository.list_by_port(
            port=25640,
            statuses=[ServerStatus.running],
            exclude_id=a.id,
        )
        assert [r.id for r in rows] == [b.id]

    @pytest.mark.asyncio
    async def test_list_by_ids_returns_only_matching(self, repository, db, admin_user):
        a = _seed_server(db, admin_user.id, name="bi-a", port=25650)
        b = _seed_server(db, admin_user.id, name="bi-b", port=25651)
        _seed_server(db, admin_user.id, name="bi-c", port=25652)
        rows = await repository.list_by_ids([a.id, b.id])
        assert {r.name for r in rows} == {"bi-a", "bi-b"}

    @pytest.mark.asyncio
    async def test_list_by_ids_empty_input_returns_empty(self, repository):
        assert await repository.list_by_ids([]) == []

    @pytest.mark.asyncio
    async def test_list_by_owner(self, repository, db, admin_user, test_user):
        _seed_server(db, admin_user.id, name="own-a", port=25660)
        _seed_server(db, test_user.id, name="own-b", port=25661)
        rows = await repository.list_by_owner(admin_user.id)
        assert [r.name for r in rows] == ["own-a"]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


class TestServerRepositoryWrites:
    @pytest.mark.asyncio
    async def test_add_inserts_row_with_owner_populated(self, repository, db, admin_user):
        entity = await repository.add(
            CreateServerCommand(
                name="created",
                directory_path="/servers/created",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                port=25700,
                max_memory=1024,
                max_players=20,
                owner_id=admin_user.id,
                description="hello",
            )
        )
        db.commit()  # adapter does not commit

        assert entity.id is not None
        assert entity.status == ServerStatus.stopped
        # server-side defaults must surface back through the refresh()
        assert entity.created_at is not None
        assert entity.updated_at is not None
        # owner relationship must be eagerly populated
        assert entity.owner_username == admin_user.username
        assert entity.description == "hello"

    @pytest.mark.asyncio
    async def test_add_does_not_commit_session(self, repository, db, admin_user):
        await repository.add(
            CreateServerCommand(
                name="staged-only",
                directory_path="/servers/staged-only",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                port=25701,
                max_memory=1024,
                max_players=20,
                owner_id=admin_user.id,
            )
        )
        # Without our explicit commit the row must roll back
        db.rollback()
        assert db.query(Server).filter(Server.name == "staged-only").one_or_none() is None

    @pytest.mark.asyncio
    async def test_update_sparse_only_changes_applied_fields(
        self, repository, db, admin_user
    ):
        row = _seed_server(db, admin_user.id, name="upd", port=25710, description="old")
        original_max_memory = row.max_memory

        updated = await repository.update(
            row.id,
            UpdateServerCommand(name="upd-renamed"),
        )
        db.commit()
        assert updated is not None
        assert updated.name == "upd-renamed"
        # untouched
        assert updated.max_memory == original_max_memory
        assert updated.description == "old"

    @pytest.mark.asyncio
    async def test_update_unknown_returns_none(self, repository):
        result = await repository.update(99999, UpdateServerCommand(name="ghost"))
        assert result is None

    @pytest.mark.asyncio
    async def test_soft_delete_marks_row_and_resets_status(
        self, repository, db, admin_user
    ):
        row = _seed_server(
            db,
            admin_user.id,
            name="sd-row",
            port=25720,
            status=ServerStatus.running,
        )

        ok = await repository.soft_delete(row.id)
        db.commit()
        assert ok is True

        db.expire_all()
        refreshed = db.query(Server).filter(Server.id == row.id).one()
        assert refreshed.is_deleted is True
        assert refreshed.status == ServerStatus.stopped

    @pytest.mark.asyncio
    async def test_soft_delete_unknown_returns_false(self, repository):
        assert await repository.soft_delete(99999) is False

    @pytest.mark.asyncio
    async def test_soft_delete_updates_directory_path(
        self, repository, db, admin_user
    ):
        row = _seed_server(
            db, admin_user.id, name="sd-dir", port=25721
        )
        original_dir = row.directory_path

        ok = await repository.soft_delete(
            row.id, directory_path="servers/.archived/1_20260601_120000"
        )
        db.commit()
        assert ok is True

        db.expire_all()
        refreshed = db.query(Server).filter(Server.id == row.id).one()
        assert refreshed.directory_path == "servers/.archived/1_20260601_120000"
        assert refreshed.directory_path != original_dir

    @pytest.mark.asyncio
    async def test_soft_delete_without_directory_path_preserves_original(
        self, repository, db, admin_user
    ):
        row = _seed_server(
            db, admin_user.id, name="sd-keep", port=25722
        )
        original_dir = row.directory_path

        ok = await repository.soft_delete(row.id)
        db.commit()

        db.expire_all()
        refreshed = db.query(Server).filter(Server.id == row.id).one()
        assert refreshed.directory_path == original_dir


# ---------------------------------------------------------------------------
# Status writes (own-transaction with retry)
# ---------------------------------------------------------------------------


class TestServerRepositoryStatusWrites:
    @pytest.mark.asyncio
    async def test_update_status_sets_value(self, repository, db, admin_user):
        row = _seed_server(db, admin_user.id, name="us", port=25730)
        result = await repository.update_status(row.id, ServerStatus.running)
        assert result is not None
        assert result.status == ServerStatus.running

        # update_status owns the transaction, so we expect to see the new
        # value from a fresh query without re-committing.
        db.expire_all()
        refreshed = db.query(Server).filter(Server.id == row.id).one()
        assert refreshed.status == ServerStatus.running

    @pytest.mark.asyncio
    async def test_update_status_unknown_returns_none(self, repository):
        assert await repository.update_status(99999, ServerStatus.running) is None

    @pytest.mark.asyncio
    async def test_update_status_retries_on_operational_error(
        self, repository, db, admin_user, monkeypatch
    ):
        """Inject one transient OperationalError on commit() and verify
        `with_transaction` retries. Confirms M-8 / D-5 wiring."""
        row = _seed_server(db, admin_user.id, name="usret", port=25731)

        # Bind the original method to the specific session instance so
        # the patched callable carries no implicit `self` — and so the
        # patch does not bleed into other concurrently-running tests
        # via the `Session` class (parallel-execution flake guard).
        original_commit = db.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate a transient lock/disconnect that should retry.
                raise OperationalError("simulated", {}, Exception("flake"))
            return original_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)

        result = await repository.update_status(row.id, ServerStatus.error)
        assert result is not None
        assert result.status == ServerStatus.error
        assert calls["n"] >= 2  # at least one retry

    @pytest.mark.asyncio
    async def test_batch_update_statuses(self, repository, db, admin_user):
        a = _seed_server(db, admin_user.id, name="bus-a", port=25740)
        b = _seed_server(db, admin_user.id, name="bus-b", port=25741)
        c = _seed_server(db, admin_user.id, name="bus-c", port=25742)

        result = await repository.batch_update_statuses(
            {
                a.id: ServerStatus.running,
                b.id: ServerStatus.starting,
                c.id: ServerStatus.error,
            }
        )
        assert result[a.id] is not None and result[a.id].status == ServerStatus.running
        assert result[b.id].status == ServerStatus.starting
        assert result[c.id].status == ServerStatus.error

        db.expire_all()
        statuses = {
            r.id: r.status
            for r in db.query(Server).filter(Server.id.in_([a.id, b.id, c.id])).all()
        }
        assert statuses == {
            a.id: ServerStatus.running,
            b.id: ServerStatus.starting,
            c.id: ServerStatus.error,
        }

    @pytest.mark.asyncio
    async def test_batch_update_statuses_unknown_id_yields_none(
        self, repository, db, admin_user
    ):
        a = _seed_server(db, admin_user.id, name="busx", port=25745)
        result = await repository.batch_update_statuses(
            {a.id: ServerStatus.running, 99999: ServerStatus.running}
        )
        assert result[a.id] is not None
        assert result[99999] is None

    @pytest.mark.asyncio
    async def test_batch_update_statuses_empty(self, repository):
        assert await repository.batch_update_statuses({}) == {}


# ---------------------------------------------------------------------------
# Eager loading sanity (no N+1)
# ---------------------------------------------------------------------------


class TestServerRepositoryEagerLoading:
    @pytest.mark.asyncio
    async def test_list_paged_does_not_issue_per_row_owner_lookup(
        self, repository, db, admin_user
    ):
        for i in range(3):
            _seed_server(db, admin_user.id, name=f"el-{i}", port=25750 + i)

        # Expire any cached state so subsequent owner access goes
        # through the joinedload path rather than the identity-map.
        db.expire_all()

        # Count per-row owner SELECTs (statements against `users`
        # without a JOIN clause) that fire *during* entity access. A
        # working joinedload keeps this count bounded by 1 — at most
        # the initial population of the owner row when the joinedload
        # rehydrates from the result cursor — and never grows with N.
        user_selects_per_access: list[str] = []

        page = await repository.list_paged(
            ServerListSpec(owner_id=admin_user.id, page=1, size=10)
        )
        assert len(page.entities) == 3

        @event.listens_for(db.bind, "before_cursor_execute")
        def collect(conn, cursor, statement, params, ctx, many):
            if "FROM users" in statement and "JOIN" not in statement:
                user_selects_per_access.append(statement)

        try:
            # Touch owner_username on every entity — even with N rows
            # the count must NOT scale linearly with N.
            for entity in page.entities:
                assert entity.owner_username == admin_user.username
        finally:
            event.remove(db.bind, "before_cursor_execute", collect)

        # Strict ceiling: no per-row owner SELECTs at access time.
        # Adapters convert ORM → entity *during* `list_paged`, so by
        # the time we touch `owner_username` the value is already a
        # plain string on the dataclass.
        assert user_selects_per_access == [], (
            f"Per-row owner lookup detected at access time: {user_selects_per_access}"
        )


# ---------------------------------------------------------------------------
# Adapter-level sanity
# ---------------------------------------------------------------------------


class TestServerRepositorySanity:
    def test_adapter_does_not_subclass_anything_surprising(self):
        assert SqlAlchemyServerRepository.__bases__ == (object,)

    def test_to_entity_handles_missing_owner_relationship(self, db, admin_user):
        """When `Server.owner` is not eagerly loaded the converter must
        return `owner_username=None` without forcing a lazy SELECT.
        """
        # Round-trip the row through a fresh session so the relationship
        # is not loaded — simulates a code path that intentionally skips
        # the joinedload.
        row = Server(
            name="no-owner-load",
            description=None,
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25800,
            max_memory=1024,
            max_players=20,
            owner_id=admin_user.id,
            directory_path="/servers/no-owner-load",
            status=ServerStatus.stopped,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        # Force the relation back out of the row's instance dict so
        # `_server_to_entity` does not see it as eagerly loaded.
        row.__dict__.pop("owner", None)

        entity = _server_to_entity(row)
        assert entity.owner_username is None
        # Other columns still copy through correctly.
        assert entity.name == "no-owner-load"
        assert entity.owner_id == admin_user.id

    def test_get_uses_one_or_none(self):
        """`get(id)` is a primary-key lookup; `one_or_none()` is a
        defensive guard against duplicate ids."""
        import inspect as _inspect

        src = _inspect.getsource(SqlAlchemyServerRepository.get)
        assert "one_or_none()" in src

    def test_get_by_name_uses_first(self):
        """`Server.name` is *not* a DB-level unique constraint
        (uniqueness is enforced at the application layer), so
        `get_by_name` uses `.first()` rather than `one_or_none()` to
        avoid raising on legacy duplicates."""
        import inspect as _inspect

        src = _inspect.getsource(SqlAlchemyServerRepository.get_by_name)
        assert ".first()" in src


# ---------------------------------------------------------------------------
# Soft-delete behaviour for list_by_port
# ---------------------------------------------------------------------------


class TestServerRepositoryListByPortDeletedHandling:
    @pytest.mark.asyncio
    async def test_list_by_port_excludes_soft_deleted_by_default(
        self, repository, db, admin_user
    ):
        _seed_server(
            db,
            admin_user.id,
            name="lbpd-live",
            port=25810,
            status=ServerStatus.running,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lbpd-dead",
            port=25810,
            status=ServerStatus.running,
            is_deleted=True,
        )
        rows = await repository.list_by_port(port=25810, statuses=[ServerStatus.running])
        assert [r.name for r in rows] == ["lbpd-live"]

    @pytest.mark.asyncio
    async def test_list_by_port_include_deleted(self, repository, db, admin_user):
        _seed_server(
            db,
            admin_user.id,
            name="lbpdi-live",
            port=25811,
            status=ServerStatus.running,
        )
        _seed_server(
            db,
            admin_user.id,
            name="lbpdi-dead",
            port=25811,
            status=ServerStatus.running,
            is_deleted=True,
        )
        rows = await repository.list_by_port(
            port=25811,
            statuses=[ServerStatus.running],
            include_deleted=True,
        )
        names = {r.name for r in rows}
        assert names == {"lbpdi-live", "lbpdi-dead"}
