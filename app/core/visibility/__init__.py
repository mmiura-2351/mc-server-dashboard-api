"""Resource visibility package (hex layout introduced in #228 PR 2f).

The SQLAlchemy ORM (`ResourceVisibility`, `ResourceUserAccess`) and the
public enums (`VisibilityType`, `ResourceType`) remain importable from
this top-level path for backwards compatibility with the rest of the
codebase (`from app.core.visibility import ...`). New code in the
domain / application layers should import the domain entities from
`app.core.visibility.domain.entities` instead.
"""

from app.core.visibility.models import (
    ResourceType,
    ResourceUserAccess,
    ResourceVisibility,
    VisibilityType,
)

__all__ = [
    "ResourceType",
    "ResourceUserAccess",
    "ResourceVisibility",
    "VisibilityType",
]
