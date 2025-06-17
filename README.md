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
- Python 3.13+
- uv package manager
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
- **[RCON Integration](docs/RCON_INTEGRATION.md)** - Real-time command execution system
- **[Java Compatibility Guide](docs/java-compatibility.md)** - Multi-version Java setup and configuration

### 🏗️ System Architecture  
- **[Architecture](docs/architecture.md)** - System design and architecture
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

| Command | Description |
|---------|-------------|
| `uv run fastapi dev` | Start development server |
| `uv run pytest` | Run tests |
| `uv run pytest --timeout=300000` | Run full test suite with extended timeout |
| `uv run ruff check app/` | Check code quality |
| `uv run black app/` | Format code |
| `uv run coverage run -m pytest && uv run coverage report` | Generate coverage report |

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.