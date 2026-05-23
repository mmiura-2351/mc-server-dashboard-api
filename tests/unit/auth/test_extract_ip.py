"""Unit tests for `_extract_ip` (PR #333 review, Blocker 1).

The function MUST NOT trust ``X-Forwarded-For`` / ``X-Real-IP``
unless ``TRUST_PROXY_HEADERS`` is enabled AND the immediate peer is
in ``TRUSTED_PROXIES``. Otherwise an attacker could spoof any IP
via the header and bypass per-IP brute-force lockout.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.auth.api.router import _extract_ip
from app.core.config import settings


def _make_request(*, client_host: str | None, headers: dict[str, str]):
    """Build a minimal stand-in for `starlette.Request` for `_extract_ip`.

    The real ``Request.headers`` is a case-insensitive mapping; a
    plain dict works for the keys we use as long as we look them up
    with the same casing the function uses.
    """
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host) if client_host else None,
        headers=headers,
    )


class TestProxyTrustDisabledByDefault:
    def test_xff_is_ignored_when_trust_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.1")
        req = _make_request(
            client_host="203.0.113.5",
            headers={"X-Forwarded-For": "1.2.3.4, 9.9.9.9"},
        )
        assert _extract_ip(req) == "203.0.113.5"

    def test_x_real_ip_is_ignored_when_trust_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
        req = _make_request(
            client_host="203.0.113.5",
            headers={"X-Real-IP": "1.2.3.4"},
        )
        assert _extract_ip(req) == "203.0.113.5"

    def test_no_client_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
        req = _make_request(client_host=None, headers={})
        assert _extract_ip(req) is None


class TestProxyTrustEnabledRequiresTrustedPeer:
    def test_xff_trusted_when_peer_is_trusted_proxy(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.1,127.0.0.1")
        req = _make_request(
            client_host="10.0.0.1",
            headers={"X-Forwarded-For": "1.2.3.4, 9.9.9.9"},
        )
        assert _extract_ip(req) == "1.2.3.4"

    def test_xff_rejected_when_peer_not_trusted(self, monkeypatch):
        """An attacker hitting the API directly cannot spoof IP."""
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.1")
        req = _make_request(
            client_host="203.0.113.5",  # NOT in TRUSTED_PROXIES
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        # Must fall back to the real peer, not the spoofed XFF value.
        assert _extract_ip(req) == "203.0.113.5"

    def test_real_ip_fallback_when_xff_absent(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.1")
        req = _make_request(
            client_host="10.0.0.1",
            headers={"X-Real-IP": "1.2.3.4"},
        )
        assert _extract_ip(req) == "1.2.3.4"

    def test_empty_trusted_proxies_means_no_trust(self, monkeypatch):
        """Safe-by-default even when TRUST_PROXY_HEADERS=true."""
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "")
        req = _make_request(
            client_host="10.0.0.1",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert _extract_ip(req) == "10.0.0.1"

    def test_xff_left_most_entry_is_picked(self, monkeypatch):
        """Multi-hop XFF returns the original client (leftmost)."""
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.1")
        req = _make_request(
            client_host="10.0.0.1",
            headers={"X-Forwarded-For": "  1.2.3.4 , 5.6.7.8 , 10.0.0.1 "},
        )
        assert _extract_ip(req) == "1.2.3.4"


class TestTrustedProxiesListParse:
    """Pure config helper covering whitespace handling."""

    def test_list_strips_whitespace_and_skips_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "  10.0.0.1 ,, 127.0.0.1 ,")
        assert settings.trusted_proxies_list == ["10.0.0.1", "127.0.0.1"]

    def test_list_empty_when_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", "")
        assert settings.trusted_proxies_list == []
