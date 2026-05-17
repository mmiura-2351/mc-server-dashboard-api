"""Backward-compat shim for the versions repository.

The canonical Port lives in `app.versions.domain.ports.VersionRepository`
and the SQLAlchemy implementation lives in
`app.versions.adapters.repository.SqlAlchemyVersionRepository`.

This shim re-exports `SqlAlchemyVersionRepository` under the historical
name `VersionRepository` so that existing imports keep working while
consumers migrate. To be removed in a follow-up sub-issue.
"""

from app.versions.adapters.repository import SqlAlchemyVersionRepository

VersionRepository = SqlAlchemyVersionRepository

__all__ = ["VersionRepository", "SqlAlchemyVersionRepository"]
