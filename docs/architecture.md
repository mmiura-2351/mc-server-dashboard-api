# System Architecture

This document provides a comprehensive overview of the Minecraft Server Dashboard API architecture, design patterns, and system requirements.

## Overview

The Minecraft Server Dashboard API is a production-ready FastAPI-based backend system for managing multiple Minecraft servers with enterprise-grade features. It provides JWT authentication, three-tier role-based access control, real-time WebSocket monitoring, automated backup scheduling, comprehensive file management with version history, and complete server lifecycle management with graceful degradation capabilities.

## Technology Stack

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

## System Architecture

### High-Level Architecture

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

### Service Architecture

#### Core Services Layer

**MinecraftServerManager** (`app/services/minecraft_server.py`)
- Async subprocess management for Minecraft server processes
- Comprehensive status monitoring and health checks
- Process lifecycle management (start, stop, restart, force kill)
- Real-time log streaming with configurable queue sizes
- Java environment validation and EULA auto-acceptance
- Memory-efficient log handling with file rotation

**DatabaseIntegrationService** (`app/services/database_integration.py`)
- Bidirectional synchronization between process states and database
- Transaction management with retry logic and exponential backoff
- Callback-based status updates for real-time database sync
- Graceful degradation when database issues occur
- Batch operations for performance optimization

**BackupSchedulerService** (`app/services/backup_scheduler.py`)
- Database-persistent backup scheduling with cron expressions
- Memory caching for performance with database synchronization
- Server status awareness (backup running servers only)
- Comprehensive execution logging and error handling
- Session management preventing connection leaks

**WebSocketService** (`app/services/websocket_service.py`)
- Real-time server monitoring and log streaming
- Per-server connection management with automatic cleanup
- Command execution bridge for authenticated users
- Connection lifecycle management preventing resource leaks
- Real-time status broadcasts to connected clients

#### Business Services Layer

**FileManagementService** (`app/services/file_management_service.py`)
- Secure file operations with path traversal protection
- Automatic encoding detection for international character support
- File version history with rollback capabilities
- Role-based file access control (restricted files for admins only)
- Batch file operations for performance

**GroupService** (`app/services/group_service.py`)
- Dynamic OP/whitelist groups with multi-server attachment
- Automatic server file synchronization (ops.json/whitelist.json)
- Minecraft API integration for UUID/username resolution
- Priority-based group attachment system
- Batch file updates for performance optimization

**TemplateService** (`app/services/template_service.py`)
- Reusable server configurations with cloning capabilities
- Template creation from existing servers or custom configurations
- Public/private template sharing system
- Template validation and dependency management

**AuthorizationService** (`app/services/authorization_service.py`)
- Three-tier role-based access control (User/Operator/Admin)
- Resource ownership validation
- Permission checking for all operations
- Security audit logging integration

#### Infrastructure Layer

**JAR Cache Manager** (`app/services/jar_cache_manager.py`)
- Minecraft version JAR file caching and management
- Automatic download and validation
- Cache cleanup and statistics
- Version compatibility checking

**Version Manager** (`app/services/version_manager.py`)
- Minecraft version management and API integration
- Server type support (Vanilla, Paper, Spigot, Forge, Fabric)
- Version validation and compatibility checking

**Minecraft API Service** (`app/services/minecraft_api_service.py`)
- Integration with Minecraft official API
- Player UUID/username resolution
- External service error handling and retry logic

## Application Lifecycle

### Startup Sequence

The application follows a carefully orchestrated startup sequence with graceful degradation:

1. **Database Initialization** (Critical)
   - SQLAlchemy table creation
   - Connection validation
   - Migration handling
   - *Failure here prevents startup*

2. **Database Integration Service** (Important)
   - Service initialization
   - Server state synchronization
   - *Degrades gracefully if sync fails*

3. **Backup Scheduler Service** (Optional)
   - Scheduler startup
   - Schedule loading from database
   - *Continues without automated backups if fails*

4. **WebSocket Service** (Optional)
   - Real-time monitoring initialization
   - Connection manager setup
   - *Continues without real-time features if fails*

### Graceful Degradation

The system is designed to continue operating even when optional services fail:

- **Database Issues**: Core functionality continues, real-time sync disabled
- **Backup Scheduler Failure**: Manual backups still available
- **WebSocket Failure**: API remains functional, no real-time updates
- **External API Failure**: Cached data used, functionality limited

### Shutdown Sequence

Clean shutdown with proper resource cleanup:

1. **Minecraft Server Manager**: Graceful server shutdown
2. **Backup Scheduler**: Task completion and scheduler stop
3. **WebSocket Service**: Connection cleanup and monitoring stop
4. **Database**: Connection pool cleanup

## Security Architecture

### Authentication & Authorization

**Authentication Flow**:
1. User registration with admin approval system
2. First registered user automatically becomes admin
3. JWT access tokens (short-lived) + refresh tokens (long-lived)
4. Secure logout with refresh token invalidation

**Role-Based Access Control**:
- **User**: View own resources, basic file read access
- **Operator**: Create/manage servers, groups, templates, backups; full file operations
- **Admin**: Full system access including user management and system operations

**Resource Ownership Model**:
- Users can only access resources they own
- Admins can access all resources
- Some operations require specific roles regardless of ownership

### Security Features

- **Password Security**: bcrypt hashing with salt
- **JWT Security**: Secure token generation with expiration
- **Path Security**: Traversal protection for file operations
- **Input Validation**: Comprehensive Pydantic model validation
- **Audit Logging**: Complete activity tracking for security compliance
- **Rate Limiting**: Protection against abuse on sensitive endpoints

