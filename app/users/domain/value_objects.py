"""Domain-pure value objects for the users module.

Per `docs/ARCHITECTURE.md` §4.1, this module must not import from any
framework, database driver, or HTTP client. Only the Python standard
library is allowed.
"""

import enum


class Role(enum.Enum):
    admin = "admin"
    operator = "operator"
    user = "user"
