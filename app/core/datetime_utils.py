"""Datetime helpers.

`utcnow()` returns a naive datetime representing the current UTC wall time
(the same semantics as the deprecated `datetime.datetime.utcnow()`). It exists
so the codebase can avoid the deprecated call without changing storage or
comparison semantics — DB columns are declared as `DateTime` (not
`DateTime(timezone=True)`), so values written by this helper round-trip as
naive datetimes just as `datetime.utcnow()` did.

New code that does not interact with naive DB rows should prefer
`datetime.now(timezone.utc)` (timezone-aware UTC) directly.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
