# Structured Logging

Phase 1 of [issue #24](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/24).
Provides JSON / text structured logs, request-correlation IDs, and best-effort
masking of sensitive data — all using the stdlib `logging` module (no new
runtime dependencies).

Phase 2 (performance metrics, business-event helpers) and Phase 3
(OpenTelemetry export) are tracked as separate follow-up issues and are **not**
included in this PR.

## JSON Schema

When `LOG_FORMAT=json` each record is emitted as a single-line JSON document:

| Field         | Type            | Description |
|---------------|-----------------|-------------|
| `timestamp`   | string          | ISO-8601 UTC with millisecond precision (trailing `Z`). |
| `level`       | string          | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`. |
| `logger`      | string          | Logger name (e.g. `app.servers.application.service`). |
| `message`     | string          | Rendered message text, already scrubbed by `SensitiveDataFilter`. |
| `request_id`  | string \| null  | UUID4 from `AuditMiddleware` for the current request. |
| `user_id`     | int \| null     | Authenticated user id, if known. |
| `client_ip`   | string \| null  | Originating client IP (honours `X-Forwarded-For`). |
| `module`      | string          | Source module. |
| `function`    | string          | Source function. |
| `line`        | int             | Source line number. |
| `extra`       | object          | Any `extra={...}` fields passed at log time. |
| `exception`   | object          | Only present when `exc_info` is set. `{ type, message, traceback }`. |

The `request_id` field matches the `X-Request-ID` response header set by
`AuditMiddleware`, so it can be used to join request-level traces.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. `DEBUG` is rejected when `ENVIRONMENT=production`. |
| `LOG_FORMAT` | `text` | `text` for development, `json` for production / aggregators. |
| `LOG_FILE` | _(unset)_ | If set, also write to a rotating file at this path. |
| `LOG_FILE_MAX_BYTES` | `10485760` (10 MiB) | Rotation threshold for the file handler. |
| `LOG_FILE_BACKUP_COUNT` | `5` | Number of rotated files to retain. |

## Local development

```bash
LOG_LEVEL=INFO
LOG_FORMAT=text
# LOG_FILE intentionally unset → stdout only
```

Example output:

```
2026-05-22T12:34:56 INFO [9c0d…e1] app.servers.application.service: server started
```

## Production

```bash
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=/var/log/mc-server-dashboard/app.log
LOG_FILE_MAX_BYTES=52428800     # 50 MiB
LOG_FILE_BACKUP_COUNT=10
```

Example output (formatted for readability — the on-disk form is single-line):

```json
{
  "timestamp": "2026-05-22T12:34:56.789Z",
  "level": "INFO",
  "logger": "app.servers.application.service",
  "message": "server started",
  "request_id": "9c0d...e1",
  "user_id": 42,
  "client_ip": "10.0.0.1",
  "module": "service",
  "function": "start_server",
  "line": 218,
  "extra": { "server_id": 7 }
}
```

## Sensitive-data masking

Two layers protect against leaking secrets:

1. **Message scrubber** — `SensitiveDataFilter` rewrites `key=value` and
   `key: value` fragments inside the rendered message whenever the key
   matches one of the substrings in `SENSITIVE_FIELDS`:
   `password`, `token`, `secret`, `key`, `auth`, `credential`, `private`,
   `sensitive`, `confidential`, `jwt`, `refresh`.
2. **Extras scrubber** — entries in `extra={...}` whose key matches the same
   list are replaced with `"[FILTERED]"`. Nested dicts / lists are walked
   recursively.

### Extending the filter

`SENSITIVE_FIELDS` lives in `app/core/logging.py` and is re-exported from
`app/middleware/audit_middleware.py` for backward compatibility. To add a new
sensitive substring, append it to the list in `app/core/logging.py`:

```python
SENSITIVE_FIELDS.append("api_key")
```

Match is case-insensitive substring, so adding `"api_key"` will mask
`API_KEY`, `user_api_key`, `apiKey123`, etc.

## External log aggregation

The configuration writes plain JSON to stdout when `LOG_FORMAT=json`, which is
compatible with any log shipper that tails container output. A typical
production pipeline:

```
app (JSON to stdout)  →  Vector / Fluent Bit / Promtail  →  Loki / Elasticsearch / Datadog
```

The `request_id` field is suitable as a primary index for request tracing in
your aggregator. To correlate against the HTTP layer, search for the same
value in the `X-Request-ID` response header.

## Out of scope (Phase 2 / Phase 3)

These items are intentionally **not** part of this PR and should be tracked
as separate issues:

- **Phase 2** — request/response performance-metric emission, business-event
  helpers (server start/stop, backup created, etc.), enhanced error context.
- **Phase 3** — OpenTelemetry tracing exporter, distributed-trace propagation
  via `traceparent` headers.

The current implementation deliberately reuses the `AuditMiddleware`
`ContextVar`s (`request_id_context`, `user_id_context`, `ip_address_context`)
so that future tracing work can hook in at the same boundary without rewiring
log records.
