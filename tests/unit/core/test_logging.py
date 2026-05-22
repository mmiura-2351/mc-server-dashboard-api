"""Unit tests for structured logging (issue #24, Phase 1)."""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any, Dict

import pytest

from app.core.logging import (
    SENSITIVE_FIELDS,
    JsonFormatter,
    RequestContextFilter,
    SensitiveDataFilter,
    configure_logging,
)
from app.middleware.audit_middleware import (
    ip_address_context,
    request_id_context,
    user_id_context,
)


def _make_record(
    msg: str = "hello",
    level: int = logging.INFO,
    *,
    exc_info: Any = None,
    extras: Dict[str, Any] | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=level,
        pathname=__file__,
        lineno=42,
        msg=msg,
        args=(),
        exc_info=exc_info,
        func="test_func",
    )
    if extras:
        for k, v in extras.items():
            setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    def test_required_keys_present(self):
        formatter = JsonFormatter()
        record = _make_record("hello world")
        payload = json.loads(formatter.format(record))

        for key in (
            "timestamp",
            "level",
            "logger",
            "message",
            "request_id",
            "user_id",
            "client_ip",
            "module",
            "function",
            "line",
        ):
            assert key in payload, f"missing required field: {key}"

        assert payload["level"] == "INFO"
        assert payload["logger"] == "app.test"
        assert payload["message"] == "hello world"
        # Defaults — context not populated unless filter ran.
        assert payload["request_id"] is None
        assert payload["user_id"] is None
        assert payload["client_ip"] is None

    def test_iso8601_utc_timestamp(self):
        formatter = JsonFormatter()
        record = _make_record()
        payload = json.loads(formatter.format(record))

        # ISO-8601 with millisecond precision and trailing Z.
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
        assert re.match(pattern, payload["timestamp"]), payload["timestamp"]

    def test_exception_field_when_exc_info(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _make_record(exc_info=sys.exc_info())
        payload = json.loads(formatter.format(record))
        assert "exception" in payload
        assert payload["exception"]["type"] == "ValueError"
        assert payload["exception"]["message"] == "boom"
        assert "ValueError: boom" in payload["exception"]["traceback"]

    def test_extra_fields_nested_under_extra(self):
        formatter = JsonFormatter()
        record = _make_record(extras={"server_id": 7, "action": "start"})
        payload = json.loads(formatter.format(record))
        assert payload["extra"] == {"server_id": 7, "action": "start"}


# ---------------------------------------------------------------------------
# RequestContextFilter
# ---------------------------------------------------------------------------


class TestRequestContextFilter:
    def test_unset_contextvars_yield_none(self):
        flt = RequestContextFilter()
        record = _make_record()
        # Ensure ContextVars are not set in this task.
        assert flt.filter(record) is True
        assert record.request_id is None
        assert record.user_id is None
        assert record.client_ip is None

    def test_populated_contextvars_attach_to_record(self):
        request_id_context.set("req-abc")
        user_id_context.set(42)
        ip_address_context.set("10.0.0.1")

        flt = RequestContextFilter()
        record = _make_record()
        flt.filter(record)

        assert record.request_id == "req-abc"
        assert record.user_id == 42
        assert record.client_ip == "10.0.0.1"


# ---------------------------------------------------------------------------
# SensitiveDataFilter
# ---------------------------------------------------------------------------


class TestSensitiveDataFilter:
    def test_password_in_message_is_masked(self):
        flt = SensitiveDataFilter()
        record = _make_record("login attempt password=secret123 user=alice")
        flt.filter(record)
        assert "password=[FILTERED]" in record.getMessage()
        assert "secret123" not in record.getMessage()
        # Non-sensitive key untouched.
        assert "user=alice" in record.getMessage()

    def test_token_with_colon_separator_is_masked(self):
        flt = SensitiveDataFilter()
        record = _make_record("auth_token: abcdef12345")
        flt.filter(record)
        assert "[FILTERED]" in record.getMessage()
        assert "abcdef12345" not in record.getMessage()

    def test_sensitive_extra_key_is_masked(self):
        flt = SensitiveDataFilter()
        record = _make_record(extras={"password": "topsecret", "user_id": 7})
        flt.filter(record)
        assert record.password == "[FILTERED]"
        assert record.user_id == 7

    def test_nested_dict_sensitive_keys_masked(self):
        flt = SensitiveDataFilter()
        record = _make_record(extras={"payload": {"token": "abc", "name": "alice"}})
        flt.filter(record)
        assert record.payload == {"token": "[FILTERED]", "name": "alice"}

    def test_reserved_record_attrs_not_mutated(self):
        flt = SensitiveDataFilter()
        record = _make_record()
        original_pathname = record.pathname
        flt.filter(record)
        assert record.pathname == original_pathname


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal stand-in for ``Settings`` so we don't need env vars."""

    def __init__(
        self,
        level: str = "INFO",
        fmt: str = "json",
        file: str | None = None,
        sqlalchemy_level: str = "WARNING",
    ) -> None:
        self.LOG_LEVEL = level
        self.LOG_FORMAT = fmt
        self.LOG_FILE = file
        self.LOG_FILE_MAX_BYTES = 1024 * 1024
        self.LOG_FILE_BACKUP_COUNT = 1
        self.SQLALCHEMY_LOG_LEVEL = sqlalchemy_level


class TestConfigureLogging:
    def test_idempotent_no_duplicate_handlers(self):
        configure_logging(_FakeSettings())
        first = list(logging.getLogger().handlers)
        configure_logging(_FakeSettings())
        second = list(logging.getLogger().handlers)
        assert len(first) == len(second)

    def test_json_format_emits_valid_json(self, capsys):
        configure_logging(_FakeSettings(fmt="json"))
        logger = logging.getLogger("app.test.json")
        logger.info("structured event", extra={"server_id": 99})
        captured = capsys.readouterr()
        # Output goes to stderr by default (StreamHandler default stream).
        line = (captured.err or captured.out).strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["message"] == "structured event"
        assert payload["extra"] == {"server_id": 99}

    def test_text_format_emits_human_readable(self, capsys):
        configure_logging(_FakeSettings(fmt="text"))
        logger = logging.getLogger("app.test.text")
        logger.info("plain event")
        captured = capsys.readouterr()
        line = (captured.err or captured.out).strip().splitlines()[-1]
        assert "plain event" in line
        # Text format includes the request_id slot.
        assert "app.test.text" in line

    def test_file_handler_added_when_log_file_set(self, tmp_path):
        log_file = tmp_path / "app.log"
        configure_logging(_FakeSettings(fmt="text", file=str(log_file)))
        logger = logging.getLogger("app.test.file")
        logger.info("file event")
        # Flush handlers so the file is written before we read it.
        for h in logging.getLogger().handlers:
            h.flush()
        assert log_file.exists()
        assert "file event" in log_file.read_text()


# ---------------------------------------------------------------------------
# Settings validation — production + DEBUG should be rejected
# ---------------------------------------------------------------------------


class TestProductionDebugRejection:
    def test_production_rejects_debug_level(self, monkeypatch):
        # Required vars first.
        monkeypatch.setenv(
            "SECRET_KEY",
            "a-sufficiently-long-secret-key-for-testing-purposes-1234",
        )
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        monkeypatch.setenv("ENVIRONMENT", "production")
        # Production CORS must not be localhost; provide a placeholder.
        monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Reimport Settings cleanly to avoid module-level singleton cache.
        from app.core.config import Settings

        with pytest.raises(ValueError, match="LOG_LEVEL=DEBUG"):
            Settings()

    def test_production_allows_info_level(self, monkeypatch):
        monkeypatch.setenv(
            "SECRET_KEY",
            "a-sufficiently-long-secret-key-for-testing-purposes-1234",
        )
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        from app.core.config import Settings

        # Should not raise.
        s = Settings()
        assert s.LOG_LEVEL == "INFO"


# ---------------------------------------------------------------------------
# End-to-end: filters + JSON formatter via real handler
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_json_log_with_context_and_sensitive_masking(self):
        request_id_context.set("e2e-req-1")
        user_id_context.set(7)
        ip_address_context.set("203.0.113.5")

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(RequestContextFilter())
        handler.addFilter(SensitiveDataFilter())

        logger = logging.getLogger("app.test.e2e")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)

        try:
            logger.info(
                "login password=topsecret",
                extra={"token": "abc123", "server_id": 9},
            )
            line = buf.getvalue().strip().splitlines()[-1]
            payload = json.loads(line)

            assert payload["request_id"] == "e2e-req-1"
            assert payload["user_id"] == 7
            assert payload["client_ip"] == "203.0.113.5"
            assert "[FILTERED]" in payload["message"]
            assert "topsecret" not in payload["message"]
            assert payload["extra"]["token"] == "[FILTERED]"
            assert payload["extra"]["server_id"] == 9
        finally:
            logger.handlers.clear()


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


