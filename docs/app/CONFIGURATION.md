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
| `LOG_LEVEL`                 | `INFO`    | `WARNING` | `INFO` | `INFO` |
| `LOG_FORMAT`                | `text`    | `text`    | `json` | `json` |
| `KEEP_SERVERS_ON_SHUTDOWN`  | `True`    | `False`   | `True` | `True` |
| `AUTO_SYNC_ON_STARTUP`      | `True`    | `False`   | `True` | `True` |
| `DATABASE_MAX_RETRIES`      | `3`       | `1`       | `3`    | `5`    |
| `PASSWORD_BCRYPT_ROUNDS`    | `12`      | `4`       | `12`   | `12`   |

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

### Database connection pool (Issue #369)

Applied to SQLAlchemy `create_engine()`. `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`
only take effect for non-SQLite backends (SQLite uses a single-connection pool
by default).

| Field | Type | Default | Validation |
|---|---|---|---|
| `DB_POOL_SIZE` | `int` | `5` | 1–100 |
| `DB_MAX_OVERFLOW` | `int` | `10` | 0–100 |
| `DB_POOL_RECYCLE` | `int` | `3600` (sec) | -1–86400 |
| `DB_POOL_PRE_PING` | `bool` | `True` | — |

### Server management / Java

| Field | Type | Default | Validation |
|---|---|---|---|
| `SERVER_LOG_QUEUE_SIZE` | `int` | `500` | 100–10000 |
| `JAVA_CHECK_TIMEOUT` | `int` | `5` | 1–60 sec |
| `KEEP_SERVERS_ON_SHUTDOWN` | `bool` | `True` (overlay-aware) | — |
| `AUTO_SYNC_ON_STARTUP` | `bool` | `True` (overlay-aware) | — |
| `JAVA_DISCOVERY_PATHS` | `str` | `""` | comma-separated paths |
| `JAVA_8_PATH` … `JAVA_25_PATH` | `str` | `""` | direct path to `java` binary |

### Daemon process settings (`DAEMON_*`)

The 23 `DAEMON_*` environment variables live on
`app.core.daemon_config.DaemonConfig` (not on `Settings`). They are loaded
once at process start by `DaemonConfig.from_environment()`. Defaults are
appropriate for production; only override when you have a specific reason.

Cross-references: process-level context is in
[`docs/app/DAEMON_PROCESS_ARCHITECTURE.md`](DAEMON_PROCESS_ARCHITECTURE.md);
the upgrade guide (with rollback) is in
[`docs/dev/DAEMON_MIGRATION.md`](../dev/DAEMON_MIGRATION.md). Both documents now
defer to this section for the env var inventory.

#### Process creation

| Field | DaemonConfig | Default | Validation |
|---|---|---|---|
| `DAEMON_MODE` | `daemon_mode` | `double_fork` | `double_fork` \| `subprocess_daemon` \| `process_group` |
| `DAEMON_ENABLE_PERSISTENCE` | `enable_process_persistence` | `true` | bool |
| `DAEMON_PID_DIRECTORY` | `pid_file_directory` | _server dir_ | writable dir; auto-`mkdir -p` |

#### Monitoring

| Field | DaemonConfig | Default | Validation |
|---|---|---|---|
| `DAEMON_ENABLE_MONITORING` | `enable_process_monitoring` | `true` | bool |
| `DAEMON_MONITORING_INTERVAL` | `monitoring_interval_seconds` | `5` | 1 ≤ n ≤ 60 |
| `DAEMON_STARTUP_TIMEOUT` | `process_startup_timeout_seconds` | `30` | 5 ≤ n ≤ 300 |

#### Resource limits (`DaemonProcessLimits`)

| Field | Limits field | Default | Validation |
|---|---|---|---|
| `DAEMON_MAX_MEMORY_MB` | `max_memory_mb` | `2048` | 1 ≤ n ≤ 32768 |
| `DAEMON_MAX_CPU_PERCENT` | `max_cpu_percent` | `80.0` | 0 < x ≤ 100 |
| `DAEMON_MAX_OPEN_FILES` | `max_open_files` | `1024` | 64 ≤ n ≤ 65536 |
| `DAEMON_MAX_PROCESSES` | `max_processes` | `10` | int |
| `DAEMON_TIMEOUT_SECONDS` | `timeout_seconds` | `300` | int (≥ startup timeout) |

#### Logging

| Field | DaemonConfig | Default | Validation |
|---|---|---|---|
| `DAEMON_LOG_LEVEL` | `log_level` | `info` | debug/info/warning/error/critical |
| `DAEMON_ENABLE_LOGS` | `enable_daemon_logs` | `true` | bool |
| `DAEMON_LOG_ROTATION_SIZE` | `log_rotation_size_mb` | `100` | 1 ≤ n ≤ 1000 |

#### Security

| Field | DaemonConfig | Default | Validation |
|---|---|---|---|
| `DAEMON_ENABLE_ISOLATION` | `enable_process_isolation` | `true` | bool |
| `DAEMON_VERIFY_DETACHMENT` | `verify_detachment` | `true` | bool |
| `DAEMON_SECURE_ENVIRONMENT` | `secure_environment` | `true` | bool |

#### RCON

