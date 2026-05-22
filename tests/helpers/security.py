"""Shared bcrypt context for test fixtures (Issue #168).

Tests use `bcrypt__rounds=4` to keep hashing fast in CI. Centralizing
the `CryptContext` instance prevents accidental regressions to the
production default (rounds=12), which was previously possible in any
test file that constructed its own `CryptContext`.
"""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)

__all__ = ["pwd_context"]
