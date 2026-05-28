# Minecraft Server Dashboard API

A comprehensive FastAPI-based backend system for managing multiple Minecraft servers with advanced automation, real-time monitoring, and extensive file management capabilities.

## Features

### 🖥️ Server Management
- **Daemon Process Architecture** - True process detachment with double-fork technique for server persistence
- **Multi-Server Management** - Create and manage multiple Minecraft servers with advanced process monitoring
- **Auto-Recovery System** - Automatic server restoration across API restarts using PID file management
- **Java Version Compatibility** - Automatic Java version selection and validation for different Minecraft versions

### 🔐 Security & Authentication
- **User Authentication & Authorization** - JWT-based authentication with three-tier role system (User/Operator/Admin)
- **Security Hardening** - Protection against path traversal, command injection, and memory exhaustion attacks
- **Process Isolation** - Secure daemon processes with resource limits and signal isolation
- **Audit Logging** - Comprehensive activity tracking for security and compliance

### ⚡ Real-time Operations
- **RCON Integration** - Real-time command execution via Remote Console protocol
- **Live Monitoring** - WebSocket-based live server status, log streaming, and console interaction
- **Group Operations** - Dynamic OP/whitelist groups with real-time player management via RCON
- **Observability** - Structured logs with correlation IDs, Prometheus metrics (`/metrics`), Kubernetes liveness/readiness probes (`/healthz`, `/readyz`)

### 💾 Data Management
- **Automated Backup System** - Database-persistent scheduling with metadata tracking and restoration
- **Advanced File Management** - Secure file operations with version history, encoding detection, and rollback
- **Database Integration** - Seamless sync between filesystem state and database records

## Quick Start

