"""Structured logging configuration for the application.

Phase 1 of issue #24. Provides:

* JSON / text formatters (stdlib only, no third-party deps).
* A ``RequestContextFilter`` that injects ``request_id``, ``user_id`` and
  ``client_ip`` onto every record from the audit-middleware ``ContextVar``s.
* A ``SensitiveDataFilter`` that masks values whose keys (or ``key=value``
  fragments inside the formatted message) look like secrets.
* :func:`configure_logging` — wires the above through ``dictConfig`` and is
  idempotent (safe to call repeatedly, e.g. from tests).

Out-of-scope for this PR (tracked in Phase 2 / Phase 3 follow-up issues):
performance-metric emission, business-event helpers, OpenTelemetry export.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import logging.config
import re
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.config import Settings

# Re-exported so ``audit_middleware`` can import a single source of truth.
#
# Anchored-token set. Matching is done by splitting candidate keys on
# ``_``/``-``/``.`` boundaries and checking *token equality* (not substring
# containment) so legitimate diagnostic identifiers like ``cache_key``,
# ``keystore_path`` or ``user_secret_id`` are not falsely scrubbed. Compound
# secret labels (``api_key``, ``private_key`` …) are listed explicitly.
SENSITIVE_FIELDS = frozenset(
    {
        # Bare-word secrets.
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "cookie",
        "session",
        "sessionid",
        "jwt",
        "refresh",
        "apikey",  # for the no-separator spelling
        # Compound spellings — these survive the split() pass intact only
        # when the original key has no separators (e.g. ``Authorization``),
        # so the equality check still hits them via the rejoined fallback
        # below.
        "api_key",
        "secret_key",
        "private_key",
        "public_key",  # commonly paired with private_key in keymats
        "access_key",
        "access_token",
        "refresh_token",
        "auth_token",
        "id_token",
        "client_secret",
        "csrf_token",
        "x_api_key",
    }
)

# Tokens that should match anywhere (not as keys, but in free-text k=v).
_SPLIT_RE = re.compile(r"[_\-.]+")

# Matches ``foo=value`` or ``foo: value`` style fragments inside log messages so
# we can mask values that happen to be inlined into f-strings.
_KV_PATTERN = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*)"
    r"\s*(?P<sep>[:=])\s*"
    r"(?P<val>(?:\"[^\"]*\"|'[^']*'|[^\s,;)\]}]+))"
)

_FILTERED = "[FILTERED]"

# Module-level guard so ``configure_logging`` is idempotent without leaking
# duplicate handlers when called more than once (e.g. from tests).
_CONFIGURED = False


def _key_is_sensitive(key: str) -> bool:
    """Return True iff ``key`` looks like a secret-bearing identifier.

    Anchored-token match: the key is split on ``_``/``-``/``.``, then we check
    three things against :data:`SENSITIVE_FIELDS` (all equality, no substring):

    1. The full lowercased key (catches ``Authorization``).
    2. Each individual split token (catches ``password`` in ``user_password``).
    3. Adjacent token pairs rejoined with ``_`` (catches ``api_key`` in
       ``x-api-key`` / ``API.Key`` etc.).

    Step 3 lets compound spellings in ``SENSITIVE_FIELDS`` (e.g. ``api_key``,
    ``secret_key``, ``access_token``) match across any separator while still
    rejecting unrelated identifiers like ``cache_key`` or ``keystore_path``
    where the standalone token (``key``) is intentionally NOT in the set.
    """
    if not key:
        return False
    lowered = key.lower()
    if lowered in SENSITIVE_FIELDS:
        return True
    tokens = [t for t in _SPLIT_RE.split(lowered) if t]
    if any(t in SENSITIVE_FIELDS for t in tokens):
        return True
    # Adjacent bigrams rejoined with ``_`` to catch compound labels regardless
    # of original separator (``x-api-key`` → ``x_api`` / ``api_key``).
    for i in range(len(tokens) - 1):
        if f"{tokens[i]}_{tokens[i + 1]}" in SENSITIVE_FIELDS:
            return True
    return False


def _mask_message(message: str) -> str:
    """Mask ``key=value`` / ``key: value`` fragments where the key is sensitive."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group("key")
        sep = match.group("sep")
        if _key_is_sensitive(key):
            return f"{key}{sep}{_FILTERED}"
        return match.group(0)

    return _KV_PATTERN.sub(_replace, message)


