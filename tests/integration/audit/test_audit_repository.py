"""Integration tests for `SqlAlchemyAuditRepository` and `SqlAlchemyAuditWriter`.

Uses the real worker-scoped SQLite test session. Confirms:

- The adapter converts ORM rows to `AuditLogEntity` (joined `user_email`
  included when the user row exists).
- The writer's direct-DB path persists rows and commits them on its
  own (no caller-side commit).
- The writer swallows failures rather than propagating.
- Statistics aggregate consistently with the underlying rows.
"""

import logging

import pytest

from app.audit.adapters.repository import (
    SqlAlchemyAuditRepository,
    SqlAlchemyAuditWriter,
)
from app.audit.domain.entities import AuditEventCommand, LogFilters
from app.audit.models import AuditLog
from app.users.models import Role, User


@pytest.fixture
def repository(db):
    return SqlAlchemyAuditRepository(db)


@pytest.fixture
def truncate_audit_logs(db):
    """Delete all AuditLog rows before the test, then yield.

    Allows statistics tests to assert exact integer counts without
    interference from residue left by other tests in the shared session.
    """
    db.query(AuditLog).delete()
    db.commit()
    yield
    # No explicit teardown: the function-scoped `db` fixture in conftest
    # already deletes all rows from every table after each test.


@pytest.fixture
def writer(db):
    """Writer pointed at the worker-scoped test SQLite.

    The fixture takes `db` purely to ensure conftest's `Base.metadata.create_all`
    has run before the writer's first call constructs its own session.
    """
    _ = db
    return SqlAlchemyAuditWriter(tracker=None)


