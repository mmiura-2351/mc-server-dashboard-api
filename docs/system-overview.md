# System Overview

## Introduction

The Minecraft Server Dashboard API is a production-ready FastAPI-based backend system for managing multiple Minecraft servers with enterprise-grade features. It provides JWT authentication, three-tier role-based access control, real-time WebSocket monitoring, automated backup scheduling, comprehensive file management with version history, and complete server lifecycle management with graceful degradation capabilities.

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
- File edit history with version tracking and rollback capabilities
- Real-time file synchronization and monitoring
- Upload/download capabilities with validation
- File search and batch operations
- Automatic backup creation before edits

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
- **Framework**: FastAPI (Python 3.13+) with uvicorn ASGI server
- **Database**: SQLite with SQLAlchemy 2.0 ORM and transaction management
- **Authentication**: JWT tokens with refresh token support and bcrypt password hashing
- **Real-time**: WebSockets with connection lifecycle management
- **Process Management**: Async subprocess management with comprehensive monitoring
- **File Operations**: aiofiles with encoding detection and security validation
- **Package Management**: uv with dependency groups and workspace support
- **Testing**: pytest with asyncio support and comprehensive fixtures
- **Code Quality**: Black formatter, Ruff linter, and coverage reporting
- **Monitoring**: Performance middleware with metrics collection and audit logging

### System Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Web Client    │────▶│   FastAPI App   │────▶│    Database     │
│   (Frontend)    │◀────│  (with lifespan  │◀────│    (SQLite)     │
└─────────────────┘     │   management)   │     └─────────────────┘
         │               └─────────────────┘              │
         │                        │                       │
         │                        ├── Core Services ──────┤
         │                        │   ├── MinecraftServerManager (Process Management)
         │                        │   ├── DatabaseIntegrationService (State Sync)
         │                        │   ├── BackupSchedulerService (Automated Backups)
         │                        │   └── WebSocketService (Real-time Communication)
         │                        │
         │                        ├── Business Services
         │                        │   ├── FileManagementService (File Ops + History)
         │                        │   ├── GroupService (Player Management)
         │                        │   ├── TemplateService (Server Templates)
         │                        │   └── AuthorizationService (RBAC)
         │                        │
         └── WebSocket ────────────┼── Infrastructure
            Connection            │   ├── File System (servers/, backups/, templates/)
                                  │   ├── JAR Cache Manager (Minecraft versions)
                                  │   ├── Performance Monitoring Middleware
                                  │   └── Audit Middleware
                                  │
                                  └── External APIs
                                      ├── Minecraft Official API
                                      └── Mojang API (Player UUIDs)
```

### Core Components

#### 1. Application Layer (`app/`)
- **Routers**: HTTP endpoint definitions
- **Schemas**: Pydantic models for validation
- **Dependencies**: Dependency injection setup

#### 2. Business Logic Layer (`app/services/`)
- **MinecraftServerManager**: Async subprocess management, server lifecycle, status monitoring
- **DatabaseIntegrationService**: State synchronization between processes and database
- **BackupSchedulerService**: Database-persistent scheduling with caching and session management
- **WebSocketService**: Real-time monitoring, log streaming, command execution
- **FileManagementService**: Secure file operations, encoding detection, history tracking
- **GroupService**: Dynamic player groups with automatic server file synchronization
- **TemplateService**: Reusable server configurations and cloning
- **AuthorizationService**: Role-based access control and resource ownership validation
- **VersionManager**: Minecraft version management and JAR caching
- **MinecraftAPIService**: External API integration for player data

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
1. **Users**: User accounts with approval system, three-tier roles (User/Operator/Admin)
2. **Servers**: Minecraft server instances with process state, configuration, and metadata
3. **Groups**: Player permission groups (OP/whitelist) with multi-server attachment priorities
4. **Backups**: Server backup records with metadata, statistics, and restoration capabilities
5. **Templates**: Reusable server configurations with cloning and customization
6. **FileEditHistory**: Complete file version tracking with rollback capabilities
7. **AuditLogs**: Comprehensive system activity logging for security and compliance
8. **BackupSchedules**: Database-persistent backup scheduling with execution tracking
9. **GroupServerAttachments**: Many-to-many relationships with priority levels
10. **PlayerGroupAssignments**: Player-to-group associations with UUID tracking

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
1. User registers with username/email and awaits admin approval
2. First registered user automatically becomes admin with approval
3. Admin approves subsequent user accounts (sets is_approved=True)
4. User logs in and receives access token + refresh token
5. Access tokens used for API authentication with role-based permissions
6. Refresh tokens for secure token renewal without re-authentication
7. Logout invalidates refresh tokens for security

### Authorization Levels
- **User**: View own resources, basic file read access
- **Operator**: Create/manage servers, groups, templates, backups; full file operations
- **Admin**: Full system access including user management, all resources, system operations

**Resource Ownership Model**: Users can only access resources they own, except Admins who can access all resources. Some operations require specific roles regardless of ownership.

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

# Run tests with extended timeout for full suite
uv run pytest --timeout=300000

# Code quality checks
uv run ruff check app/
uv run black app/

# Coverage reporting
uv run coverage run -m pytest && uv run coverage report

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