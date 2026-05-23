"""Domain-pure value objects for the users module.

Per `docs/ARCHITECTURE.md` §4.1, this module must not import from any
framework, database driver, or HTTP client. Only the Python standard
library is allowed.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Optional, Sequence


class Role(enum.Enum):
    admin = "admin"
    operator = "operator"
    user = "user"


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates the active policy.

    Multiple distinct policy violations are aggregated into ``reasons``
    so the caller can present them all at once (the message string is
    a `; `-joined summary suitable for logging).
    """

    def __init__(self, reasons: Sequence[str]):
        self.reasons: list[str] = list(reasons)
        super().__init__("; ".join(self.reasons) or "Password policy violation")


# Regex bits used by the complexity / sequence checks.
_LOWER_RE = re.compile(r"[a-z]")
_UPPER_RE = re.compile(r"[A-Z]")
_DIGIT_RE = re.compile(r"[0-9]")
# Anything that is not a letter or a digit and is not whitespace counts
# as a "symbol" for complexity purposes. Whitespace is permitted but
# does not contribute to the character-class count.
_SYMBOL_RE = re.compile(r"[^A-Za-z0-9\s]")

# Common reversible numeric/letter sequences screened during the
# repetition check. Listed lower-cased; comparisons are also done
# against the lower-cased password.
_SEQUENCES: tuple[str, ...] = (
    "0123456789",
    "abcdefghijklmnopqrstuvwxyz",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
)


@dataclass(frozen=True)
class PasswordPolicy:
    """Password-strength policy (OWASP ASVS v4 L1 + NIST 800-63B inspired).

    The policy is intentionally a pure value object so it can be unit-
    tested in isolation and overridden per environment (production vs
    testing) without touching application code.

    Defaults match the production posture documented in `docs/SECURITY.md`:

    * length:           12 – 128 characters
    * complexity:       at least 3 of {upper, lower, digit, symbol},
                        OR 16+ characters (long-passphrase escape hatch)
    * blocklist:        case-insensitive match against the
                        SecLists top-10k common-password list
    * cross-field:      reject passwords that contain the user's
                        username or the local-part of their e-mail
                        (case-insensitive, substring match)
    * repetition:       reject 4+ consecutive identical characters or
                        any 4+ character run of a known keyboard /
                        alphabet / numeric sequence (forward or reverse)
    """

    min_length: int = 12
    max_length: int = 128
    require_complexity: bool = True
    long_password_complexity_escape: int = 16
    # When True the candidate is checked against `common_passwords`.
    check_common_passwords: bool = True
    common_passwords: FrozenSet[str] = field(default_factory=frozenset)
    # When True the candidate is rejected if it contains the username
    # or e-mail local-part (case-insensitive substring match).
    forbid_user_info: bool = True
    # When True, 4+ consecutive identical characters or 4+ run of a
    # known sequence trips a rejection.
    forbid_simple_patterns: bool = True

    # ----- Public API -----

    def validate(
        self,
        password: str,
        *,
        username: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        """Raise `PasswordPolicyError` iff *password* violates the policy.

        ``username`` / ``email`` are optional; when supplied they are
        used for the cross-field check (see `forbid_user_info`).
        """
        reasons = list(self._iter_violations(password, username=username, email=email))
        if reasons:
            raise PasswordPolicyError(reasons)

    def is_valid(
        self,
        password: str,
        *,
        username: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """Convenience predicate; returns ``False`` on any violation."""
        try:
            self.validate(password, username=username, email=email)
        except PasswordPolicyError:
            return False
        return True

    # ----- Internal helpers -----

    def _iter_violations(
        self,
        password: str,
        *,
        username: Optional[str],
        email: Optional[str],
    ) -> Iterable[str]:
        if not isinstance(password, str) or not password:
            yield "Password must be a non-empty string"
            return

        n = len(password)
        if n < self.min_length:
            yield (
                f"Password must be at least {self.min_length} characters long (got {n})"
            )
        if n > self.max_length:
            yield (
                f"Password must be at most {self.max_length} characters long (got {n})"
            )

        if self.require_complexity and n < self.long_password_complexity_escape:
            classes = self._character_classes(password)
            if classes < 3:
                yield (
                    "Password must contain characters from at least 3 of"
                    " {uppercase, lowercase, digit, symbol}"
                    f" (or be {self.long_password_complexity_escape}+ characters long)"
                )

        if self.check_common_passwords and self.common_passwords:
            if password.lower() in self.common_passwords:
                yield "Password is too common and easily guessable"

        if self.forbid_user_info:
            forbidden = self._forbidden_substrings(username=username, email=email)
            lowered = password.lower()
            for needle in forbidden:
                if needle and needle in lowered:
                    yield "Password must not contain your username or e-mail"
                    break

        if self.forbid_simple_patterns and _has_simple_pattern(password):
            yield (
                "Password must not contain long runs of repeated characters"
                " or simple sequences (e.g. 'aaaa', '1234', 'abcd')"
            )

    @staticmethod
    def _character_classes(password: str) -> int:
        return sum(
            1
            for regex in (_LOWER_RE, _UPPER_RE, _DIGIT_RE, _SYMBOL_RE)
            if regex.search(password) is not None
        )

    @staticmethod
    def _forbidden_substrings(
        *, username: Optional[str], email: Optional[str]
    ) -> tuple[str, ...]:
        bits: list[str] = []
        if username:
            u = username.strip().lower()
            if len(u) >= 3:
                bits.append(u)
        if email:
            local = email.strip().split("@", 1)[0].lower()
            if len(local) >= 3:
                bits.append(local)
        return tuple(bits)


def _has_simple_pattern(password: str) -> bool:
    """Detect trivially-weak patterns: 4+ repeats or 4+ sequence runs."""
    if re.search(r"(.)\1{3,}", password):
        return True
    lowered = password.lower()
    for seq in _SEQUENCES:
        rev = seq[::-1]
        for window in range(4, min(len(seq), len(lowered)) + 1):
            for i in range(len(seq) - window + 1):
                if seq[i : i + window] in lowered:
                    return True
                if rev[i : i + window] in lowered:
                    return True
            # No need to scan larger windows once the smallest run
            # was checked above — but break the inner loop sentinel
            # for clarity:
        # continue to the next sequence
    return False