@pytest.fixture
def seeded_user(db):
    user = User(
        username="audit-target",
        email="audit-target@example.com",
        hashed_password="x",
        role=Role.user,
        is_active=True,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_writer_persists_event(db, writer, seeded_user) -> None:
    writer.record(
        AuditEventCommand(
            action="server_start",
            resource_type="server",
            resource_id=42,
            user_id=seeded_user.id,
            details={"foo": "bar"},
            ip_address="10.0.0.1",
        )
    )
    # Writer commits on its own — fresh query sees the row.
    rows = db.query(AuditLog).filter(AuditLog.action == "server_start").all()
    assert len(rows) == 1
    assert rows[0].user_id == seeded_user.id
    assert rows[0].resource_id == 42
    assert rows[0].ip_address == "10.0.0.1"


@pytest.mark.asyncio
async def test_writer_swallows_tracker_errors(db) -> None:
    """Tracker path: a raising add_event must be swallowed (Resolves #244)."""

    class _ExplodingTracker:
        def add_event(self, **_):
            raise RuntimeError("boom")

    _ = db
    bad_writer = SqlAlchemyAuditWriter(tracker=_ExplodingTracker())
    bad_writer.record(AuditEventCommand(action="x", resource_type="t"))


@pytest.mark.asyncio
async def test_writer_swallows_direct_write_errors(db) -> None:
    """Direct-write path: a broken session_factory must be swallowed (Resolves #244).

    A hand-rolled fake (not `MagicMock(spec=Session)`) is used here: pytest-xdist
    pickles items across worker boundaries, and pickling a SQLAlchemy `Session`
    mock recurses through Session's complex metaclass machinery and trips
    Python's recursion limit (see the comment in
    `tests/unit/users/test_protocol_conformance.py::_build_implementation`).
    """

    class _ExplodingSession:
        def add(self, instance) -> None:
            raise RuntimeError("boom")

        def commit(self) -> None:
            pass

        def close(self) -> None:
            pass

    _ = db
    bad_writer = SqlAlchemyAuditWriter(tracker=None, session_factory=_ExplodingSession)
    bad_writer.record(AuditEventCommand(action="x", resource_type="t"))


class _TrackerSpy:
    """Captures `add_event` kwargs so the mismatch-warning tests can prove
    the tracker value still wins after the warning is emitted (#239)."""

    def __init__(self, ip_address: str | None) -> None:
        self.ip_address = ip_address
        self.calls: list[dict] = []

    def add_event(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_writer_warns_on_ip_address_mismatch(caplog) -> None:
    """Tracker path: divergent ip_address emits exactly one WARNING and
    the tracker's value is still the one forwarded to `add_event`
    (Resolves #239)."""
    spy = _TrackerSpy(ip_address="1.2.3.4")
    writer = SqlAlchemyAuditWriter(tracker=spy)

    with caplog.at_level(logging.WARNING, logger="app.audit.adapters.repository"):
        writer.record(
            AuditEventCommand(action="y", resource_type="t", ip_address="10.0.0.99")
        )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    record = warnings[0]
    assert record.command_ip == "10.0.0.99"
    assert record.tracker_ip == "1.2.3.4"
    assert record.action == "y"
    # Tracker value still wins: add_event is invoked with the command's
    # kwargs (which carry no ip_address) — tracker.ip_address is what
    # `AuditTracker.add_event` stamps onto the event downstream.
    assert spy.calls == [
        {
            "action": "y",
            "resource_type": "t",
            "resource_id": None,
            "details": None,
            "user_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_writer_does_not_warn_when_ip_address_matches(caplog) -> None:
    """No warning when command and tracker agree on ip_address (#239)."""
    spy = _TrackerSpy(ip_address="1.2.3.4")
    writer = SqlAlchemyAuditWriter(tracker=spy)

    with caplog.at_level(logging.WARNING, logger="app.audit.adapters.repository"):
        writer.record(
            AuditEventCommand(action="y", resource_type="t", ip_address="1.2.3.4")
        )

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_writer_does_not_warn_when_command_ip_is_none(caplog) -> None:
    """No warning when command carries no ip_address — the tracker
    value is simply used and no comparison fires (#239)."""
    spy = _TrackerSpy(ip_address="1.2.3.4")
    writer = SqlAlchemyAuditWriter(tracker=spy)

    with caplog.at_level(logging.WARNING, logger="app.audit.adapters.repository"):
        writer.record(AuditEventCommand(action="y", resource_type="t"))

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_writer_does_not_commit_callers_session(db) -> None:
    """#240: audit must not commit caller's pending transaction.

    Scenario:
      1. Caller stages an uncommitted row.
      2. Caller invokes the audit writer (direct path — no tracker).
      3. Caller rolls back.

    Expected: caller's row is **not** persisted. (Pre-#240 the writer
    called `commit()` on the caller's session, which persisted the
    caller's pending row as a side effect.)

    The audit row's own persistence is not asserted here: on SQLite
    the caller's pending write holds a file-level lock, so the
    writer's fresh session blocks and the fire-and-forget swallow
    drops the audit row. Postgres avoids the lock contention. This
    test focuses on the property that matters for #240 — caller
    transaction isolation — and leaves the SQLite-vs-Postgres
    persistence story to integration runs against the production
    backend.
    """
    writer = SqlAlchemyAuditWriter(tracker=None)

    extra = User(
        username="must-not-persist",
        email="must-not-persist@example.com",
        hashed_password="x",
        role=Role.user,
        is_active=True,
        is_approved=True,
    )
    db.add(extra)
    db.flush()  # assigns an id but stays inside the open transaction

    writer.record(AuditEventCommand(action="server_start_240", resource_type="server"))

    db.rollback()

    assert db.query(User).filter(User.username == "must-not-persist").first() is None


@pytest.mark.asyncio
async def test_list_logs_returns_entities_with_user_email(
    db, writer, repository, seeded_user
) -> None:
    writer.record(
        AuditEventCommand(
            action="user_event",
            resource_type="server",
            user_id=seeded_user.id,
        )
    )
    logs = await repository.list_logs(LogFilters(action="user_event"), limit=10, offset=0)
    assert len(logs) == 1
    assert logs[0].user_id == seeded_user.id
    assert logs[0].user_email == seeded_user.email


@pytest.mark.asyncio
async def test_count_logs_matches_list(db, writer, repository) -> None:
    for i in range(3):
        writer.record(
            AuditEventCommand(action=f"countable_{i}", resource_type="t", user_id=99)
        )
    n = await repository.count_logs(LogFilters(user_id=99, action="countable"))
    assert n == 3


@pytest.mark.asyncio
async def test_list_user_activity(db, writer, repository, seeded_user) -> None:
    writer.record(
        AuditEventCommand(action="a", resource_type="t", user_id=seeded_user.id)
    )
    writer.record(
        AuditEventCommand(action="b", resource_type="t", user_id=seeded_user.id)
    )
    writer.record(
        AuditEventCommand(action="x", resource_type="t", user_id=seeded_user.id + 1)
    )

    rows = await repository.list_user_activity(seeded_user.id, limit=10)
    assert {r.action for r in rows} == {"a", "b"}


@pytest.mark.asyncio
async def test_security_alerts_filtered_by_resource_type(db, writer, repository) -> None:
    writer.record(
        AuditEventCommand(
            action="security_x",
            resource_type="security",
            details={"severity": "critical"},
        )
    )
    writer.record(AuditEventCommand(action="other", resource_type="server"))
    alerts = await repository.list_security_alerts(severity=None, limit=10)
    assert all(a.resource_type == "security" for a in alerts)
    assert any(a.action == "security_x" for a in alerts)


@pytest.mark.asyncio
async def test_security_alerts_filtered_by_severity(db, writer, repository) -> None:
    """Severity filter must work on SQLite (json_extract path — Resolves #241)."""
    writer.record(
        AuditEventCommand(
            action="sev_critical",
            resource_type="security",
            details={"severity": "critical"},
        )
    )
    writer.record(
        AuditEventCommand(
            action="sev_warning",
            resource_type="security",
            details={"severity": "warning"},
        )
    )
    critical_alerts = await repository.list_security_alerts(severity="critical", limit=10)
    assert any(a.action == "sev_critical" for a in critical_alerts)
    assert not any(a.action == "sev_warning" for a in critical_alerts)


@pytest.mark.asyncio
async def test_security_alerts_severity_emits_postgres_operator() -> None:
    """PostgreSQL dialect must emit the native `->>` JSON operator.

    The conftest session binds to SQLite, so the dialect-branch test
    above only covers the json_extract path. Stub the session's dialect
    to `postgresql`, capture the filter expression, and confirm the
    compiled SQL contains `->>` — proves the Postgres branch is
    reachable without needing a real Postgres backend (Resolves #241).
    """
    from unittest.mock import MagicMock

    from sqlalchemy.dialects import postgresql

    db = MagicMock()
    db.bind.dialect.name = "postgresql"
    query = MagicMock()
    query.options.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = []
    db.query.return_value = query

    repo = SqlAlchemyAuditRepository(db)
    await repo.list_security_alerts(severity="critical", limit=10)

    # Locate the severity filter by inspecting the compiled SQL of each
    # `.filter(...)` call rather than by positional index — survives
    # future refactors that reorder filters or fold them into a helper.
    def _compile(expr) -> str:
        return str(
            expr.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )

    severity_compiled = [
        _compile(call.args[0])
        for call in query.filter.call_args_list
        if "severity" in _compile(call.args[0])
    ]
    assert len(severity_compiled) == 1, query.filter.call_args_list
    assert "->>" in severity_compiled[0]
    assert "json_extract" not in severity_compiled[0]


@pytest.mark.asyncio
async def test_security_alerts_severity_rejects_unknown_dialect() -> None:
    """Unknown dialects must raise rather than silently return empty.

    Routing every non-Postgres dialect through `json_extract` would
    reintroduce the silent-no-match failure mode #241 was filed
    against — just for a different backend.
    """
    from unittest.mock import MagicMock

    db = MagicMock()
    db.bind.dialect.name = "mysql"
    query = MagicMock()
    query.options.return_value = query
    query.filter.return_value = query
    db.query.return_value = query

    repo = SqlAlchemyAuditRepository(db)
    with pytest.raises(NotImplementedError, match="mysql"):
        await repo.list_security_alerts(severity="critical", limit=10)


_STATS_USER_ID = 1234


@pytest.mark.asyncio
async def test_statistics_consistency(
    db, writer, repository, truncate_audit_logs
) -> None:
    # Truncated by fixture — exact counts are reliable.
    writer.record(
        AuditEventCommand(
            action="stats_seed_recent",
            resource_type="server",
            user_id=_STATS_USER_ID,
        )
    )

    stats = await repository.get_statistics()

    assert stats.total_logs == 1
    assert stats.recent_logs_24h == 1
    assert stats.security_events_7d == 0
    assert stats.most_active_users_30d == [(_STATS_USER_ID, 1)]
