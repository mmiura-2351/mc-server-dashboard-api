# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-05-28

Aggregates 106 commits since v0.1.0. Centered on the staged migration to a
hexagonal (Port + Adapter) architecture (Issues #154, #228), broad performance
work, and new observability / security surface.

### Added
- Health and readiness endpoints: `/healthz`, `/readyz`, `/api/v1/health` (#328).
- Structured logging with correlation IDs, JSON/text output, and sensitive-field masking (#330).
- Prometheus metrics export at `/metrics` and `/api/v1/metrics` (health gauges + business metrics) (#344).
- File operation error handling backed by audit logging (#340).
- Optional port, auto-assign, and port discovery endpoints for server creation (#337).
- Actionable error responses for server creation failures (#334).
- Password strength validation and brute-force protection (#333).
- Periodic cleanup of `.pending/` and `.failed/` directories under the backups directory (#317).
- `VisibilityMigrationService` is now invoked at lifespan startup (#315).
- Environment-specific configuration (development / staging / production / testing) with validators (#331).
- Standardized pagination and error response shapes (backward compatible) (#332).
- direnv integration and a minimal Nix flake for reproducible dev environments (#324, #346).
- Release automation via [tagpr](https://github.com/Songmu/tagpr): every merge to `master`
  updates a release PR; merging it tags `vX.Y.Z` and publishes a GitHub Release.
  Bump kind is controlled by the `tagpr:major` / `tagpr:minor` PR labels (defaults to patch).
  See [docs/RELEASING.md](docs/RELEASING.md) §4 (#201, #202, #204).
- `is_stable` is populated correctly for pre-release versions (#356).

### Changed
- **Hexagonal migration (Issue #154 / #228)**: introduced Port + Adapter layering,
  Repository, and UnitOfWork patterns across versions, users, auth, audit, servers,
  backups, groups, templates, files, visibility, and websockets domains.
  Dismantled the aggregated `app/services/` layer
  (#229, #230, #238, #254, #256, #261, #264, #265, #269, #275, #279, #283, #286, #290,
  #300, #301, #303, #304, #305, #306, #308, #309, #311, #313, #316).
- Migrated `AuditService` callsites in auth/users/files to `AuditWriter` DI.
  Legacy `app.audit.router` import path kept for backward compatibility
  (#246, #248, #296, #401).
- Split `app/servers/application/minecraft_server.py` into focused mixins
  (`DaemonProcessMixin`, `PidFileMixin`, `PreflightMixin`, `MonitoringMixin`) (#389).
- Split `app/files/application/file_management_service.py` into focused modules (#388).
- Exposed `broadcast_group_change` to remove a Demeter chain in `GroupService` (#313).

### Removed
- **Templates feature removed in full** (#355). Affected surfaces:
  `POST/GET/PUT/DELETE /api/v1/templates/*`,
  `POST /api/v1/backups/.../restore-with-template`, `Template*` ORM, schemas, and tests.
  Group-as-template use cases now use the existing `is_template` flag on `Group`.
- Removed `app/servers/service.py` shim by migrating the last imports (#310).
- Removed stale `REFACTOR_PLAN.md` and `populate_initial_versions.py` (#402).

### Performance
- HTTP `Cache-Control` headers on read-only list endpoints (#381).
- Explicit SQLAlchemy connection pool config (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
  `DB_POOL_RECYCLE`, `DB_POOL_PRE_PING`) (#380).
- Semaphore concurrency control for backups / WebSocket / file I/O
  (`MAX_CONCURRENT_BACKUPS`, `MAX_CONCURRENT_WEBSOCKETS`, `FILE_IO_SEMAPHORE_LIMIT`) (#383).
- Groups pagination moved from in-memory slicing to SQL `LIMIT/OFFSET` (#379).
- Audit statistics consolidated into a single conditional-aggregation query (#378).
- Audit log count + fetch merged into a single filtered query (#377).
- Replaced `model_validate` with `model_construct` for trusted entity conversions (#376).
- Visibility repository: replaced `NOT IN` subquery with `LEFT JOIN ... IS NULL` (#374).
- Server statistics: replaced per-server `COUNT` loops with `GROUP BY` aggregation (#375).
- Cached parsed `Settings` properties with `functools.cached_property` (#373).
- `MemoryTracker`: removed unused `memory_start` and added a TTL cache (#382).
- Added missing database indexes for hot query paths (#343).
- Test execution time optimization (#335).

### Fixed
- **Security**: sanitize uploaded filename to block path traversal (#403).
- Token revocation on user deactivation via `token_version` claim (#336).
- Reject duplicate email and inactive-user login attempts (#236).
- Cancel and await log-streaming tasks on WebSocket disconnect (#326).
- Mount `visibility_router` and order `/migration/*` before
  `/{resource_type}/{resource_id}` so it matches first (#312, #322).
- TOCTOU fix on `file_history` `version_number` with separate-session writers (#266).
- Restore the `granted=False` `permission_check_denied` audit event (#321).
- Validate the upper bound of version groups and the JAR `download_url` (#358).
- Register the `/validate` endpoint on the unified servers router (#339).
- Avoid `importlib.reload(app.core.config)` in concurrency tests (#385).
- Audit: dialect-aware severity filter for SQLite (#251).
- Audit: warn when `command.ip_address` differs from the request tracker (#250).
- Enforce upload size limit, encoding validator, and rename conflict 409 (#345).

### Documentation
- Added [docs/DAEMON_MIGRATION.md](docs/DAEMON_MIGRATION.md) — a 10-chapter migration
  guide retroactively covering the breaking changes in PR #60 (daemon architecture,
  RCON, process persistence). Documents 23 `DAEMON_*` env vars and the new defaults
  for `KEEP_SERVERS_ON_SHUTDOWN` / `AUTO_SYNC_ON_STARTUP` (#342).
- Updated [docs/DAEMON_PROCESS_ARCHITECTURE.md](docs/DAEMON_PROCESS_ARCHITECTURE.md):
  linked the Migration chapter to the new guide, corrected the PID filename to
  `server.pid`, and replaced non-existent endpoints
  (`/api/v1/servers/shutdown-all`, `/api/v1/processes/*`,
  `/api/v1/servers/{id}/process-info`) with the real paths.
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md): added cross-references to the
  `DAEMON_*` configuration.
- [README.md](README.md): added links to the Daemon Migration Guide and the
  Configuration Reference, plus a pre-PR-#60 upgrade warning in the Production
  Deployment section.
- Documented the test hierarchy (unit / integration / infrastructure) policy in
  [docs/TESTING.md](docs/TESTING.md) (#205).
- Documented audit and real-time event emission patterns in ARCHITECTURE.md (#387).

### Infrastructure
- Enabled mypy in pre-commit with a relaxed config (#220).
- Split pre-commit / pre-push / CI test scopes into three layers (#208).
- Pinned Temurin 21 in CI and nightly workflows (#214).
- Migrated pytest config to `pyproject.toml` and fixed an xdist race (#215).
- Annotated Java-dependent integration tests with `@pytest.mark.requires_java`
  and fixed two pollution sources (#212).
- Disabled the uv cache for the tagpr release-tag run to avoid CI failures (#404).

### Dependencies
- Bumped Python to the latest 3.13.x patch (#391).
- Raised starlette floor to the latest patch (#392).
- Raised fastapi floor to 0.136 (#393).
- Updated pydantic and pydantic-settings to the latest 2.x (#394).
- Updated SQLAlchemy to the latest 2.0.x (>=2.0.49) (#399).

## [0.1.0] - 2026-05-16

Initial release. This release pins the 2026-05-16 snapshot of the repository as
`v0.1.0`. Subsequent releases follow the procedure in
[docs/RELEASING.md](docs/RELEASING.md).

### Added
- **Java version compatibility management** — multi-version Java support for
  Minecraft servers: automatic version selection based on the Minecraft version,
  Java 8 / 16 / 17 / 21 with configurable paths
  (`JAVA_8_PATH`, `JAVA_16_PATH`, `JAVA_17_PATH`, `JAVA_21_PATH`), OpenJDK discovery
  in common installation paths with vendor detection, custom discovery paths via
  `JAVA_DISCOVERY_PATHS`, and detailed compatibility error messages during server
  creation and startup. See [Java Compatibility Guide](docs/java-compatibility.md).

### Changed
- Server creation now runs a pre-flight Java compatibility check.
- Improved error handling for Java-related startup failures.
- `MinecraftServerManager` now uses version-specific Java executables.
- Simplified version management architecture by removing unnecessary complexity.

### Fixed
- **Version management timeout issues**: identified that systemd `IPAddressAllow`
  restrictions were blocking external API calls, then simplified timeout handling
  (31.7-minute timeouts reduced to 60 seconds). Improved HTTP client config with
  proper connect/read timeouts, added `User-Agent` and `Accept-Encoding` headers,
  fixed gzip decoding for the Forge Maven API. Removed ~780 lines of unnecessary
  timeout handling code; all 31 version-manager unit tests pass.

### Documentation
- Added the [Java Compatibility Guide](docs/java-compatibility.md).
- Updated README.md with Java configuration examples.
- Extended the API reference with Java compatibility information.
- Updated architecture docs to include `JavaCompatibilityService`.

## Previous Versions

Previous changes are tracked in git commit history. This changelog was started
with the Java compatibility feature implementation.