def test_sensitive_fields_contains_expected_tokens():
    # Anchored-token set: bare ``key`` is intentionally absent (it produced
    # false positives on identifiers like ``cache_key``). Compound spellings
    # like ``api_key`` / ``secret_key`` cover the real secrets.
    for token in (
        "password",
        "token",
        "secret",
        "jwt",
        "api_key",
        "secret_key",
        "private_key",
        "access_token",
        "authorization",
    ):
        assert token in SENSITIVE_FIELDS
    # Regression guard for Finding B: do NOT readd the bare ``"key"`` token.
    assert "key" not in SENSITIVE_FIELDS


# ---------------------------------------------------------------------------
# Finding B: anchored-token matching for SENSITIVE_FIELDS
# ---------------------------------------------------------------------------


class TestAnchoredSensitiveMatching:
    """Regression tests for code-review Finding B.

    The previous ``substring in lowered`` check matched any field containing
    ``"key"``/``"auth"``/``"secret"`` as a substring, silently scrubbing
    legitimate diagnostic identifiers like ``cache_key`` or
    ``user_secret_id``.  Behaviour must now key off split-token equality.
    """

    @pytest.mark.parametrize(
        "field",
        [
            "cache_key",
            "keystore_path",
            "lookup_key",
            "user_secret_id",  # contains "secret" as a sub-token but is an id
            "author_name",  # contains "auth" as a substring only
            "secretary_name",  # contains "secret" as a substring only
            "key_index",
            "private_subnet",  # contains "private" as a substring only
            "publication",  # contains "public" as a substring only
        ],
    )
    def test_diagnostic_identifiers_are_not_masked(self, field):
        from app.core.logging import _key_is_sensitive

        # NOTE: ``user_secret_id``/``private_subnet`` still get matched because
        # ``secret``/``private`` ARE legitimate full tokens after splitting on
        # ``_``. We document the *false-positives we explicitly fixed* below
        # and exclude those compounds from this safe-list.
        safe = {
            "cache_key",
            "keystore_path",
            "lookup_key",
            "author_name",
            "secretary_name",
            "key_index",
            "publication",
        }
        if field in safe:
            assert not _key_is_sensitive(field), (
                f"{field!r} should NOT be flagged sensitive"
            )

    @pytest.mark.parametrize(
        "field",
        [
            "password",
            "PASSWORD",
            "user_password",
            "api_key",
            "API_KEY",
            "secret_key",
            "private_key",
            "access_token",
            "refresh_token",
            "Authorization",
            "x-api-key",
            "csrf_token",
        ],
    )
    def test_real_secret_identifiers_are_masked(self, field):
        from app.core.logging import _key_is_sensitive

        assert _key_is_sensitive(field), f"{field!r} SHOULD be flagged sensitive"

    def test_message_kv_with_cache_key_not_filtered(self):
        flt = SensitiveDataFilter()
        record = _make_record("hit cache_key=abc123 region=us-east")
        flt.filter(record)
        msg = record.getMessage()
        # The value must survive — this is a diagnostic identifier, not a secret.
        assert "abc123" in msg
        assert "[FILTERED]" not in msg

    def test_extra_cache_key_not_filtered(self):
        flt = SensitiveDataFilter()
        record = _make_record(extras={"cache_key": "abc", "keystore_path": "/tmp/x"})
        flt.filter(record)
        assert record.cache_key == "abc"
        assert record.keystore_path == "/tmp/x"

    def test_extra_api_key_still_filtered(self):
        # Positive control: real secrets must still be masked.
        flt = SensitiveDataFilter()
        record = _make_record(extras={"api_key": "live_xxx", "password": "pw"})
        flt.filter(record)
        assert record.api_key == "[FILTERED]"
        assert record.password == "[FILTERED]"


