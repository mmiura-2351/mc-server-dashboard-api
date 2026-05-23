"""Brute-force protection (Issue #73 Phase 1B).

Tracks failed authentication attempts in a sliding window and locks
the *username* or the *source IP* once a configurable threshold is
exceeded. Lockout durations grow exponentially up to a configurable
cap (NIST 800-63B §5.2.2 recommends exponential back-off rather than
a hard cap).

Persistence lives in ``app.auth.models`` (``login_attempts`` and
``account_lockouts``); the service does *not* go through the
auth-domain UnitOfWork because brute-force counters are an orthogonal
cross-cutting concern that should remain queryable even if the rest
of the auth transaction rolls back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import AccountLockout, LoginAttempt
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LockoutStatus:
    """Result of `BruteForceService.check_lockout`.

    * ``locked``                — True when either the username or
                                  source IP is currently locked.
    * ``retry_after_seconds``  — Seconds until the soonest lockout
                                  expires (0 when not locked).
    * ``reason``               — Machine-readable code for logging
                                  / metrics ("", "account_locked",
                                  "ip_locked").
    """

    locked: bool
    retry_after_seconds: int
    reason: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Return *dt* with UTC tzinfo (SQLite drops tz on round-trip)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class BruteForceService:
    """Sliding-window brute-force tracker with exponential lockout."""

    def __init__(self, db: Session):
        self._db = db

    # ----- Public API -----

    async def check_lockout(
        self, username: str, ip_address: Optional[str]
    ) -> LockoutStatus:
        """Return the current lockout status for *username* / *ip_address*.

        When brute-force protection is disabled (``BRUTE_FORCE_ENABLED``)
        this always returns ``LockoutStatus(locked=False, …)``.
        """
        if not settings.BRUTE_FORCE_ENABLED:
            return LockoutStatus(locked=False, retry_after_seconds=0)

        now = _now()
        # ----- Username-based lockout -----
        retry_username = 0
        if username:
            row = (
                self._db.query(AccountLockout)
                .filter(AccountLockout.username == username)
                .first()
            )
            if row is not None and row.locked_until is not None:
                locked_until = _aware(row.locked_until)
                if locked_until and locked_until > now:
                    retry_username = int((locked_until - now).total_seconds()) + 1

        # ----- IP-based lockout -----
        retry_ip = 0
        if ip_address:
            recent_ip_failures = self._count_failures(
                ip_address=ip_address,
                since=now - timedelta(seconds=settings.BRUTE_FORCE_IP_WINDOW_SECONDS),
            )
            if recent_ip_failures >= settings.BRUTE_FORCE_IP_THRESHOLD:
                retry_ip = settings.BRUTE_FORCE_IP_LOCKOUT_SECONDS

        if retry_username and retry_ip:
            return LockoutStatus(
                locked=True,
                retry_after_seconds=max(retry_username, retry_ip),
                reason="account_locked",
            )
        if retry_username:
            return LockoutStatus(
                locked=True,
                retry_after_seconds=retry_username,
                reason="account_locked",
            )
        if retry_ip:
            return LockoutStatus(
                locked=True,
                retry_after_seconds=retry_ip,
                reason="ip_locked",
            )
        return LockoutStatus(locked=False, retry_after_seconds=0)

    async def record_attempt(
        self,
        username: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        success: bool,
        failure_reason: Optional[str] = None,
    ) -> Optional[LockoutStatus]:
        """Record an authentication attempt and update lockout state.

        Returns a fresh ``LockoutStatus`` iff this attempt *triggered*
        a new lockout (caller can audit / surface a security event).
        Returns ``None`` otherwise.
        """
        if not settings.BRUTE_FORCE_ENABLED:
            return None

        attempt = LoginAttempt(
            username=username or "",
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            failure_reason=failure_reason,
        )
        self._db.add(attempt)

        triggered: Optional[LockoutStatus] = None
        if success:
            # Successful login clears any existing username lockout
            # — the user has just proven knowledge of the credential.
            if username:
                row = (
                    self._db.query(AccountLockout)
                    .filter(AccountLockout.username == username)
                    .first()
                )
                if row is not None:
                    row.locked_until = None
                    # Keep `lockout_count` so repeated abuse still
                    # escalates the back-off on the next failure.
        else:
            triggered = self._maybe_lock_username(username)
            if triggered is None:
                triggered = self._maybe_check_ip(ip_address)

        # The caller is responsible for committing the surrounding
        # session; flushing here is enough for downstream queries
        # within the same request.
        self._db.flush()
        return triggered

    # ----- Internal helpers -----

    def _count_failures(
        self,
        *,
        since: datetime,
        username: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> int:
        q = self._db.query(func.count(LoginAttempt.id)).filter(
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= since,
        )
        if username is not None:
            q = q.filter(LoginAttempt.username == username)
        if ip_address is not None:
            q = q.filter(LoginAttempt.ip_address == ip_address)
        return int(q.scalar() or 0)

    def _maybe_lock_username(self, username: str) -> Optional[LockoutStatus]:
        if not username:
            return None
        now = _now()
        window_start = now - timedelta(
            seconds=settings.BRUTE_FORCE_USERNAME_WINDOW_SECONDS
        )
        # Include the current attempt (just added but not yet flushed
        # — count via the buffered session).
        self._db.flush()
        failures = self._count_failures(username=username, since=window_start)
        if failures < settings.BRUTE_FORCE_USERNAME_THRESHOLD:
            return None

        row = (
            self._db.query(AccountLockout)
            .filter(AccountLockout.username == username)
            .first()
        )
        if row is None:
            row = AccountLockout(username=username, lockout_count=0)
            self._db.add(row)

        # Treat a still-active lockout as a no-op (we shouldn't even
        # be here in normal flow because `check_lockout` would have
        # short-circuited the request).
        existing_until = _aware(row.locked_until)
        if existing_until is not None and existing_until > now:
            return None

        next_count = (row.lockout_count or 0) + 1
        duration = self._lockout_duration(next_count)
        row.lockout_count = next_count
        row.last_locked_at = now
        row.locked_until = now + timedelta(seconds=duration)

        logger.warning(
            "brute_force.account_locked username=%s for=%ss count=%s",
            username,
            duration,
            next_count,
        )
        return LockoutStatus(
            locked=True,
            retry_after_seconds=duration,
            reason="account_locked",
        )

    def _maybe_check_ip(self, ip_address: Optional[str]) -> Optional[LockoutStatus]:
        if not ip_address:
            return None
        now = _now()
        window_start = now - timedelta(seconds=settings.BRUTE_FORCE_IP_WINDOW_SECONDS)
        self._db.flush()
        failures = self._count_failures(ip_address=ip_address, since=window_start)
        if failures < settings.BRUTE_FORCE_IP_THRESHOLD:
            return None
        # IP lockout is implicit — driven by the sliding-window count
        # rather than a row in `account_lockouts` (it would be unsafe
        # to durably commit per-IP entries because the table key is
        # the username). We surface the event so the caller can audit
        # the first crossing of the threshold.
        logger.warning(
            "brute_force.ip_blocked ip=%s window_failures=%s", ip_address, failures
        )
        return LockoutStatus(
            locked=True,
            retry_after_seconds=settings.BRUTE_FORCE_IP_LOCKOUT_SECONDS,
            reason="ip_locked",
        )

    @staticmethod
    def _lockout_duration(lockout_count: int) -> int:
        """Exponential back-off: base * 2**(n-1), capped at the max."""
        base = settings.BRUTE_FORCE_LOCKOUT_BASE_SECONDS
        cap = settings.BRUTE_FORCE_LOCKOUT_MAX_SECONDS
        # Use a safe ceiling on the exponent so very large counts
        # do not overflow.
        exponent = min(max(lockout_count - 1, 0), 16)
        return min(cap, base * (2**exponent))


__all__ = ["BruteForceService", "LockoutStatus"]
