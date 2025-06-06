# Minecraft Server Dashboard API

A comprehensive FastAPI-based backend for managing multiple Minecraft servers with user authentication, role-based access control, and real-time monitoring capabilities.

## 🚀 Features

- **Multi-Server Management** - Manage multiple Minecraft servers simultaneously
- **User Authentication** - JWT-based authentication with role-based access control
- **Real-time Monitoring** - WebSocket-based server status and log streaming
- **Player Management** - OP/Whitelist group management with dynamic server attachment
- **Backup System** - Automated and manual backup creation with restoration capabilities
- **Template System** - Reusable server configurations and templates
- **File Management** - Complete file operations within server directories
- **RESTful API** - Clean, consistent API design following REST principles

## 📚 Documentation

- [**System Overview**](docs/system-overview.md) - Complete system architecture and feature overview
- [**API Reference**](docs/api-reference.md) - Comprehensive API endpoint documentation
- [**Database Schema**](docs/database-schema.md) - Database structure and relationships
- [**Requirements**](docs/requirements.md) - Detailed functional requirements (UC1-46)

## 🛠️ Development

### Prerequisites

- Python 3.11+
- uv package manager

### Quick Start

1. Clone the repository
2. Create `.env` file with required variables:
   ```env
   SECRET_KEY=your-secret-key
   DATABASE_URL=sqlite:///./app.db
   ```
3. Install dependencies and start the application:
   ```bash
   uv run fastapi dev
   ```

### Development Commands

| Task              | Command                       |
|-------------------|-------------------------------|
| Start application | `uv run fastapi dev`          |
| Lint code         | `uv run ruff check app/`      |
| Format code       | `uv run black app/`           |
| Run tests         | `uv run pytest`               |
| Run single test   | `uv run pytest tests/test_filename.py::test_function_name` |
| Check code coverage | `uv run coverage run -m pytest && uv run coverage report` |

## 🏗️ Architecture

### Technology Stack
- **Framework**: FastAPI (Python)
- **Database**: SQLite with SQLAlchemy ORM
- **Authentication**: JWT token-based authentication
- **Real-time Communication**: WebSocket
- **File Management**: Local filesystem
- **Process Management**: Python subprocess

### Core Structure
```
app/
├── main.py           # FastAPI application entry point
├── core/             # Core configuration and database
├── auth/             # Authentication system
├── users/            # User management
├── servers/          # Server management
├── groups/           # Group management
├── backups/          # Backup system
├── templates/        # Template system
├── files/            # File management
├── websockets/       # WebSocket communication
└── services/         # Business logic layer
```

## 🔐 Security Features

- **JWT Authentication** - Secure token-based authentication
- **Role-Based Access Control** - Admin/Operator/User permission levels
- **Resource Ownership** - Users can only access their own resources
- **File Path Validation** - Protection against directory traversal attacks
- **Password Security** - bcrypt hashing for password storage
- **Input Validation** - Comprehensive request validation using Pydantic

## 📊 API Overview

All API endpoints use the `/api/v1/` prefix and follow RESTful conventions:

- **Authentication**: `/api/v1/auth/*` - User authentication and registration
- **Users**: `/api/v1/users/*` - User management (admin only)
- **Servers**: `/api/v1/servers/*` - Server creation and management
- **Groups**: `/api/v1/groups/*` - Player group management
- **Backups**: `/api/v1/backups/*` - Backup operations
- **Templates**: `/api/v1/templates/*` - Template management
- **Files**: `/api/v1/files/*` - File operations
- **WebSocket**: `/api/v1/ws/*` - Real-time communication

## 🧪 Testing

The project includes comprehensive test coverage for all major features:

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run coverage run -m pytest && uv run coverage report

# Run specific test file
uv run pytest tests/test_server_router.py -v
```

## 🎯 Use Cases Coverage

This system implements 46 use cases covering:

- **UC1-7**: Server Management
- **UC8-11**: Server Operations
- **UC12-19**: Player Management
- **UC20**: Monitoring
- **UC21-28**: Backup Management
- **UC29-37**: File Management
- **UC38-42**: Account Management
- **UC43-46**: Administrative Functions

## 🔒 LICENSE
This project is licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.
