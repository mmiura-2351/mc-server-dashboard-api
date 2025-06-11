# System Overview

## Introduction

The Minecraft Server Dashboard API is a comprehensive FastAPI-based backend system for managing multiple Minecraft servers. It provides user authentication, role-based access control, real-time monitoring, automated backups, and complete server lifecycle management.

## Key Features

### 🖥️ Multi-Server Management
- Create and manage multiple Minecraft servers simultaneously
- Support for Vanilla, Paper, Spigot, Forge, and Fabric server types
- Version support from Minecraft 1.8 to 1.21.5
- Real-time server status monitoring and control

### 👥 Player Management
- Dynamic OP and whitelist group management
- Multi-server group attachment with priority levels
- Minecraft API integration for player data validation
- Centralized player permission management

### 💾 Backup System
- Automated scheduled backups
- Manual backup creation with metadata
- Server restoration from backups
- Template creation from backups

### 📁 File Management
- Secure file operations within server directories
- File version history tracking
- Upload/download capabilities
- File search and batch operations

### 🔐 Security & Authentication
- JWT-based authentication with refresh tokens
- Three-tier role system (User, Operator, Admin)
- Resource ownership validation
- Comprehensive audit logging

### 🔌 Real-time Features
- WebSocket-based server log streaming
- Live server status updates
- System-wide notifications
- Real-time console interaction

## Architecture

### Technology Stack
- **Framework**: FastAPI (Python 3.13+)
- **Database**: SQLite with SQLAlchemy ORM
- **Authentication**: JWT tokens with PyJWT
- **Real-time**: WebSockets
- **Process Management**: Python subprocess
- **File Operations**: aiofiles for async I/O
- **Package Management**: uv

### System Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Web Client    │────▶│   FastAPI App   │────▶│    Database     │
│   (Frontend)    │◀────│    (Backend)    │◀────│    (SQLite)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ├── Services Layer
                               │   ├── MinecraftServer
                               │   ├── BackupService
                               │   ├── GroupService
                               │   └── FileService
                               │
                               └── Infrastructure
                                   ├── File System
                                   ├── Process Manager
                                   └── WebSocket Manager
```

### Core Components

#### 1. Application Layer (`app/`)
- **Routers**: HTTP endpoint definitions
- **Schemas**: Pydantic models for validation
- **Dependencies**: Dependency injection setup

#### 2. Business Logic Layer (`app/services/`)
- **MinecraftServer**: Server process management
- **BackupService**: Backup operations
- **BackupScheduler**: Automated backup scheduling
- **GroupService**: Player group management
- **FileManagementService**: File operations
- **WebSocketService**: Real-time communication

#### 3. Data Layer
- **Models**: SQLAlchemy ORM models
- **Database**: SQLite with migrations
- **File Storage**: Local filesystem for servers and backups

#### 4. Security Layer
- **Authentication**: JWT token management
- **Authorization**: Role-based access control
- **Validation**: Input sanitization and path validation

## Data Model

### Core Entities
1. **Users**: User accounts with roles and permissions
2. **Servers**: Minecraft server instances
3. **Groups**: Player permission groups (OP/whitelist)
4. **Backups**: Server backup records
5. **Templates**: Reusable server configurations
6. **FileEditHistory**: File version tracking
7. **AuditLogs**: System activity logging

### Relationships
- Users own Servers, Groups, and Templates
- Servers can have multiple Backups
- Groups can be attached to multiple Servers
- Templates can be used to create new Servers
- All actions are tracked in AuditLogs

## API Design

### RESTful Principles
- Resource-oriented URLs
- HTTP methods for operations (GET, POST, PUT, DELETE)
- Consistent response formats
- Proper HTTP status codes

### API Structure
```
/api/v1/
├── /auth         - Authentication endpoints
├── /users        - User management
├── /servers      - Server operations
├── /groups       - Group management
├── /backups      - Backup operations
├── /templates    - Template management
├── /files        - File operations
└── /ws           - WebSocket connections
```

## Security Model

### Authentication Flow
1. User registers and awaits admin approval
2. Admin approves user account
3. User logs in and receives JWT tokens
4. Tokens used for API authentication
5. Refresh token for token renewal

### Authorization Levels
- **User**: Basic access to assigned resources
- **Operator**: Can create and manage servers
- **Admin**: Full system access

### Security Features
- Password hashing with bcrypt
- JWT tokens with expiration
- Path traversal protection
- Input validation and sanitization
- Rate limiting on sensitive endpoints

## Development

### Environment Setup
```bash
# Install dependencies
uv sync

# Start development server
uv run fastapi dev

# Run tests
uv run pytest

# Code quality checks
uv run ruff check app/
uv run black app/
```

### Configuration
Environment variables in `.env`:
```
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///./app.db
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

## Use Cases Coverage

The system implements 46 comprehensive use cases:

### Server Management (UC1-11)
- Server creation, configuration, deletion
- Start, stop, restart operations
- Console command execution
- Status monitoring

### Player Management (UC12-19)
- Group creation and management
- Player addition/removal
- Server attachment/detachment
- Dynamic configuration updates

### Monitoring (UC20)
- Real-time server status
- Log streaming
- System notifications

### Backup Management (UC21-28)
- Manual and scheduled backups
- Backup restoration
- Template creation from backups
- Backup statistics

### File Management (UC29-37)
- File CRUD operations
- Directory management
- File search
- Upload/download
- Version history

### Account Management (UC38-42)
- User registration
- Profile management
- Password changes
- Account deletion

### Administrative Functions (UC43-46)
- User approval
- Role management
- System synchronization
- Cache management

## Performance Considerations

### Optimization Strategies
- Database indexing for frequent queries
- Pagination for large datasets
- Async I/O for file operations
- Connection pooling for WebSockets
- JAR file caching for server downloads

### Scalability
- Stateless API design
- Horizontal scaling ready
- Database optimization
- Efficient file storage

## Monitoring & Maintenance

### System Health
- Server process monitoring
- Database connection checks
- File system space monitoring
- Backup verification

### Logging
- Application logs
- Audit logs for security
- Error tracking
- Performance metrics

## Future Enhancements

Potential areas for expansion:
- Plugin management system
- Advanced server metrics
- Cluster support
- External storage backends
- Advanced scheduling features