"""Unit coverage for the Issue #237 token-version invalidation path.

These tests exercise the central ``_authenticate`` helper directly so
we don't have to spin up a TestClient just to assert that a forged or
revoked ``tv`` claim raises 401. Integration coverage for the full
HTTP flow lives in ``tests/integration/auth/test_router.py``.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.auth.auth import create_access_token
from app.auth.dependencies import _authenticate


class TestTokenVersionAuthentication:
    def test_matching_tv_authenticates(self, db, test_user):
        """A token whose ``tv`` matches ``user.token_version`` is accepted."""
        token = create_access_token(
            data={"sub": test_user.username, "tv": test_user.token_version}
        )
        user = _authenticate(token, db)
        assert user.id == test_user.id

    def test_legacy_token_without_tv_treated_as_zero(self, db, test_user):
        """Tokens minted before Issue #237 (no ``tv`` claim) keep working.

        ``payload.get("tv", 0)`` defaults to 0, which matches the
        ``token_version=0`` default on freshly created users — so the
        rollout does not invalidate already-issued sessions.
        """
        token = create_access_token(data={"sub": test_user.username})
        user = _authenticate(token, db)
        assert user.id == test_user.id

    def test_tv_mismatch_raises_401(self, db, test_user):
        """A token whose ``tv`` is stale (revoked) is rejected."""
        # Mint with the current tv, then bump the user's tv to simulate
        # a deactivation / password rotation happening after the token
        # was issued.
        token = create_access_token(
            data={"sub": test_user.username, "tv": test_user.token_version}
        )
        test_user.token_version = (test_user.token_version or 0) + 1
        db.commit()

        with pytest.raises(HTTPException) as excinfo:
            _authenticate(token, db)
        assert excinfo.value.status_code == 401

    def test_tv_mismatch_emits_audit_event(self, db, test_user):
        """The ``tv`` mismatch path emits a security audit event."""
        token = create_access_token(
            data={"sub": test_user.username, "tv": test_user.token_version}
        )
        test_user.token_version = (test_user.token_version or 0) + 1
        db.commit()

        with patch(
            "app.audit.application.legacy_facade.AuditService.log_security_event"
        ) as mock_log:
            from starlette.requests import Request

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/users/me",
                "headers": [(b"user-agent", b"pytest")],
                "query_string": b"",
                "client": ("127.0.0.1", 0),
                "server": ("testserver", 80),
                "scheme": "http",
                "root_path": "",
            }
            request = Request(scope)
            with pytest.raises(HTTPException):
                _authenticate(token, db, request=request)

        assert mock_log.called
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["event_type"] == "token_revoked_post_deactivation"
        assert call_kwargs["severity"] == "warning"

    def test_inactive_user_rejected_even_with_matching_tv(self, db, test_user):
        """Defense-in-depth: ``is_active=False`` blocks auth regardless of tv."""
        token = create_access_token(
            data={"sub": test_user.username, "tv": test_user.token_version}
        )
        test_user.is_active = False
        db.commit()

        with pytest.raises(HTTPException) as excinfo:
            _authenticate(token, db)
        assert excinfo.value.status_code == 401

    def test_unknown_user_rejected(self, db):
        """A token for a sub that no longer exists raises 401."""
        token = create_access_token(data={"sub": "ghost_user", "tv": 0})
        with pytest.raises(HTTPException) as excinfo:
            _authenticate(token, db)
        assert excinfo.value.status_code == 401

    def test_malformed_token_rejected(self, db):
        """A JWT with an invalid signature raises 401."""
        with pytest.raises(HTTPException) as excinfo:
            _authenticate("not-a-real-token", db)
        assert excinfo.value.status_code == 401

    def test_expired_token_rejected(self, db, test_user):
        """An expired token raises 401."""
        token = create_access_token(
            data={"sub": test_user.username, "tv": test_user.token_version},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(HTTPException) as excinfo:
            _authenticate(token, db)
        assert excinfo.value.status_code == 401
