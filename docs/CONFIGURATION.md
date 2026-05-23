# Configuration Reference (Issue #22 Phase 1)

This document is the canonical reference for `app.core.config.Settings`.
It covers:

1. The `Environment` enum and per-environment behaviour.
2. The full `.env` / environment-variable load order.
3. Every field, its type, default, and any validator constraints.
4. Per-environment default overlays.
5. Production / staging hardening rules.
6. Migration notes from the pre-Issue-#22 `.env`-only model.
7. Production deployment checklist.

## 1. Environments

`ENVIRONMENT` is typed as the `Environment` enum (string-derived, so all
existing string comparisons such as `settings.ENVIRONMENT == "production"`
continue to work):

| Value         | Intent                                            |
|---------------|---------------------------------------------------|
| `development` | Local developer workstation. Permissive defaults. |
| `testing`     | Automated test runs (CI, pytest).                 |
| `staging`     | Pre-production; production-like CORS hardening.   |
| `production`  | Live deployment; strictest hardening.             |

Values are accepted case-insensitively (`PRODUCTION` → `Environment.PRODUCTION`).
Unknown values raise a validation error at startup.

Convenience properties: `settings.is_development`, `settings.is_testing`,
`settings.is_staging`, `settings.is_production`.

## 2. Load order

Settings are composed from these sources, lowest to highest precedence:

1. Class-level defaults defined on `Settings`.
2. **Per-environment defaults overlay** (`_PER_ENV_DEFAULTS`), injected
   before pydantic validation.
3. `.env` (always read, if present).
4. `.env.{environment}` (e.g. `.env.production`).
5. `.env.{environment}.local` (never committed; developer / operator overrides).
6. `os.environ` (process environment variables — wins over `.env` files).
7. Explicit `Settings(...)` keyword arguments (test convenience; overrides
   everything above).

`ENVIRONMENT` itself is resolved *first* (from kwargs / `os.environ`) so
that the `.env.{environment}` files used in steps 4–5 reflect the active
environment.

```
defaults ─► per-env overlay ─► .env ─► .env.{env} ─► .env.{env}.local ─► os.environ ─► kwargs
                                  (lower)                                              (higher)
```

## 3. Per-environment default overlay

When a key is **not** explicitly supplied (env var, `.env`, kwarg), the
overlay fills it in based on `ENVIRONMENT`. Explicit values always win.

| Setting                    | development | testing | staging | production |
|---------------------------|-------------|---------|---------|------------|
| `LOG_LEVEL`               | `INFO`      | `WARNING` | `INFO`  | `INFO`     |
| `LOG_FORMAT`              | `text`      | `text`  | `json`  | `json`     |
| `KEEP_SERVERS_ON_SHUTDOWN`| `True`      | `False` | `True`  | `True`     |
| `AUTO_SYNC_ON_STARTUP`    | `True`      | `False` | `True`  | `True`     |
| `DATABASE_MAX_RETRIES`    | `3`         | `1`     | `3`     | `5`        |

## 4. Field reference

Required fields have no default. All others fall back to the class default,
which the per-env overlay may further refine.

### Auth / JWT

| Field | Type | Default | Validation |
|---|---|---|---|
| `SECRET_KEY` | `str` | *(required)* | ≥ 32 chars; rejects prefixes `your-secret-key`, `secret`, `default`, `change-me` |
| `ALGORITHM` | `str` | `HS256` | — |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `int` | `30` | — |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `int` | `30` | — |

### Database

| Field | Type | Default | Validation |
|---|---|---|---|
| `DATABASE_URL` | `str` | *(required)* | `sqlite:` rejected in production |
| `DATABASE_MAX_RETRIES` | `int` | `3` (overlay-aware) | 1–10 |
| `DATABASE_RETRY_BACKOFF` | `float` | `0.1` | 0.01–5.0 sec |
| `DATABASE_BATCH_SIZE` | `int` | `100` | 10–1000 |

### Server management / Java

| Field | Type | Default | Validation |
|---|---|---|---|
| `SERVER_LOG_QUEUE_SIZE` | `int` | `500` | 100–10000 |
| `JAVA_CHECK_TIMEOUT` | `int` | `5` | 1–60 sec |
| `KEEP_SERVERS_ON_SHUTDOWN` | `bool` | `True` (overlay-aware) | — |
| `AUTO_SYNC_ON_STARTUP` | `bool` | `True` (overlay-aware) | — |
| `JAVA_DISCOVERY_PATHS` | `str` | `""` | comma-separated paths |
| `JAVA_8_PATH` … `JAVA_21_PATH` | `str` | `""` | direct path to `java` binary |

### Daemon process settings (`DAEMON_*`)