### Prerequisites
- uv package manager (automatically manages Python 3.13+ requirement)
- [`just`](https://github.com/casey/just) task runner — install via one of:
  - `cargo install just`
  - `brew install just`
  - `apt install just` (Debian/Ubuntu 22.10+)
  - or download a prebuilt binary from the [just releases page](https://github.com/casey/just/releases)
- Java Runtime Environment (for Minecraft servers)
  - Supports multiple Java versions for different Minecraft versions
  - OpenJDK 8, 16, 17, or 21 recommended

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   uv sync
   ```
3. Create a `.env` file:
   ```env
   # Required Settings
   SECRET_KEY=your-secret-key           # ≥ 32 chars, no weak prefixes
   DATABASE_URL=sqlite:///./app.db

   # CORS_ORIGINS is a comma-separated list (NOT a JSON array)
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

   # Java Configuration (Optional - for specific Java paths)
   JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk/bin/java
   JAVA_16_PATH=/usr/lib/jvm/java-16-openjdk/bin/java
   JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk/bin/java
   JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk/bin/java
   JAVA_DISCOVERY_PATHS=/opt/java,/usr/local/java

   # All other knobs (DAEMON_*, DB_POOL_*, PASSWORD_*, BRUTE_FORCE_*,
   # MAX_CONCURRENT_*, FILE_MAX_UPLOAD_BYTES, …) have safe defaults.
   # Full reference: docs/CONFIGURATION.md
   ```
4. Start the application:
   ```bash
   uv run fastapi dev
   ```

The API will be available at `http://localhost:8000` with interactive documentation at `/docs`.

### Optional: Nix-based development environment

For a fully reproducible system-level toolchain (Python 3.13, `uv`,
JDK 21, `just`, `pre-commit`, `git`), the repository ships a minimal
[`flake.nix`](./flake.nix). This is **strictly opt-in** — the standard
`uv sync` workflow above continues to work without any of the steps
below, so non-Nix contributors are unaffected.

**Prerequisites**: install [Nix](https://nixos.org/download) with
flakes enabled (the [Determinate Systems installer](https://zero-to-nix.com/start/install)
enables flakes by default).

**Manual entry** — enter the devShell on demand:

```bash
nix develop
uv sync --group dev
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

**Automatic with direnv** (recommended) — `cd` into the repo and the
devShell loads itself; `cd` out and it unloads:

```bash
# one-time install of direnv + nix-direnv, then in this directory:
direnv allow
```

`.envrc` (committed) contains `use flake`, which delegates activation
to [`nix-direnv`](https://github.com/nix-community/nix-direnv). Place
host-specific overrides in `.envrc.local` (gitignored).

**Relationship to the standard workflow**: Nix manages the *system*
toolchain (interpreter, JDK, CLI utilities); `uv` continues to manage
Python *dependencies* inside `.venv`. The two layers are independent,
so you can adopt or drop Nix without touching `pyproject.toml` /
`uv.lock`.

## Documentation

### 📚 Core Documentation
- **Interactive API docs**: `http://localhost:8000/docs`
- **[Daemon Process Architecture](docs/DAEMON_PROCESS_ARCHITECTURE.md)** - Process management and persistence system
- **[Daemon Architecture Migration Guide](docs/DAEMON_MIGRATION.md)** - Upgrading existing deployments from pre-PR-#60 to the daemon architecture (breaking changes, checklist, rollback)
- **[Configuration Reference](docs/CONFIGURATION.md)** - Full `Settings` reference and per-environment overlays
- **[RCON Integration](docs/RCON_INTEGRATION.md)** - Real-time command execution system
- **[Java Compatibility Guide](docs/java-compatibility.md)** - Multi-version Java setup and configuration

### 🏗️ System Architecture  
- **[Architecture](docs/ARCHITECTURE.md)** - Target hexagonal architecture and the standards new code must follow (see §17.4 for the current per-domain migration status)
- **[Architecture (Historical)](docs/ARCHITECTURE_LEGACY.md)** - Pre-refactor snapshot, archived for context
- **[Database Schema](docs/database.md)** - Database models and relationships
- **[API Reference](docs/api-reference.md)** - Complete endpoint documentation
- **[Development Guide](docs/development.md)** - Testing, coding standards, and deployment
- **[Testing Policy](docs/TESTING.md)** - Test hierarchy (unit / integration / infrastructure), markers, and CI scopes
- **[Dependency Policy](docs/DEPENDENCIES.md)** - Pinning style, lockfile, supply-chain cooldown

### 🔧 Configuration
The canonical configuration reference is [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md): every env var, default, validator, and per-environment overlay. Topic-specific cross-references:
- **Daemon process settings** — see [DAEMON_PROCESS_ARCHITECTURE.md](docs/DAEMON_PROCESS_ARCHITECTURE.md) for the architectural context (env vars themselves are in [CONFIGURATION.md § Daemon process settings](docs/CONFIGURATION.md#daemon-process-settings-daemon_))
- **RCON behaviour** — see [RCON_INTEGRATION.md](docs/RCON_INTEGRATION.md)
- **Security policy** (passwords, brute-force protection, proxy trust) — see [SECURITY.md](docs/SECURITY.md)
- **Logging** (structured JSON, correlation IDs, masking) — see [LOGGING.md](docs/LOGGING.md)

## Development

Recipes are managed with [`just`](https://github.com/casey/just). Run `just` (no args) to list all available recipes.

### Quick Commands

| Command | Description |
|---------|-------------|
| `just dev` | Start development server with auto-reload |
| `just test` | Run test suite |
| `just lint` | Check code quality |
| `just format` | Format code |
| `just install` | Install dependencies and setup environment |

### Direct Commands

| Command | Description |
|---------|-------------|
| `uv run fastapi dev` | Start development server |
| `uv run pytest` | Run tests |
| `uv run pytest --timeout=300000` | Run full test suite with extended timeout |
| `uv run ruff check app/` | Check code quality |
| `uv run ruff format app/` | Format code |
| `just coverage` | Generate coverage report |

### Development Scripts

| Script | Description |
|--------|-------------|
| `just dev-start` | Start development server with monitoring |
| `just dev-stop` | Stop development server |
| `just dev-status` | Show development server status |
| `just dev-logs` | View development logs |

### Alternative: Direct Script Execution

| Script | Description |
|--------|-------------|
| `./scripts/dev-start.sh start` | Start development server with monitoring |
| `./scripts/dev-start.sh stop` | Stop development server |
| `./scripts/dev-start.sh status` | Show development server status |
| `./scripts/dev-start.sh logs` | View development logs |

## Production Deployment

> **Upgrading from a pre-PR-#60 deployment?** The daemon architecture
> introduces breaking changes (PID files on disk, RCON auto-enabled,
> `KEEP_SERVERS_ON_SHUTDOWN=True` by default, Unix-only). See
> [docs/DAEMON_MIGRATION.md](docs/DAEMON_MIGRATION.md) **before** pulling
> the new code on a host that has running Minecraft servers.

### Quick Deployment

```bash
# Using just (recommended)
just deploy

# Or direct script execution
./scripts/deploy.sh
```

### Production Management

| Command | Description |
|---------|-------------|
| `just service-start` | Start production service |
| `just service-stop` | Stop production service |
| `just service-restart` | Restart production service |
| `just service-status` | Show service status |
| `just service-logs` | View service logs |
| `just service-enable` | Enable auto-start on boot |
| `just service-disable` | Disable auto-start on boot |

### Alternative: Direct Script Execution

| Command | Description |
|---------|-------------|
| `./scripts/service-manager.sh start` | Start production service |
| `./scripts/service-manager.sh stop` | Stop production service |
| `./scripts/service-manager.sh restart` | Restart production service |
| `./scripts/service-manager.sh status` | Show service status |
| `./scripts/service-manager.sh logs` | View service logs |

### Manual Production Setup

See [comprehensive deployment guide](deployment/docs/en/DEPLOYMENT.md) for detailed production setup instructions including:

- Prerequisites and system requirements
- Nginx reverse proxy configuration
- SSL/TLS setup with Let's Encrypt
- Security hardening
- Monitoring and maintenance
- Troubleshooting guide

## Integration with Frontend

This API is designed to work with the [Minecraft Server Dashboard UI](../mc-server-dashboard-ui/) frontend. For complete setup:

1. Deploy this API backend
2. Deploy the frontend UI
3. Configure nginx reverse proxy (optional but recommended)

The deployment scripts and documentation are aligned with the frontend for seamless integration.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
