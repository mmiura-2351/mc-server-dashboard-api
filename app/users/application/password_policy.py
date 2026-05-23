"""Factory for the active `PasswordPolicy` value object.

Bridges the framework-pure `PasswordPolicy` (domain layer) with the
runtime configuration (`app.core.config.settings`) and the resource
loader (`app.users.resources.load_common_passwords`).

Kept in the application layer because the domain layer is forbidden
from importing settings or resources directly.
"""

from __future__ import annotations

import functools

from app.core.config import settings
from app.users.domain.value_objects import PasswordPolicy
from app.users.resources import load_common_passwords


@functools.lru_cache(maxsize=1)
def get_password_policy() -> PasswordPolicy:
    """Return the singleton `PasswordPolicy` built from the active settings.

    The result is cached for the lifetime of the process; tests that
    need to vary policy parameters should override the relevant
    settings *before* this is first called, or call
    `reset_password_policy_cache()` afterwards.
    """
    check_common = settings.PASSWORD_CHECK_COMMON_LIST
    common = load_common_passwords() if check_common else frozenset()
    return PasswordPolicy(
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_length=settings.PASSWORD_MAX_LENGTH,
        require_complexity=settings.PASSWORD_REQUIRE_COMPLEXITY,
        check_common_passwords=check_common,
        common_passwords=common,
        forbid_user_info=settings.PASSWORD_FORBID_USER_INFO,
        forbid_simple_patterns=settings.PASSWORD_FORBID_SIMPLE_PATTERNS,
    )


def reset_password_policy_cache() -> None:
    """Clear the cached policy so the next call re-reads settings.

    Intended for tests that mutate the configuration.
    """
    get_password_policy.cache_clear()


__all__ = ["get_password_policy", "reset_password_policy_cache"]