The 23 `DAEMON_*` environment variables live on
`app.core.daemon_config.DaemonConfig` (not on `Settings`). They are
loaded once at process start by `DaemonConfig.from_environment()` and
documented exhaustively — with defaults, validators, and cross-field
constraints — in
[`docs/DAEMON_MIGRATION.md`](DAEMON_MIGRATION.md) §3.2 and
[`docs/DAEMON_PROCESS_ARCHITECTURE.md`](DAEMON_PROCESS_ARCHITECTURE.md#configuration).
Defaults are appropriate for production; only override when you have a
specific reason.

### CORS

| Field | Type | Default | Validation |
|---|---|---|---|
| `CORS_ORIGINS` | `str` | localhost set | staging/production reject localhost & non-https |
| `ENVIRONMENT` | `Environment` | `development` | enum, case-insensitive |

### Backup housekeeping

| Field | Type | Default | Validation |
|---|---|---|---|
| `BACKUPS_PENDING_RETENTION_HOURS` | `int` | `24` | 1–8760 hrs |
| `BACKUPS_FAILED_RETENTION_DAYS` | `int` | `30` | 1–3650 days |
| `BACKUPS_CLEANUP_INTERVAL_SECONDS` | `int` | `3600` | 60–86400 sec |

### Health checks (Issue #21)

| Field | Type | Default | Validation |
|---|---|---|---|
| `HEALTH_CHECK_PER_COMPONENT_TIMEOUT_SECONDS` | `float` | `2.0` | (0, 60] |
| `HEALTH_CHECK_FS_TIMEOUT_SECONDS` | `float` | `1.0` | (0, 60] |
| `HEALTH_CHECK_GLOBAL_TIMEOUT_SECONDS` | `float` | `5.0` | (0, 60] |
| `HEALTH_CHECK_CACHE_TTL_SECONDS` | `float` | `2.0` | (0, 60] |

### Logging (Issue #24)

| Field | Type | Default | Validation |
|---|---|---|---|
| `LOG_LEVEL` | `str` | `INFO` (overlay-aware) | DEBUG/INFO/WARNING/ERROR/CRITICAL; `DEBUG` rejected in production |
| `LOG_FORMAT` | `"text"`\|`"json"` | `text` (overlay-aware) | — |
| `LOG_FILE` | `Optional[str]` | `None` | — |
| `LOG_FILE_MAX_BYTES` | `int` | `10*1024*1024` | 1 KiB – 1 GiB |
| `LOG_FILE_BACKUP_COUNT` | `int` | `5` | 0–100 |
| `SQLALCHEMY_LOG_LEVEL` | `str` | `WARNING` | DEBUG/INFO/WARNING/ERROR/CRITICAL |

## 5. Hardening rules

### Production (`ENVIRONMENT=production`)

* **Database**: `DATABASE_URL` must not contain `sqlite` (case-insensitive).
* **CORS**: every `CORS_ORIGINS` entry must start with `https://`.
* **CORS**: `localhost` / `127.0.0.1` are forbidden in `CORS_ORIGINS`.
* **Logging**: `LOG_LEVEL=DEBUG` is rejected.
* **Secret key**: ≥ 32 characters and not a well-known weak prefix.

### Staging (`ENVIRONMENT=staging`)

* **CORS**: every `CORS_ORIGINS` entry must start with `https://`.
* **CORS**: `localhost` / `127.0.0.1` are forbidden in `CORS_ORIGINS`.

Staging deliberately allows sqlite for ad-hoc pre-prod smoke runs.

### Development & Testing

No hardening — the validators above are skipped so local iteration and
the test suite remain unencumbered.

## 6. Migration from the pre-Issue-#22 setup

The new layout is backwards compatible:

* Existing `.env` files keep working unchanged.
* `ENVIRONMENT` defaults to `development`, matching the prior behaviour.
* `settings.ENVIRONMENT == "production"` continues to evaluate `True` for
  production deployments (the enum subclasses `str`).
* All previous validators (`SECRET_KEY` strength, `CORS_ORIGINS` localhost,
  `LOG_LEVEL=DEBUG` rejection) remain in force.

Recommended migration steps for production deployments:

1. Rename `.env` → `.env.production` on production hosts and set the
   process-level `ENVIRONMENT=production` (e.g. systemd unit, container env).
2. Move any host-specific secrets to `.env.production.local` (gitignored).
3. Audit `DATABASE_URL` and `CORS_ORIGINS` against the hardening rules above
   — the application will now refuse to start with unsafe combinations.

## 7. Production deployment checklist

* [ ] `ENVIRONMENT=production` is set in the process environment.
* [ ] `SECRET_KEY` is unique per environment, ≥ 32 chars, and not derived from
      any weak prefix.
* [ ] `DATABASE_URL` points at PostgreSQL or MySQL (not sqlite).
* [ ] `CORS_ORIGINS` lists only `https://…` hostnames you control.
* [ ] `LOG_FORMAT=json` (default for production via overlay).
* [ ] `LOG_FILE` either unset (stdout-only) or pointing at a writable path
      under a log-rotation-aware directory.
* [ ] `.env.production.local` exists only on the host (never committed) and
      contains any host-specific overrides.
* [ ] Application boots cleanly — startup-time `ValidationError`s indicate
      a hardening rule was violated; see §5.
