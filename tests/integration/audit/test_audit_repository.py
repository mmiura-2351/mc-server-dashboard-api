"""Integration tests for `SqlAlchemyAuditRepository` and `SqlAlchemyAuditWriter`.

Uses the real worker-scoped SQLite test session. Confirms:

- The adapter converts ORM rows to `AuditLogEntity` (joined `user_email`
  included when the user row exists).
- The writer's direct-DB path persists rows and commits them on its
  own (no caller-side commit).
- The writer swallows failures rather than propagating.
- Statistics aggregate consistently with the underlying rows.
"""

from datetime import datetime, timezone

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
async def test_writer_swallows_errors(db) -> None:
    """Audit is fire-and-forget: failures on either path must not propagate.

    Exercised here on the tracker path (the cheaper of the two — a
    fault-injecting `session_factory` for the direct path is the
    target of #244).
    """

    class _ExplodingTracker:
        def add_event(self, **_):
            raise RuntimeError("boom")

    _ = db
    bad_writer = SqlAlchemyAuditWriter(tracker=_ExplodingTracker())
    # Must not raise; failure logged and discarded.
    bad_writer.record(AuditEventCommand(action="x", resource_type="t"))


@pytest.mark.asyncio
async def test_writer_warns_on_ip_address_mismatch(db, caplog) -> None:
    """Tracker path: mismatched ip_address emits a warning (Resolves #239)."""
    import logging

    class _TrackerWithIP:
        ip_address = "1.2.3.4"

        def add_event(self, **_):
            pass

    _ = db
    writer = SqlAlchemyAuditWriter(tracker=_TrackerWithIP())
    with caplog.at_level(logging.WARNING, logger="app.audit.adapters.repository"):
        writer.record(
            AuditEventCommand(action="y", resource_type="t", ip_address="10.0.0.99")
        )
    assert any("10.0.0.99" in m for m in caplog.messages)
    assert any("1.2.3.4" in m for m in caplog.messages)


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
async def test_statistics_consistency(db, writer, repository) -> None:
    # Seed a few rows. Exact comparisons across the shared test
    # database would be fragile (other tests can leave residue
    # depending on isolation), so this test only checks the
    # invariants that must hold regardless of preceding state.
    now = datetime.now(timezone.utc)
    writer.record(
        AuditEventCommand(
            action="stats_seed_recent",
            resource_type="server",
            user_id=1234,
        )
    )

    stats = await repository.get_statistics()

    # The seeded recent action must show up in the 24h bucket.
    assert stats.recent_logs_24h >= 1
    # Total is monotonic in seeded rows.
    assert stats.total_logs >= stats.recent_logs_24h
    # All "most_active_users_30d" entries are (user_id, positive count).
    for uid, count in stats.most_active_users_30d:
        assert uid is not None
        assert count > 0
    # `now` is unused here but documents the temporal anchor.
    _ = now
