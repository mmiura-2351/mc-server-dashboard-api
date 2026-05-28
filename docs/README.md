# Documentation Index

This directory contains the long-form documentation for the Minecraft Server
Dashboard API. The top-level [`README.md`](../README.md) covers the elevator
pitch, quick start, and the most common commands; everything that needs more
than a paragraph lives here.

Docs are split by intent:

- **[`app/`](#application-docs--app)** — how the running system works.
  Architecture, persisted data, HTTP surface, runtime configuration,
  cross-cutting behaviour (logging, security, RCON, Java compatibility).
  Read these when reasoning about the application itself.
- **[`dev/`](#development-docs--dev)** — how to work *on* the application.
  Development workflow, testing layers, release procedure, dependency
  policy, one-time upgrade guides. Read these when changing the codebase
  or operating a deployment.

If you are not sure where to look, the [Quick lookup](#quick-lookup) table
below is the fastest way to land in the right file.

---

## Application docs (`app/`)

The state and behaviour of the running system. The canonical entry point is
[`ARCHITECTURE.md`](app/ARCHITECTURE.md); everything else either zooms into a
specific concern or documents a swappable subsystem.

| Doc | What it covers |
|---|---|
| [`ARCHITECTURE.md`](app/ARCHITECTURE.md) | Target hexagonal (Ports & Adapters) architecture: layer rules, dependency directions, per-domain structure, cross-cutting Ports, the audit + real-time event patterns, and the per-domain migration snapshot (Section 17.4) |
| [`ARCHITECTURE_LEGACY.md`](app/ARCHITECTURE_LEGACY.md) | Archived snapshot of the pre-Issue-#149 implementation. Historical context only — not maintained against current code |
| [`API_REFERENCE.md`](app/API_REFERENCE.md) | Every HTTP endpoint: path, method, request/response shapes, auth requirements. WebSocket endpoints, health/readiness probes, Prometheus metrics |
| [`CONFIGURATION.md`](app/CONFIGURATION.md) | Canonical reference for `app.core.config.Settings` and `DaemonConfig`. Every env var, default, validator, and per-environment overlay (development / testing / staging / production) |
| [`DATABASE.md`](app/DATABASE.md) | SQLAlchemy schema: tables, columns, foreign keys, indexes, cascade rules, enumerations |
| [`DAEMON_PROCESS_ARCHITECTURE.md`](app/DAEMON_PROCESS_ARCHITECTURE.md) | Daemon process lifecycle: double-fork, PID-file persistence, monitoring, RCON integration, recovery on startup |
| [`RCON_INTEGRATION.md`](app/RCON_INTEGRATION.md) | RCON protocol implementation, the `MinecraftServerManager.send_command()` primary path, and the `RealTimeServerCommandService` helper |
| [`JAVA_COMPATIBILITY.md`](app/JAVA_COMPATIBILITY.md) | Multi-version Java support: version selection by Minecraft version, discovery paths, `JAVA_*` env vars |
| [`LOGGING.md`](app/LOGGING.md) | Structured logging: JSON vs text output, correlation IDs, sensitive-field masking |
| [`SECURITY.md`](app/SECURITY.md) | Authentication/password/brute-force policy, reverse-proxy trust model |

## Development docs (`dev/`)

How to develop on and operate the codebase.

| Doc | What it covers |
|---|---|
| [`DEVELOPMENT.md`](dev/DEVELOPMENT.md) | Day-to-day developer workflow: setup, common `just` recipes, debugging tips |
| [`TESTING.md`](dev/TESTING.md) | Canonical test policy: unit / integration / infrastructure hierarchy, `@pytest.mark.slow` and `@pytest.mark.requires_java` usage, CI scopes |
| [`RELEASING.md`](dev/RELEASING.md) | SemVer policy, the tagpr release-PR flow, version bump labels |
| [`DEPENDENCIES.md`](dev/DEPENDENCIES.md) | Version pinning style, `uv.lock` operations, Dependabot policy, the 7-day supply-chain cooldown |
| [`DAEMON_MIGRATION.md`](dev/DAEMON_MIGRATION.md) | One-time upgrade guide for deployments still on the pre-PR-#60 architecture (breaking changes, pre-upgrade checklist, rollback) |

---

## Quick lookup

If you are looking for…

| Topic | Start here |
|---|---|
| How a request flows through the codebase | [`app/ARCHITECTURE.md`](app/ARCHITECTURE.md) |
| What endpoints exist and how to call them | [`app/API_REFERENCE.md`](app/API_REFERENCE.md) |
| What an env var does or what its default is | [`app/CONFIGURATION.md`](app/CONFIGURATION.md) |
| The shape of a table or a column rename | [`app/DATABASE.md`](app/DATABASE.md) |
| Why a Minecraft server is or isn't starting (Java, daemon, RCON) | [`app/JAVA_COMPATIBILITY.md`](app/JAVA_COMPATIBILITY.md), [`app/DAEMON_PROCESS_ARCHITECTURE.md`](app/DAEMON_PROCESS_ARCHITECTURE.md), [`app/RCON_INTEGRATION.md`](app/RCON_INTEGRATION.md) |
| Password / brute-force / proxy-trust policy | [`app/SECURITY.md`](app/SECURITY.md) |
| Log format, correlation IDs, sensitive-field masking | [`app/LOGGING.md`](app/LOGGING.md) |
| How to add a new test (and where it goes) | [`dev/TESTING.md`](dev/TESTING.md) |
| How a release gets cut | [`dev/RELEASING.md`](dev/RELEASING.md) |
| How to bump a dependency safely | [`dev/DEPENDENCIES.md`](dev/DEPENDENCIES.md) |
| How to upgrade a host still on the old (pre-#60) daemon model | [`dev/DAEMON_MIGRATION.md`](dev/DAEMON_MIGRATION.md) |
| Standing rules for working in this repo (commit style, PR flow, language policy) | [`../CLAUDE.md`](../CLAUDE.md) |
| What changed in each release | [`../CHANGELOG.md`](../CHANGELOG.md) |

---

## Conventions

- **Language**: all documentation is English (see Rule 11 in
  [`../CLAUDE.md`](../CLAUDE.md)).
- **Filenames**: `UPPERCASE_SNAKE_CASE.md`. The two subdirectory names
  (`app/`, `dev/`) are lowercase.
- **Section references**: write `Section 4.3` (or `section 4.3` mid-sentence).
  Do not use the section-mark glyph — it is uncommon on US keyboards and
  noisy to search for.
- **Cross-links**: use relative paths
  (`[CONFIGURATION.md](CONFIGURATION.md)` within the same subdirectory,
  `[CONFIGURATION.md](../app/CONFIGURATION.md)` across subdirectories).