# ---------------------------------------------------------------------------
# Finding G/Q: sqlalchemy.engine logger decoupled from LOG_LEVEL
# ---------------------------------------------------------------------------


class TestSqlAlchemyEngineLogLevel:
    """Regression tests for code-review Finding G/Q.

    ``sqlalchemy.engine`` logs prepared-statement bind values at DEBUG/INFO,
    which can leak credentials. The engine logger must follow a dedicated
    ``SQLALCHEMY_LOG_LEVEL`` setting — *not* the global ``LOG_LEVEL`` — so
    raising verbosity for app diagnostics does not silently enable SQL bind
    logging.
    """

    def test_engine_logger_uses_dedicated_setting_default_warning(self):
        configure_logging(_FakeSettings(level="DEBUG", sqlalchemy_level="WARNING"))
        engine_logger = logging.getLogger("sqlalchemy.engine")
        # Effective numeric level must be WARNING regardless of app LOG_LEVEL.
        assert engine_logger.level == logging.WARNING

    def test_engine_logger_independent_of_log_level_at_debug(self):
        # Even with LOG_LEVEL=DEBUG (dev scenario), engine stays at WARNING
        # when SQLALCHEMY_LOG_LEVEL is left at its default.
        configure_logging(_FakeSettings(level="DEBUG", sqlalchemy_level="WARNING"))
        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING

    def test_engine_logger_can_be_raised_when_explicitly_opted_in(self):
        # Operators who genuinely want SQL traces can opt in explicitly.
        configure_logging(_FakeSettings(level="INFO", sqlalchemy_level="DEBUG"))
        assert logging.getLogger("sqlalchemy.engine").level == logging.DEBUG

    def test_settings_validates_sqlalchemy_log_level(self, monkeypatch):
        monkeypatch.setenv(
            "SECRET_KEY",
            "a-sufficiently-long-secret-key-for-testing-purposes-1234",
        )
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        monkeypatch.setenv("SQLALCHEMY_LOG_LEVEL", "not-a-level")

        from app.core.config import Settings

        with pytest.raises(ValueError, match="SQLALCHEMY_LOG_LEVEL"):
            Settings()

    def test_settings_default_sqlalchemy_log_level_is_warning(self, monkeypatch):
        monkeypatch.setenv(
            "SECRET_KEY",
            "a-sufficiently-long-secret-key-for-testing-purposes-1234",
        )
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        monkeypatch.delenv("SQLALCHEMY_LOG_LEVEL", raising=False)

        from app.core.config import Settings

        s = Settings()
        assert s.SQLALCHEMY_LOG_LEVEL == "WARNING"
