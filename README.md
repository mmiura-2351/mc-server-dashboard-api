# Minecraft Server Dashboard API

A comprehensive FastAPI-based backend system for managing multiple Minecraft servers with advanced automation, real-time monitoring, and extensive file management capabilities.

## Features

- **Multi-Server Management** - Create and manage multiple Minecraft servers with process monitoring
- **Java Version Compatibility** - Automatic Java version selection and validation for different Minecraft versions
- **User Authentication & Authorization** - JWT-based authentication with three-tier role system (User/Operator/Admin)
- **Real-time Monitoring** - WebSocket-based live server status, log streaming, and console interaction
- **Dynamic Player Groups** - OP/whitelist groups with multi-server attachment and priority levels
- **Automated Backup System** - Database-persistent scheduling with metadata tracking and restoration
- **Advanced File Management** - Secure file operations with version history, encoding detection, and rollback
- **Template System** - Reusable server configurations with cloning capabilities
- **Performance Monitoring** - Request tracking, metrics collection, and service health monitoring
- **Audit Logging** - Comprehensive activity tracking for security and compliance

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
   SECRET_KEY=your-secret-key
   DATABASE_URL=sqlite:///./app.db
   CORS_ORIGINS=["http://localhost:3000"]
   
   # Java Configuration (Optional - for specific Java paths)
   JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk/bin/java
   JAVA_16_PATH=/usr/lib/jvm/java-16-openjdk/bin/java
   JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk/bin/java
   JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk/bin/java
   JAVA_DISCOVERY_PATHS=/opt/java,/usr/local/java
   ```
4. Start the application:
   ```bash
   uv run fastapi dev
   ```

The API will be available at `http://localhost:8000` with interactive documentation at `/docs`.

## Documentation

- **Interactive API docs**: `http://localhost:8000/docs`
- **[API Reference](docs/api-reference.md)** - Complete endpoint documentation
- **[Java Compatibility Guide](docs/java-compatibility.md)** - Multi-version Java setup and configuration
- **[Architecture](docs/architecture.md)** - System design and architecture
- **[Database Schema](docs/database.md)** - Database models and relationships
- **[Development Guide](docs/development.md)** - Testing, coding standards, and deployment

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