# Minecraft Server Dashboard API

A FastAPI-based backend API for managing multiple Minecraft servers through a web interface.

## Features

- **Multi-Server Management** - Create and manage multiple Minecraft servers
- **User Authentication** - Secure login system with role-based permissions
- **Real-time Monitoring** - Live server status and console log streaming
- **Player Groups** - Manage whitelists and operator lists across servers
- **Automated Backups** - Schedule and restore server backups
- **File Management** - Browse and edit server files through the API

## Quick Start

### Prerequisites
- Python 3.13+
- uv package manager

### Installation

1. Clone the repository
2. Create a `.env` file:
   ```env
   SECRET_KEY=your-secret-key
   DATABASE_URL=sqlite:///./app.db
   ```
3. Start the application:
   ```bash
   uv run fastapi dev
   ```

The API will be available at `http://localhost:8000` with documentation at `/docs`.

## API Documentation

- Interactive API docs: `http://localhost:8000/docs`
- [API Reference](docs/api-reference.md) - Complete endpoint documentation
- [System Overview](docs/system-overview.md) - Architecture and concepts

## Development

| Command | Description |
|---------|-------------|
| `uv run fastapi dev` | Start development server |
| `uv run pytest` | Run tests |
| `uv run ruff check app/` | Check code quality |
| `uv run black app/` | Format code |

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.