## Data Architecture

### Core Entities

1. **Users**: Authentication, roles, approval status, profile information
2. **Servers**: Configuration, process state, metadata, file paths
3. **Groups**: OP/whitelist player collections with multi-server attachment
4. **Backups**: Metadata, statistics, restoration capabilities, scheduling
5. **Templates**: Reusable configurations, public/private sharing
6. **FileEditHistory**: Complete version tracking with rollback
7. **AuditLogs**: Security and compliance activity tracking
8. **BackupSchedules**: Cron-based scheduling with execution history
9. **GroupServerAttachments**: Many-to-many with priorities
10. **PlayerGroupAssignments**: Player-to-group with UUID tracking

### Data Relationships

```
Users (1:N) ────┐
                ├─ Servers (1:N) ── Backups
                ├─ Groups (N:M) ──── Servers (via GroupServerAttachments)
                ├─ Templates
                └─ RefreshTokens

Servers (1:N) ── FileEditHistory
All Entities ── AuditLogs (audit trail)
```

### Database Design Principles

- **Referential Integrity**: Foreign key constraints with appropriate cascades
- **Soft Deletes**: Implemented where data retention is important
- **Audit Trail**: Complete activity logging for compliance
- **Performance**: Appropriate indexing and query optimization
- **Scalability**: Design supports horizontal scaling

## Integration Patterns

### Service Communication

**Event-Driven Updates**:
- Server status changes → Database updates → WebSocket broadcasts
- Group changes → Server file updates → Real-time reflection

**Callback Architecture**:
- MinecraftServerManager uses callbacks for database updates
- Avoids tight coupling while maintaining real-time sync

**Service Dependencies**:
- Database Integration depends on MinecraftServerManager
- WebSocket Service depends on MinecraftServerManager
- Group Service depends on File Management Service
- All services handle missing dependencies gracefully

### External API Integration

**Minecraft Official API**:
- Version information and JAR downloads
- Retry logic with exponential backoff
- Fallback to cached data when unavailable

**Mojang API**:
- Player UUID/username resolution
- Rate limiting compliance
- Error handling for service outages

## Performance Architecture

### Optimization Strategies

- **Database**: Connection pooling, query optimization, appropriate indexing
- **File Operations**: Async I/O with aiofiles, encoding detection caching
- **Process Management**: Efficient subprocess handling, resource monitoring
- **WebSocket**: Connection pooling, message queuing, automatic cleanup
- **Caching**: JAR file caching, template configuration caching

### Monitoring & Metrics

**Performance Monitoring Middleware**:
- Request/response time tracking
- Database query performance monitoring
- Memory usage and resource utilization
- Slow request identification and logging

**Health Monitoring**:
- Service status tracking
- Database connection health
- External API availability
- Process status monitoring

### Scalability Considerations

- **Stateless Design**: All state stored in database
- **Horizontal Scaling**: Load balancer ready
- **Resource Isolation**: Process-level isolation for servers
- **Database Optimization**: Query performance and connection management

## Development Architecture

### Code Organization

```
app/
├── main.py                 # Application entry point and lifespan management
├── core/                   # Core configuration and database
├── services/               # Business logic services
├── [domain]/               # Feature domains (servers, groups, etc.)
│   ├── models.py          # Database models
│   ├── schemas.py         # Pydantic validation models
│   ├── router.py          # HTTP endpoints
│   └── service.py         # Domain-specific business logic
├── middleware/             # Request/response middleware
└── types.py               # Shared type definitions
```

### Design Patterns

**Domain-Driven Design**: Clear separation by business domains
**Dependency Injection**: FastAPI dependency system for services
**Repository Pattern**: Database access abstraction
**Service Layer**: Business logic separation from HTTP layer
**Middleware Pattern**: Cross-cutting concerns (auth, logging, performance)

### Code Quality Standards

- **Formatting**: Black with 90-character line length
- **Linting**: Ruff with import sorting and type checking
- **Testing**: pytest with >90% coverage target
- **Type Hints**: Required for all new code
- **Documentation**: Comprehensive docstrings and API documentation

## Use Case Coverage

The system implements comprehensive functionality across 46+ use cases:

### Server Management (UC1-11)
- Multi-server creation, configuration, and lifecycle management
- Process control with real-time monitoring
- Version management and JAR caching
- Import/export capabilities

### Player Management (UC12-19)
- Dynamic OP/whitelist groups with server attachment
- Minecraft API integration for player validation
- Priority-based group management
- Automatic server file synchronization

### Monitoring & Real-time (UC20)
- WebSocket-based real-time server monitoring
- Live log streaming and status updates
- System-wide notifications

### Backup Management (UC21-28)
- Manual and automated backup creation
- Backup restoration with server creation
- Template generation from backups
- Comprehensive backup statistics

### File Management (UC29-37)
- Secure file operations with version history
- File search and batch operations
- Upload/download capabilities
- Rollback and recovery features

### Account Management (UC38-42)
- User registration with approval workflow
- Profile management and password changes
- Role-based access control

### Administrative Functions (UC43-46)
- User approval and role management
- System synchronization and maintenance
- Cache management and cleanup
- Comprehensive audit logging

This architecture provides a robust, scalable, and maintainable foundation for managing multiple Minecraft servers with enterprise-grade features, security, and performance.