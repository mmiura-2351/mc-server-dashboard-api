"""Unit tests for `BruteForceService` (Issue #73 Phase 1B).

The service touches SQLAlchemy directly, so this is a thin
'integration-style' unit test: we spin up an in-memory SQLite
engine, create the tables, and drive the service from there.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.application.brute_force_service import BruteForceService
from app.auth.models import AccountLockout, LoginAttempt  # noqa: F401 (table reg)
from app.core.config import settings
from app.core.database import Base


@pytest.fixture()
def session(monkeypatch):
    """Per-test in-memory DB with the brute-force tables created."""
    # Re-enable brute-force tracking for this fixture even though
    # conftest disabled it globally.
    monkeypatch.setattr(settings, "BRUTE_FORCE_ENABLED", True)
    monkeypatch.setattr(settings, "BRUTE_FORCE_USERNAME_THRESHOLD", 3)
    monkeypatch.setattr(settings, "BRUTE_FORCE_USERNAME_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "BRUTE_FORCE_LOCKOUT_BASE_SECONDS", 60)
    monkeypatch.setattr(settings, "BRUTE_FORCE_LOCKOUT_MAX_SECONDS", 3600)
    monkeypatch.setattr(settings, "BRUTE_FORCE_IP_THRESHOLD", 5)
    monkeypatch.setattr(settings, "BRUTE_FORCE_IP_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "BRUTE_FORCE_IP_LOCKOUT_SECONDS", 60)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestNoLockoutWhenDisabled:
    def test_check_lockout_short_circuits_when_disabled(self, monkeypatch, session):
        monkeypatch.setattr(settings, "BRUTE_FORCE_ENABLED", False)
        svc = BruteForceService(db=session)
        status = _run(svc.check_lockout("alice", "1.2.3.4"))
        assert status.locked is False

    def test_record_attempt_noop_when_disabled(self, monkeypatch, session):
        monkeypatch.setattr(settings, "BRUTE_FORCE_ENABLED", False)
        svc = BruteForceService(db=session)
        result = _run(svc.record_attempt("alice", "1.2.3.4", "ua", False, "x"))
        assert result is None


class TestUsernameLockout:
    def test_lockout_triggers_after_threshold(self, session):
        svc = BruteForceService(db=session)
        # 3 failures (threshold = 3) should trigger lockout.
        for _ in range(2):
            assert _run(svc.record_attempt("alice", "1.1.1.1", None, False, "x")) is None
        triggered = _run(svc.record_attempt("alice", "1.1.1.1", None, False, "x"))
        assert triggered is not None
        assert triggered.locked is True
        assert triggered.reason == "account_locked"
        # Lockout base is 60s for the first lockout.
        assert triggered.retry_after_seconds == 60

        status = _run(svc.check_lockout("alice", "1.1.1.1"))
        assert status.locked is True
        assert status.reason == "account_locked"

    def test_lockout_uses_exponential_backoff(self, session):
        svc = BruteForceService(db=session)
        # Manually pre-seed a count of 2; the next lockout should
        # be base * 2**(3-1) = 240s.
        row = AccountLockout(username="alice", lockout_count=2)
        session.add(row)
        session.flush()
        for _ in range(3):
            res = _run(svc.record_attempt("alice", "1.1.1.1", None, False, "x"))
        assert res is not None
        assert res.retry_after_seconds == 60 * (2**2)

    def test_successful_login_clears_lockout(self, session):
        svc = BruteForceService(db=session)
        for _ in range(3):
            _run(svc.record_attempt("alice", "1.1.1.1", None, False, "x"))
        # Now succeed.
        _run(svc.record_attempt("alice", "1.1.1.1", None, True))
        status = _run(svc.check_lockout("alice", "1.1.1.1"))
        assert status.locked is False
        row = (
            session.query(AccountLockout)
            .filter(AccountLockout.username == "alice")
            .first()
        )
        # Count is preserved so the next lockout escalates.
        assert row.lockout_count >= 1


class TestIpLockout:
    def test_ip_lockout_triggers_after_threshold(self, session):
        svc = BruteForceService(db=session)
        # IP threshold = 5; username threshold = 3 — vary the
        # username so we hit the IP path first.
        names = ["u1", "u2", "u3", "u4", "u5"]
        triggered = None
        for u in names:
            triggered = _run(svc.record_attempt(u, "9.9.9.9", None, False, "x"))
        assert triggered is not None
        assert triggered.locked is True
        assert triggered.reason == "ip_locked"

        status = _run(svc.check_lockout("nobody", "9.9.9.9"))
        assert status.locked is True
        assert status.reason == "ip_locked"


class TestRetryAfter:
    def test_check_lockout_returns_positive_retry_after(self, session):
        svc = BruteForceService(db=session)
        for _ in range(3):
            _run(svc.record_attempt("alice", "1.1.1.1", None, False, "x"))
        status = _run(svc.check_lockout("alice", "1.1.1.1"))
        assert status.locked is True
        assert status.retry_after_seconds > 0
