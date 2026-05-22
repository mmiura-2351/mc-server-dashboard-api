"""Authentication header helpers for test fixtures (Issue #168).

Previously, four integration test files each defined their own
identical `get_auth_headers(username)`. This module consolidates the
implementation. Use `auth_headers_for(username)` for new tests; the old
name is kept as `get_auth_headers` for drop-in replacement.
"""

from typing import Dict

from app.auth.auth import create_access_token


def auth_headers_for(username: str) -> Dict[str, str]:
    """Return an Authorization header for `username` (JWT directly minted).

    Bypasses the `/api/v1/auth/token` endpoint, which keeps fixtures
    fast and decouples them from the auth router. Login-path coverage
    lives in dedicated auth router tests.
    """
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


# Backwards-compatible alias for drop-in replacement of the historical
# per-file `get_auth_headers(username)` helpers.
get_auth_headers = auth_headers_for


__all__ = ["auth_headers_for", "get_auth_headers"]
