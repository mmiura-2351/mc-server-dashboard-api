"""Static resources for the users domain.

Currently exposes the common-passwords blocklist (`common_passwords.txt`)
as a lazily-loaded `frozenset[str]`. The set is built once per process
on first access and then cached via `functools.lru_cache`.

The resource file format is plain text, one password per line. Lines
beginning with `#` are treated as comments and skipped. Comparisons
performed against the resulting set are case-insensitive (all entries
are lower-cased on load).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import FrozenSet

_RESOURCE_DIR = Path(__file__).resolve().parent
_COMMON_PASSWORDS_FILE = _RESOURCE_DIR / "common_passwords.txt"


@functools.lru_cache(maxsize=1)
def load_common_passwords() -> FrozenSet[str]:
    """Return the common-passwords blocklist as a `frozenset[str]`.

    The result is cached for the lifetime of the process. The file is
    UTF-8 encoded; comment lines (`# ...`) and blank lines are skipped;
    entries are lower-cased to enable case-insensitive look-ups.
    """
    try:
        raw = _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Fail-open with an empty set so missing resources do not crash
        # the application at startup. Validators will still enforce
        # length / complexity / cross-field checks.
        return frozenset()

    entries: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped.lower())
    return frozenset(entries)


__all__ = ["load_common_passwords"]
