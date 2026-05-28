"""Domain-pure value objects for the groups module.

Per `docs/app/ARCHITECTURE.md` Section 4.1, this module must not import from any
framework, database driver, or HTTP client. Only the Python standard
library is allowed.
"""

import enum


class GroupType(enum.Enum):
    op = "op"
    whitelist = "whitelist"


__all__ = ["GroupType"]
