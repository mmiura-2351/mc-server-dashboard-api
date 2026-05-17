"""Backward-compat shim for the versions repository.

The canonical Port lives in `app.versions.domain.ports.VersionRepository`
and the SQLAlchemy implementation lives in
`app.versions.adapters.repository.SqlAlchemyVersionRepository`.

`VersionRepository` here is **the legacy concrete-class alias** kept for
historical imports in `app/servers/...` and the version test suite. It is
*not* the Port — re-exporting under the same name as the Protocol used to
cause "imported the Protocol, got a SqlAlchemy class" confusion. The new
name is `LegacyVersionRepository`; `VersionRepository` is retained as a
deprecated alias and triggers a `DeprecationWarning` on access. Remove
once consumers migrate to `app.versions.api.dependencies`.
"""

import warnings

from app.versions.adapters.repository import (
    SqlAlchemyVersionRepository as LegacyVersionRepository,
)


def __getattr__(name: str):
    if name == "VersionRepository":
        warnings.warn(
            "Importing `VersionRepository` from `app.versions.repository` is "
            "deprecated. Use `app.versions.adapters.repository.SqlAlchemyVersionRepository` "
            "for the concrete adapter or `app.versions.domain.ports.VersionRepository` "
            "for the Protocol.",
            DeprecationWarning,
            stacklevel=2,
        )
        return LegacyVersionRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LegacyVersionRepository"]