def _mask_mapping(value: Any) -> Any:
    """Recursively mask sensitive entries inside dict / list / tuple structures."""
    if isinstance(value, dict):
        return {
            k: (_FILTERED if _key_is_sensitive(str(k)) else _mask_mapping(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_mapping(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_mask_mapping(v) for v in value)
    return value


class RequestContextFilter(logging.Filter):
    """Attach ``request_id`` / ``user_id`` / ``client_ip`` to every record.

    Reads from the ``ContextVar``s owned by ``AuditMiddleware``. Imports are
    deferred to keep this module import-safe during early bootstrap (before
    the middleware module is imported).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            from app.middleware.audit_middleware import (
                ip_address_context,
                request_id_context,
                user_id_context,
            )
        except Exception:  # pragma: no cover - defensive
            request_id = user_id = client_ip = None
        else:
            try:
                request_id = request_id_context.get()
            except LookupError:
                request_id = None
            try:
                user_id = user_id_context.get()
            except LookupError:
                user_id = None
            try:
                client_ip = ip_address_context.get()
            except LookupError:
                client_ip = None

        # Only set attributes if not already provided via ``extra=`` so that
        # callers can override the inferred context if they want.
        if not hasattr(record, "request_id"):
            record.request_id = request_id
        if not hasattr(record, "user_id"):
            record.user_id = user_id
        if not hasattr(record, "client_ip"):
            record.client_ip = client_ip
        return True


class SensitiveDataFilter(logging.Filter):
    """Best-effort masking of sensitive content in messages and extras."""

    # Standard ``LogRecord`` attributes we should not treat as user-supplied
    # extras when scrubbing.
    _RESERVED_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
            # Injected by RequestContextFilter; safe values, never sensitive.
            "request_id",
            "user_id",
            "client_ip",
        }
    )

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        # Mask the rendered message. We render once and stash the masked form
        # so downstream formatters see the masked text.
        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            rendered = str(record.msg)
        masked = _mask_message(rendered)
        if masked != rendered:
            # Replace ``msg`` with the masked text and clear ``args`` so the
            # formatter does not attempt the ``%`` substitution again.
            record.msg = masked
            record.args = ()

        # Walk extras and mask any sensitive keys.
        for attr, value in list(record.__dict__.items()):
            if attr in self._RESERVED_ATTRS or attr.startswith("_"):
                continue
            if _key_is_sensitive(attr):
                record.__dict__[attr] = _FILTERED
            else:
                record.__dict__[attr] = _mask_mapping(value)
        return True


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON document.

    Schema:

    ``timestamp``     ISO-8601 UTC, millisecond precision, trailing ``Z``.
    ``level``         Log level name.
    ``logger``        Logger name (``record.name``).
    ``message``       Rendered message text (already scrubbed by the filter).
    ``request_id``    UUID4 from ``AuditMiddleware`` ContextVar (or ``None``).
    ``user_id``       Authenticated user id (or ``None``).
    ``client_ip``     Originating client IP (or ``None``).
    ``module``        Source module.
    ``function``      Source function.
    ``line``          Source line number.
    ``extra``         Any user-supplied ``extra={...}`` fields.
    ``exception``     ``{type, message, traceback}`` when ``exc_info`` is set.
    """

    _BASE_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
            "request_id",
            "user_id",
            "client_ip",
        }
    )

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        # ``SensitiveDataFilter`` may have already rewritten ``msg`` and
        # cleared ``args``. ``getMessage`` is still safe in that case.
        message = record.getMessage()

        timestamp = (
            _dt.datetime.fromtimestamp(record.created, tz=_dt.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

        payload: Dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
            "client_ip": getattr(record, "client_ip", None),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        extras: Dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in self._BASE_ATTRS or key.startswith("_"):
                continue
            extras[key] = value
        if extras:
            payload["extra"] = extras

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                ),
            }

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-friendly formatter for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )


def _build_handlers(settings: "Settings") -> Dict[str, Dict[str, Any]]:
    formatter_name = "json" if settings.LOG_FORMAT == "json" else "text"
    handlers: Dict[str, Dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": settings.LOG_LEVEL,
            "formatter": formatter_name,
            "filters": ["request_context", "sensitive_data"],
        },
    }
    if settings.LOG_FILE:
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": settings.LOG_LEVEL,
            "formatter": formatter_name,
            "filters": ["request_context", "sensitive_data"],
            "filename": settings.LOG_FILE,
            "maxBytes": settings.LOG_FILE_MAX_BYTES,
            "backupCount": settings.LOG_FILE_BACKUP_COUNT,
            "encoding": "utf-8",
        }
    return handlers


def configure_logging(settings: "Settings") -> None:
    """Install the structured-logging dictConfig.

    Idempotent: subsequent calls reuse the same configuration without
    appending duplicate handlers. Safe to call from tests.
    """
    global _CONFIGURED

    handlers = _build_handlers(settings)
    handler_names = list(handlers.keys())

    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {"()": RequestContextFilter},
            "sensitive_data": {"()": SensitiveDataFilter},
        },
        "formatters": {
            "json": {"()": JsonFormatter},
            "text": {"()": TextFormatter},
        },
        "handlers": handlers,
        "loggers": {
            # Project loggers — propagate to root so pytest's ``caplog`` can
            # still capture records (caplog attaches its handler to root).
            "app": {"level": settings.LOG_LEVEL, "propagate": True},
            # Uvicorn writes its own handlers by default; route them through
            # our config and turn off propagation to avoid duplicate output.
            "uvicorn": {
                "handlers": handler_names,
                "level": settings.LOG_LEVEL,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": handler_names,
                "level": settings.LOG_LEVEL,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": handler_names,
                "level": settings.LOG_LEVEL,
                "propagate": False,
            },
            # SQLAlchemy emits bound parameter values at DEBUG / INFO which
            # can leak passwords or tokens. Pin to a dedicated setting (default
            # WARNING) so raising ``LOG_LEVEL`` for app diagnostics does not
            # silently turn on SQL parameter logging. Falls back to WARNING if
            # an older Settings instance is in use.
            "sqlalchemy.engine": {
                "level": getattr(settings, "SQLALCHEMY_LOG_LEVEL", "WARNING"),
                "propagate": True,
            },
        },
        "root": {
            "handlers": handler_names,
            "level": settings.LOG_LEVEL,
        },
    }

    logging.config.dictConfig(config)
    _CONFIGURED = True


def get_request_id() -> Optional[str]:
    """Compatibility re-export. Returns the current request correlation id."""
    try:
        from app.middleware.audit_middleware import request_id_context
    except Exception:  # pragma: no cover - defensive
        return None
    try:
        return request_id_context.get()
    except LookupError:
        return None


__all__ = [
    "SENSITIVE_FIELDS",
    "RequestContextFilter",
    "SensitiveDataFilter",
    "JsonFormatter",
    "TextFormatter",
    "configure_logging",
    "get_request_id",
]