| Field | DaemonConfig | Default | Validation |
|---|---|---|---|
| `DAEMON_ENABLE_RCON` | `enable_rcon_integration` | `true` | bool |
| `DAEMON_RCON_TIMEOUT` | `rcon_timeout_seconds` | `10` | 1 ≤ n ≤ 60 |
| `DAEMON_RCON_RETRY_ATTEMPTS` | `rcon_retry_attempts` | `3` | 1 ≤ n ≤ 10 |

#### Recovery

| Field | DaemonConfig | Default | Validation |
|---|---|---|---|
| `DAEMON_ENABLE_AUTO_RECOVERY` | `enable_auto_recovery` | `true` | bool |
| `DAEMON_RECOVERY_TIMEOUT` | `recovery_timeout_seconds` | `60` | 10 ≤ n ≤ 600 |
| `DAEMON_MAX_RECOVERY_ATTEMPTS` | `max_recovery_attempts` | `3` | 1 ≤ n ≤ 10 |

Cross-field constraints (see `DaemonConfig.validate_configuration`):
* `enable_auto_recovery=true` requires both `enable_process_persistence=true`
  and `enable_process_monitoring=true`.
* `process_startup_timeout_seconds` must be ≥ `monitoring_interval_seconds`.
* `resource_limits.timeout_seconds` must be ≥ `process_startup_timeout_seconds`.

### File uploads (Issue #341)

| Field | Type | Default | Validation |
|---|---|---|---|
| `FILE_MAX_UPLOAD_BYTES` | `int` | `104857600` (100 MiB) | `0` (disabled) or 1 KiB – 10 GiB |

Enforced via streaming/chunked reads — the full payload never lands in memory
before the limit check. Set to `0` to disable enforcement (not recommended
for production).

### Concurrency control (Issue #351)

Semaphore limits that cap concurrent heavy I/O to prevent resource exhaustion.

| Field | Type | Default | Validation |
|---|---|---|---|
| `MAX_CONCURRENT_BACKUPS` | `int` | `2` | 1–20; must be ≤ `FILE_IO_SEMAPHORE_LIMIT` |
| `MAX_CONCURRENT_WEBSOCKETS` | `int` | `100` | 1–10000 |
| `FILE_IO_SEMAPHORE_LIMIT` | `int` | `10` | 1–100 |

### Password policy (Issue #73)

Consumed by `app.users.application.password_policy.get_password_policy()`.
Defaults follow OWASP ASVS L1 + NIST 800-63B.

| Field | Type | Default | Validation |
|---|---|---|---|
| `PASSWORD_MIN_LENGTH` | `int` | `12` | 8–72 (bcrypt truncates beyond 72 bytes) |
| `PASSWORD_MAX_LENGTH` | `int` | `128` | 32–1024 |
| `PASSWORD_REQUIRE_COMPLEXITY` | `bool` | `True` | — |
| `PASSWORD_CHECK_COMMON_LIST` | `bool` | `True` | — |
| `PASSWORD_FORBID_USER_INFO` | `bool` | `True` | — |
| `PASSWORD_FORBID_SIMPLE_PATTERNS` | `bool` | `True` | — |
| `PASSWORD_POLICY_RELEASE_DATE` | `str` (ISO date) | `2026-05-23` | grandfathers older `password_set_at` |
| `PASSWORD_BCRYPT_ROUNDS` | `int` | `12` (overlay: `4` in testing) | 4–15 |

### Brute-force protection (Issue #73)

Sliding-window counts of failed logins live in `login_attempts`; lockouts in
`account_lockouts`. Lockout duration grows exponentially up to
`BRUTE_FORCE_LOCKOUT_MAX_SECONDS`. See [`docs/app/SECURITY.md`](SECURITY.md).

| Field | Type | Default | Validation |
|---|---|---|---|
| `BRUTE_FORCE_ENABLED` | `bool` | `True` | — |
| `BRUTE_FORCE_USERNAME_THRESHOLD` | `int` | `5` | 1–1000 |
| `BRUTE_FORCE_USERNAME_WINDOW_SECONDS` | `int` | `900` | 30–86400 |
| `BRUTE_FORCE_LOCKOUT_BASE_SECONDS` | `int` | `900` | 1–604800 |
| `BRUTE_FORCE_LOCKOUT_MAX_SECONDS` | `int` | `86400` | 1–604800 |
| `BRUTE_FORCE_IP_THRESHOLD` | `int` | `20` | 1–1000 |
| `BRUTE_FORCE_IP_WINDOW_SECONDS` | `int` | `300` | 30–86400 |
| `BRUTE_FORCE_DELAY_MS` | `int` | `200` | 0–5000 |

### Reverse-proxy trust (Issue #73)

When `TRUST_PROXY_HEADERS=False` (the default) `X-Forwarded-For` /
`X-Real-IP` are ignored and the brute-force tracker uses
`request.client.host`. When `True`, the headers are honoured **only** if
the immediate peer is in `TRUSTED_PROXIES`.

| Field | Type | Default | Validation |
|---|---|---|---|
| `TRUST_PROXY_HEADERS` | `bool` | `False` | — |
| `TRUSTED_PROXIES` | `str` (comma-separated IPs) | `""` | no CIDR |

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
      a hardening rule was violated; see Section 5.
