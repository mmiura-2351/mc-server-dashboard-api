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

    def test_ip_retry_after_is_bounded_by_window(self, session):
        """PR #333 review (Blocker 3): IP retry_after must be the
        residual lifetime of the sliding window — never larger than
        the configured `BRUTE_FORCE_IP_WINDOW_SECONDS`.
        """
        svc = BruteForceService(db=session)
        for u in ["u1", "u2", "u3", "u4", "u5"]:
            _run(svc.record_attempt(u, "9.9.9.9", None, False, "x"))
        status = _run(svc.check_lockout("nobody", "9.9.9.9"))
        assert status.locked is True
        assert status.reason == "ip_locked"
        # Window is 60s; retry_after must be within (0, 60].
        assert 0 < status.retry_after_seconds <= settings.BRUTE_FORCE_IP_WINDOW_SECONDS


class TestAuthenticationErrorExcludedFromCount:
    """PR #333 review (Blocker 2): rows recorded with
    `failure_reason="authentication_error"` are audit-only and must
    NOT advance the lockout counter — otherwise a legitimate pending-
    approval user hitting their own real password 5 times would lock
    themselves out even though the intent is "do not punish".
    """

    def test_authentication_error_rows_do_not_trigger_lockout(self, session):
        svc = BruteForceService(db=session)
        # 10 attempts with audit-only reason: must NEVER trigger.
        for _ in range(10):
            result = _run(
                svc.record_attempt(
                    "pending_user",
                    "1.1.1.1",
                    None,
                    False,
                    failure_reason="authentication_error",
                )
            )
            assert result is None
        status = _run(svc.check_lockout("pending_user", "1.1.1.1"))
        assert status.locked is False

    def test_invalid_credentials_still_triggers_lockout(self, session):
        """Sanity check: normal invalid_credentials path is unaffected."""
        svc = BruteForceService(db=session)
        for _ in range(2):
            assert (
                _run(
                    svc.record_attempt(
                        "alice", "2.2.2.2", None, False, "invalid_credentials"
                    )
                )
                is None
            )
        triggered = _run(
            svc.record_attempt("alice", "2.2.2.2", None, False, "invalid_credentials")
        )
        assert triggered is not None
        assert triggered.locked is True

    def test_mixed_rows_only_count_non_audit(self, session):
        """Auditing rows must coexist with real failures without inflating
        the counter past the threshold.
        """
        svc = BruteForceService(db=session)
        # 4 audit-only rows: still under threshold.
        for _ in range(4):
            _run(
                svc.record_attempt("bob", "3.3.3.3", None, False, "authentication_error")
            )
        assert _run(svc.check_lockout("bob", "3.3.3.3")).locked is False
        # 2 real failures: still under threshold of 3.
        for _ in range(2):
            assert (
                _run(
                    svc.record_attempt(
                        "bob", "3.3.3.3", None, False, "invalid_credentials"
                    )
                )
                is None
            )
        # 3rd real failure crosses the threshold (audit rows do NOT
        # inflate the count).
        triggered = _run(
            svc.record_attempt("bob", "3.3.3.3", None, False, "invalid_credentials")
        )
        assert triggered is not None
        assert triggered.locked is True
        assert triggered.reason == "account_locked"
