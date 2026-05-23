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
- **Performance Monitoring** - Request tracking, metrics collection, and service health monitoring

### 💾 Data Management
- **Automated Backup System** - Database-persistent scheduling with metadata tracking and restoration
- **Advanced File Management** - Secure file operations with version history, encoding detection, and rollback
- **Template System** - Reusable server configurations with cloning capabilities
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
   SECRET_KEY=your-secret-key
   DATABASE_URL=sqlite:///./app.db
   CORS_ORIGINS=["http://localhost:3000"]

   # Java Configuration (Optional - for specific Java paths)
   JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk/bin/java
   JAVA_16_PATH=/usr/lib/jvm/java-16-openjdk/bin/java
   JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk/bin/java
   JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk/bin/java
   JAVA_DISCOVERY_PATHS=/opt/java,/usr/local/java

   # Daemon Process Configuration (Optional - defaults provided)
   DAEMON_MODE=double_fork                    # Process creation method
   DAEMON_ENABLE_PERSISTENCE=true            # Enable process persistence
   DAEMON_ENABLE_MONITORING=true             # Enable process monitoring
   DAEMON_MONITORING_INTERVAL=5              # Monitor every 5 seconds
   DAEMON_ENABLE_RCON=true                   # Enable real-time commands
   DAEMON_ENABLE_AUTO_RECOVERY=true          # Enable auto-recovery

   # See full configuration options in docs/DAEMON_PROCESS_ARCHITECTURE.md
   ```
4. Start the application:
   ```bash
   uv run fastapi dev
   ```

The API will be available at `http://localhost:8000` with interactive documentation at `/docs`.

## Documentation

### 📚 Core Documentation
- **Interactive API docs**: `http://localhost:8000/docs`
- **[Daemon Process Architecture](docs/DAEMON_PROCESS_ARCHITECTURE.md)** - Process management and persistence system
- **[Daemon Architecture Migration Guide](docs/DAEMON_MIGRATION.md)** - Upgrading existing deployments from pre-PR-#60 to the daemon architecture (breaking changes, checklist, rollback)
- **[Configuration Reference](docs/CONFIGURATION.md)** - Full `Settings` reference and per-environment overlays
- **[RCON Integration](docs/RCON_INTEGRATION.md)** - Real-time command execution system
- **[Java Compatibility Guide](docs/java-compatibility.md)** - Multi-version Java setup and configuration

### 🏗️ System Architecture  
- **[Architecture](docs/ARCHITECTURE.md)** - Target architecture and standards for new code
- **[Architecture (Historical)](docs/ARCHITECTURE_LEGACY.md)** - Pre-refactor system design (kept for context)
- **[Database Schema](docs/database.md)** - Database models and relationships
- **[API Reference](docs/api-reference.md)** - Complete endpoint documentation
- **[Development Guide](docs/development.md)** - Testing, coding standards, and deployment

### 🔧 Configuration
All configuration options are documented in the respective architecture guides:
- **Daemon Process Settings** - See [DAEMON_PROCESS_ARCHITECTURE.md](docs/DAEMON_PROCESS_ARCHITECTURE.md#configuration)
- **RCON Configuration** - See [RCON_INTEGRATION.md](docs/RCON_INTEGRATION.md#configuration)
- **Security Settings** - Environment variables for security hardening
- **Performance Tuning** - Resource limits and monitoring intervals

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
