"""Shared test helpers (Issue #168).

Centralizes fixtures and helpers that were previously duplicated across
multiple test files: authentication header construction, password
hashing context, user / server factory functions, and re-exports of
domain-port fakes.

Modules in this package may import from `app.*`. Because the root
`tests/conftest.py` sets `DATABASE_URL` BEFORE any `app.*` import (see
Issue #210), nothing in this package may be imported from the root
conftest at module-level. Import lazily inside fixtures instead.
"""
