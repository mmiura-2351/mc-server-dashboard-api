"""Integration tests for brute-force protection on `POST /api/v1/auth/token`.

The base conftest disables brute-force tracking globally; this module
re-enables it for the duration of each test via direct setting
mutation.
"""

from __future__ import annotations

import pytest

from app.auth.models import AccountLockout, LoginAttempt
from app.core.config import settings


@pytest.fixture()
def enable_brute_force(monkeypatch):
    monkeypatch.setattr(settings, "BRUTE_FORCE_ENABLED", True)
    monkeypatch.setattr(settings, "BRUTE_FORCE_USERNAME_THRESHOLD", 3)
    monkeypatch.setattr(settings, "BRUTE_FORCE_USERNAME_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "BRUTE_FORCE_LOCKOUT_BASE_SECONDS", 1)
    monkeypatch.setattr(settings, "BRUTE_FORCE_LOCKOUT_MAX_SECONDS", 60)
    monkeypatch.setattr(settings, "BRUTE_FORCE_IP_THRESHOLD", 100)
    monkeypatch.setattr(settings, "BRUTE_FORCE_DELAY_MS", 0)
    yield


class TestBruteForceLockout:
    def test_failures_below_threshold_return_401(
        self, client, test_user, enable_brute_force, db
    ):
        for _ in range(2):
            r = client.post(
                "/api/v1/auth/token",
                data={"username": "testuser", "password": "wrongpw!"},
            )
            assert r.status_code == 401

    def test_threshold_failures_trigger_429(
        self, client, test_user, enable_brute_force, db
    ):
        # Three failures (threshold = 3) — the *third* one should
        # be the lockout trigger, recorded as 401 (the attempt is
        # processed before lockout is asserted). The fourth attempt
        # hits the lockout pre-flight and returns 429.
        for _ in range(3):
            client.post(
                "/api/v1/auth/token",
                data={"username": "testuser", "password": "wrongpw!"},
            )
        r = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "wrongpw!"},
        )
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        assert int(r.headers["Retry-After"]) >= 1

        # Lockout row should exist.
        rows = (
            db.query(AccountLockout).filter(AccountLockout.username == "testuser").all()
        )
        assert len(rows) == 1
        assert rows[0].lockout_count >= 1

    def test_successful_login_clears_lockout_state(
        self, client, test_user, enable_brute_force, db
    ):
        # 2 failures (below threshold) followed by a success.
        for _ in range(2):
            client.post(
                "/api/v1/auth/token",
                data={"username": "testuser", "password": "wrongpw!"},
            )
        r = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpassword"},
        )
        assert r.status_code == 200
        # An attempt row was written.
        attempts = (
            db.query(LoginAttempt).filter(LoginAttempt.username == "testuser").all()
        )
        assert any(a.success for a in attempts)

    def test_disabled_brute_force_skips_lockout(self, client, test_user, monkeypatch):
        monkeypatch.setattr(settings, "BRUTE_FORCE_ENABLED", False)
        # 10 failures — none should ever produce a 429.
        for _ in range(10):
            r = client.post(
                "/api/v1/auth/token",
                data={"username": "testuser", "password": "wrongpw!"},
            )
            assert r.status_code == 401


class TestPendingApprovalNotLockedOut:
    """PR #333 review (Blocker 2). Pending-approval users hit the
    ``authentication_error`` path because ``authenticate_user`` raises
    HTTP 403 rather than the canonical 401. Those attempts must NOT
    advance the lockout counter — otherwise a legitimate user trying
    their own real password would be locked out at the threshold.
    """

    def test_pending_user_real_password_does_not_trigger_429(
        self, client, unapproved_user, enable_brute_force, db
    ):
        # Username threshold from `enable_brute_force` is 3.
        # 10 consecutive attempts with the REAL password — must NEVER
        # return 429 (only 403 from the pending-approval guard).
        for _ in range(10):
            r = client.post(
                "/api/v1/auth/token",
                data={"username": "unapproved", "password": "unapprovedpassword"},
            )
            assert r.status_code == 403, (
                f"expected 403 from pending-approval guard, got {r.status_code}: {r.text}"
            )

        # Audit rows ARE present (with failure_reason=authentication_error)
        # but the lockout row must NOT exist.
        audit_rows = (
            db.query(LoginAttempt).filter(LoginAttempt.username == "unapproved").all()
        )
        assert len(audit_rows) == 10
        assert all(a.failure_reason == "authentication_error" for a in audit_rows)
        lockout = (
            db.query(AccountLockout)
            .filter(AccountLockout.username == "unapproved")
            .first()
        )
        assert lockout is None or lockout.locked_until is None
