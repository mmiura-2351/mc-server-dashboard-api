"""Unit tests for the `PasswordPolicy` value object (Issue #73)."""

from __future__ import annotations

import pytest

from app.users.domain.value_objects import PasswordPolicy, PasswordPolicyError

STRONG_PASSWORD = "Snowy-River-Pebbles-9!"
USERNAME = "alice"
EMAIL = "alice@example.com"


def _policy(**overrides) -> PasswordPolicy:
    defaults = dict(
        min_length=12,
        max_length=128,
        require_complexity=True,
        check_common_passwords=True,
        common_passwords=frozenset({"password", "qwerty123!a", "letmein2024"}),
        forbid_user_info=True,
        forbid_simple_patterns=True,
    )
    defaults.update(overrides)
    return PasswordPolicy(**defaults)


class TestLength:
    def test_too_short_rejected(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy().validate("Aa1!" * 2)  # 8 chars
        assert any("at least 12" in r for r in exc.value.reasons)

    def test_too_long_rejected(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy(max_length=20).validate("A1!aaaaa" * 4)  # 32 chars
        assert any("at most 20" in r for r in exc.value.reasons)

    def test_strong_password_accepted(self):
        _policy().validate(STRONG_PASSWORD)


class TestComplexity:
    def test_three_classes_pass_threshold(self):
        # Lower + Upper + Digit, no symbol — 3 classes => OK at 12 chars.
        _policy().validate("Strongpass2024")

    def test_two_classes_below_long_threshold_rejected(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy().validate("strongpass2024")  # lower+digit = 2 classes, 14 chars
        assert any("at least 3" in r for r in exc.value.reasons)

    def test_two_classes_above_long_threshold_accepted(self):
        # 16+ chars with 2 classes is the passphrase escape hatch.
        _policy().validate("strongpasswordtwentyfour2024")


class TestCommonPasswords:
    def test_blocklisted_password_rejected(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy(min_length=8).validate("password")
        assert any("too common" in r for r in exc.value.reasons)

    def test_case_insensitive_blocklist(self):
        with pytest.raises(PasswordPolicyError):
            _policy(min_length=8).validate("PASSWORD")


class TestUserInfoContainment:
    def test_password_containing_username_rejected(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy().validate("Alice-Strong-Pass-9!", username=USERNAME, email=EMAIL)
        assert any("username" in r.lower() for r in exc.value.reasons)

    def test_password_containing_email_local_part_rejected(self):
        with pytest.raises(PasswordPolicyError):
            _policy().validate(
                "AliceLocalPart-9!a",
                username="bob",
                email="alicelocalpart@example.com",
            )

    def test_short_username_not_substring_checked(self):
        # Username under 3 chars is ignored for substring checks.
        _policy().validate(STRONG_PASSWORD, username="al", email=EMAIL)


class TestSimplePatterns:
    def test_long_repeat_rejected(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy().validate("Aaaa1234567!Bb")
        assert any(
            "repeated" in r.lower() or "sequence" in r.lower() for r in exc.value.reasons
        )

    def test_numeric_sequence_rejected(self):
        with pytest.raises(PasswordPolicyError):
            _policy().validate("ZZ-12345-Abc!")  # contains 12345

    def test_reverse_sequence_rejected(self):
        with pytest.raises(PasswordPolicyError):
            _policy().validate("Abcd-54321-XYZ!")


class TestIsValid:
    def test_is_valid_false_on_violation(self):
        assert _policy().is_valid("short") is False

    def test_is_valid_true_on_strong(self):
        assert _policy().is_valid(STRONG_PASSWORD) is True


class TestPolicyAggregatesViolations:
    def test_multiple_violations_in_one_error(self):
        with pytest.raises(PasswordPolicyError) as exc:
            _policy().validate("a", username=USERNAME, email=EMAIL)
        # Should report length + complexity at minimum.
        assert len(exc.value.reasons) >= 2
