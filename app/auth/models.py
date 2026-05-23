"""SQLAlchemy ORM models for brute-force tracking (Issue #73).

Two tables back the `BruteForceService`:

* ``login_attempts`` — append-only audit of every authentication
  attempt (success or failure), used to compute sliding-window
  failure counts. Lookups are indexed by username, IP, and time.
* ``account_lockouts`` — at-most-one row per username; tracks the
  active lockout (``locked_until``) and the historic lockout count
  (used to derive exponential back-off durations).

These tables intentionally live in the auth domain even though
``RefreshToken`` historically resides under ``app.users.models``
— that placement is grandfathered for backwards compatibility.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class LoginAttempt(Base):
    """Append-only record of an authentication attempt."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    # Username supplied on the form (may not correspond to a real
    # user — we still track it so attackers cannot probe by
    # enumerating). Length matches `users.username` (50).
    username = Column(String(50), index=True, nullable=False)
    # IPv6 max 45 chars (`ffff:ffff:...::255.255.255.255`).
    ip_address = Column(String(45), index=True, nullable=True)
    user_agent = Column(Text, nullable=True)
    attempted_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    success = Column(Boolean, default=False, nullable=False)
    # Short, machine-readable reason for failure (e.g.
    # "invalid_credentials", "account_locked", "unapproved").
    # NULL on successful attempts.
    failure_reason = Column(String(64), nullable=True)


class AccountLockout(Base):
    """Per-username lockout state.

    Up to one row per ``username``. ``locked_until`` is in the future
    while a lockout is active. ``lockout_count`` accumulates across
    rotations and drives exponential back-off in the service layer.
    """

    __tablename__ = "account_lockouts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    lockout_count = Column(Integer, default=0, nullable=False)
    last_locked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["LoginAttempt", "AccountLockout"]
