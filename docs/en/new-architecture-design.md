# Minecraft Server Dashboard API V2 - Architecture Design Document

## Overview

This document outlines the complete architecture design for rebuilding the Minecraft Server Dashboard API from scratch, addressing the complexity issues identified in the current system while maintaining core functionality across 6 bounded contexts.

## Architecture Philosophy

### Core Principles
1. **Domain-Driven Design (DDD)**: Organize code around business domains with clear boundaries
2. **Clean Architecture**: Dependency inversion with infrastructure as outer layer
3. **CQRS + Event Sourcing**: Separate read/write operations with event-driven architecture
4. **Microservices-Ready**: Modular design that can scale to distributed architecture
5. **Testability First**: Design for easy testing with dependency injection
6. **Fail-Fast Design**: Early validation and error handling

### Architecture Patterns
- **Hexagonal Architecture**: Clean separation between business logic and infrastructure
- **Command Query Responsibility Segregation (CQRS)**: Separate read and write models
- **Event-Driven Architecture**: Decouple components through domain events
- **Repository Pattern**: Abstract data access with clean interfaces
- **Unit of Work Pattern**: Manage database transactions consistently

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Presentation Layer                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   REST API  │  │  WebSocket  │  │  GraphQL    │        │
│  │  (FastAPI)  │  │   Gateway   │  │  (Optional) │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   Application Layer                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Command    │  │    Query     │  │   Event     │        │
│  │  Handlers   │  │   Handlers   │  │  Handlers   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Domain Layer                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Domain    │  │   Domain    │  │   Domain    │        │
│  │  Services   │  │   Events    │  │   Models    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                Infrastructure Layer                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ Repositories│  │  External   │  │ Background  │        │
│  │ (Database)  │  │   APIs      │  │   Tasks     │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

## Technology Stack V2

### Core Framework
- **Python 3.12+**: Latest stable version for performance improvements
- **FastAPI 0.115+**: Continue with FastAPI for async performance and automatic OpenAPI
- **Pydantic V2**: Enhanced validation and serialization
- **SQLAlchemy 2.0**: Modern async ORM with improved query patterns
- **Alembic**: Database migration management

### Database & Storage
- **PostgreSQL 15+**: Primary database for ACID compliance and JSON support
- **Redis 7+**: Session storage, caching, and pub/sub for real-time features
- **MinIO/S3**: Object storage for backups and large files
- **ClickHouse**: Optional time-series database for metrics and audit logs

### Message Queue & Background Processing
- **RQ (Redis Queue)**: Background job processing with Redis
- **APScheduler**: Scheduled task management
- **Celery**: Optional upgrade path for complex distributed tasks

### Real-time & Communication
- **FastAPI WebSockets**: Real-time communication
- **Server-Sent Events (SSE)**: Alternative to WebSockets for simpler clients
- **Redis Pub/Sub**: Inter-service communication

### Development & Deployment
- **UV**: Fast Python package manager and project management
- **Ruff**: Lightning-fast linting and formatting
- **Pytest**: Comprehensive testing framework
- **Docker**: Containerization for development and deployment
- **Traefik**: API Gateway and load balancer

### Monitoring & Observability
- **Structlog**: Structured logging
- **Prometheus**: Metrics collection
- **Grafana**: Visualization and dashboards
- **Sentry**: Error tracking and performance monitoring

## Domain-Driven Design Structure

### Bounded Contexts

#### 1. User Management Context
```
users/
├── domain/
│   ├── entities/
│   │   ├── user.py
│   │   └── user_session.py
│   ├── value_objects/
│   │   ├── user_id.py
│   │   ├── email.py
│   │   └── password.py
│   ├── repositories/
│   │   └── user_repository.py
│   ├── events/
│   │   ├── user_registered.py
│   │   └── user_approved.py
│   └── services/
│       └── user_service.py
├── application/
│   ├── commands/
│   │   ├── register_user.py
│   │   └── approve_user.py
│   ├── queries/
│   │   └── get_user_profile.py
│   └── handlers/
│       ├── command_handlers.py
│       └── query_handlers.py
├── infrastructure/
│   ├── repositories/
│   │   └── sql_user_repository.py
│   └── adapters/
│       └── auth_adapter.py
└── api/
    └── user_router.py
```

#### 2. Server Management Context
```
servers/
├── domain/
│   ├── entities/
│   │   ├── minecraft_server.py
│   │   └── server_configuration.py
│   ├── value_objects/
│   │   ├── server_id.py
│   │   ├── port.py
│   │   └── java_version.py
│   ├── repositories/
│   │   └── server_repository.py
│   ├── events/
│   │   ├── server_created.py
│   │   └── server_started.py
│   └── services/
│       ├── server_lifecycle_service.py
│       └── process_manager_service.py
├── application/
│   ├── commands/
│   │   ├── create_server.py
│   │   └── start_server.py
│   ├── queries/
│   │   └── get_server_status.py
│   └── handlers/
├── infrastructure/
│   ├── repositories/
│   ├── adapters/
│   │   ├── minecraft_process_adapter.py
│   │   └── file_system_adapter.py
│   └── external/
│       └── minecraft_api_client.py
└── api/
    └── server_router.py
```

#### 3. Group Management Context
```
groups/
├── domain/
│   ├── entities/
│   │   ├── player_group.py
│   │   └── player.py
│   ├── value_objects/
│   │   ├── group_id.py
│   │   ├── minecraft_uuid.py
│   │   └── username.py
│   ├── repositories/
│   │   └── group_repository.py
│   ├── events/
│   │   ├── player_added.py
│   │   └── group_attached.py
│   └── services/
│       └── group_management_service.py
├── application/
├── infrastructure/
└── api/
```

#### 4. Backup Management Context
```
backups/
├── domain/
│   ├── entities/
│   │   ├── backup.py
│   │   └── backup_schedule.py
│   ├── value_objects/
│   │   ├── backup_id.py
│   │   └── cron_expression.py
│   ├── repositories/
│   │   └── backup_repository.py
│   ├── events/
│   │   ├── backup_created.py
│   │   └── backup_scheduled.py
│   └── services/
│       ├── backup_service.py
│       └── schedule_service.py
├── application/
├── infrastructure/
│   └── adapters/
│       └── storage_adapter.py
└── api/
```

#### 5. File Management Context
```
files/
├── domain/
│   ├── entities/
│   │   ├── server_file.py
│   │   └── file_history.py
│   ├── value_objects/
│   │   ├── file_path.py
│   │   └── file_content.py
│   ├── repositories/
│   │   └── file_repository.py
│   ├── events/
│   │   └── file_modified.py
│   └── services/
│       └── file_management_service.py
├── application/
├── infrastructure/
│   └── adapters/
│       └── file_system_adapter.py
└── api/
```

#### 6. Monitoring Context
```
monitoring/
├── domain/
│   ├── entities/
│   │   ├── server_metrics.py
│   │   └── audit_log.py
│   ├── value_objects/
│   │   └── metric_value.py
│   ├── repositories/
│   │   └── metrics_repository.py
│   ├── events/
│   │   └── metric_recorded.py
│   └── services/
│       └── monitoring_service.py
├── application/
├── infrastructure/
│   └── adapters/
│       └── metrics_collector.py
└── api/
```

### Shared Kernel
```
shared/
├── domain/
│   ├── value_objects/
│   │   ├── entity_id.py
│   │   └── created_at.py
│   ├── events/
│   │   └── domain_event.py
│   └── exceptions/
│       └── domain_exception.py
├── application/
│   ├── commands/
│   │   └── command.py
│   ├── queries/
│   │   └── query.py
│   └── handlers/
│       └── handler.py
└── infrastructure/
    ├── database/
    │   ├── base_repository.py
    │   └── unit_of_work.py
    ├── events/
    │   └── event_publisher.py
    └── cache/
        └── cache_service.py
```

## Event-Driven Architecture

### Domain Events

#### User Events
- `UserRegistered`
- `UserApproved`
- `UserRoleChanged`
- `UserLoggedIn`
- `UserLoggedOut`

#### Server Events
- `ServerCreated`
- `ServerStarted`
- `ServerStopped`
- `ServerConfigurationUpdated`
- `ServerDeleted`
- `ConsoleCommandExecuted`

#### Group Events
- `GroupCreated`
- `PlayerAddedToGroup`
- `PlayerRemovedFromGroup`
- `GroupAttachedToServer`
- `GroupDetachedFromServer`

#### Backup Events
- `BackupCreated`
- `BackupScheduled`
- `BackupCompleted`
- `BackupFailed`
- `BackupRestored`

### Event Handlers

Events are handled by:
1. **Immediate Handlers**: Update read models, send notifications
2. **Background Handlers**: Long-running operations (backup creation, file processing)
3. **Integration Handlers**: Update external systems, trigger webhooks

### Event Store

Using PostgreSQL with JSONB for event storage:
```sql
CREATE TABLE domain_events (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    event_version INTEGER NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE
);
```

## CQRS Implementation

### Command Side
- **Commands**: Represent write operations with validation
- **Command Handlers**: Execute business logic and emit events
- **Aggregates**: Ensure consistency within bounded contexts
- **Repositories**: Persist aggregate state

### Query Side
- **Queries**: Represent read operations with specific data needs
- **Query Handlers**: Return optimized read models
- **Read Models**: Denormalized views optimized for specific queries
- **Projections**: Update read models from domain events

### Read Model Examples

#### Server List Read Model
```python
@dataclass
class ServerListItem:
    id: UUID
    name: str
    status: ServerStatus
    player_count: int
    version: str
    created_at: datetime
    owner_username: str
```

#### Backup Summary Read Model
```python
@dataclass
class BackupSummary:
    server_id: UUID
    server_name: str
    backup_count: int
    latest_backup: datetime
    total_size: int
    success_rate: float
```

## Database Design V2

### Write Models (Normalized)
```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active BOOLEAN DEFAULT true,
    is_approved BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

-- Servers table
CREATE TABLE servers (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    owner_id UUID REFERENCES users(id),
    port INTEGER UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'stopped',
    configuration JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

-- Groups table
CREATE TABLE groups (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    group_type VARCHAR(20) NOT NULL, -- 'op' or 'whitelist'
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

-- Players table
CREATE TABLE players (
    id UUID PRIMARY KEY,
    minecraft_uuid UUID UNIQUE NOT NULL,
    username VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Group players junction
CREATE TABLE group_players (
    group_id UUID REFERENCES groups(id) ON DELETE CASCADE,
    player_id UUID REFERENCES players(id) ON DELETE CASCADE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (group_id, player_id)
);

-- Server groups junction
CREATE TABLE server_groups (
    server_id UUID REFERENCES servers(id) ON DELETE CASCADE,
    group_id UUID REFERENCES groups(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 0,
    attached_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (server_id, group_id)
);

-- Backups table
CREATE TABLE backups (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES servers(id),
    name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    size_bytes BIGINT,
    backup_type VARCHAR(20) DEFAULT 'manual', -- 'manual' or 'scheduled'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Backup schedules table
CREATE TABLE backup_schedules (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES servers(id),
    cron_expression VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    last_run TIMESTAMP WITH TIME ZONE,
    next_run TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

```

### Read Models (Denormalized)
```sql
-- Server list view
CREATE MATERIALIZED VIEW server_list_view AS
SELECT 
    s.id,
    s.name,
    s.status,
    s.port,
    s.configuration->>'version' as version,
    s.created_at,
    u.username as owner_username,
    COUNT(b.id) as backup_count,
    MAX(b.created_at) as latest_backup
FROM servers s
LEFT JOIN users u ON s.owner_id = u.id
LEFT JOIN backups b ON s.id = b.server_id
GROUP BY s.id, s.name, s.status, s.port, s.configuration, s.created_at, u.username;

-- Group summary view
CREATE MATERIALIZED VIEW group_summary_view AS
SELECT 
    g.id,
    g.name,
    g.group_type,
    g.created_at,
    u.username as owner_username,
    COUNT(DISTINCT gp.player_id) as player_count,
    COUNT(DISTINCT sg.server_id) as server_count
FROM groups g
LEFT JOIN users u ON g.owner_id = u.id
LEFT JOIN group_players gp ON g.id = gp.group_id
LEFT JOIN server_groups sg ON g.id = sg.group_id
GROUP BY g.id, g.name, g.group_type, g.created_at, u.username;
```

## API Design V2

### RESTful API Structure
```
/api/v2/
├── auth/
│   ├── POST /register
│   ├── POST /login
│   ├── POST /refresh
│   └── POST /logout
├── users/
│   ├── GET /me
│   ├── PUT /me
│   ├── GET /
│   └── PATCH /{user_id}/approve
├── servers/
│   ├── GET /
│   ├── POST /
│   ├── GET /{server_id}
│   ├── PUT /{server_id}
│   ├── DELETE /{server_id}
│   ├── POST /{server_id}/start
│   ├── POST /{server_id}/stop
│   ├── POST /{server_id}/restart
│   ├── GET /{server_id}/status
│   ├── POST /{server_id}/console
│   └── GET /{server_id}/logs
├── groups/
│   ├── GET /
│   ├── POST /
│   ├── GET /{group_id}
│   ├── PUT /{group_id}
│   ├── DELETE /{group_id}
│   ├── POST /{group_id}/players
│   ├── DELETE /{group_id}/players/{player_id}
│   ├── POST /{group_id}/servers/{server_id}
│   └── DELETE /{group_id}/servers/{server_id}
├── backups/
│   ├── GET /servers/{server_id}/backups
│   ├── POST /servers/{server_id}/backups
│   ├── GET /backups/{backup_id}
│   ├── DELETE /backups/{backup_id}
│   ├── POST /backups/{backup_id}/restore
│   ├── GET /servers/{server_id}/schedules
│   ├── POST /servers/{server_id}/schedules
│   └── DELETE /schedules/{schedule_id}
├── files/
│   ├── GET /servers/{server_id}/files
│   ├── GET /servers/{server_id}/files/{file_path}
│   ├── PUT /servers/{server_id}/files/{file_path}
│   ├── DELETE /servers/{server_id}/files/{file_path}
│   └── GET /servers/{server_id}/files/{file_path}/history
└── admin/
    ├── GET /users
    ├── GET /system/sync
    ├── GET /cache/stats
    └── GET /audit
```

### WebSocket API
```
/ws/
├── servers/{server_id}/
│   ├── status    # Server status updates
│   ├── logs      # Real-time log streaming
│   └── console   # Interactive console
├── notifications # Global user notifications
└── metrics       # System metrics (admin)
```

### Command/Query Separation
```python
# Commands (Write operations)
class CreateServerCommand:
    name: str
    description: str
    version: str
    memory_mb: int
    owner_id: UUID

class StartServerCommand:
    server_id: UUID
    
# Queries (Read operations)
class GetServerListQuery:
    owner_id: Optional[UUID] = None
    status: Optional[ServerStatus] = None
    page: int = 1
    limit: int = 20

class GetServerDetailsQuery:
    server_id: UUID
    include_metrics: bool = False
```

## Security Architecture

### Authentication & Authorization
```python
# JWT Claims Structure
{
    "sub": "user_id",
    "username": "john_doe",
    "role": "operator",
    "permissions": ["server:read", "server:write", "group:read"],
    "exp": 1234567890,
    "iat": 1234567890
}

# Permission System
class Permission:
    ADMIN_ALL = "admin:*"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    SERVER_READ = "server:read"
    SERVER_WRITE = "server:write"
    SERVER_CONSOLE = "server:console"
    GROUP_READ = "group:read"
    GROUP_WRITE = "group:write"
    BACKUP_READ = "backup:read"
    BACKUP_WRITE = "backup:write"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
```

### Input Validation
```python
from pydantic import BaseModel, validator, Field
from typing import Optional
import re

class CreateServerRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    version: str = Field(..., regex=r'^\d+\.\d+(\.\d+)?$')
    memory_mb: int = Field(..., ge=512, le=32768)
    
    @validator('name')
    def validate_server_name(cls, v):
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Server name can only contain letters, numbers, underscores, and hyphens')
        return v

class ConsoleCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=200)
    
    @validator('command')
    def validate_command(cls, v):
        dangerous_commands = ['rm', 'del', 'format', 'shutdown', 'restart']
        if any(cmd in v.lower() for cmd in dangerous_commands):
            raise ValueError('Dangerous command not allowed')
        return v
```

### Rate Limiting
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Rate limiting configuration
RATE_LIMITS = {
    "auth": "5/minute",
    "console": "30/minute", 
    "api_general": "100/minute",
    "websocket": "1000/minute"
}
```

## Performance Optimizations

### Database Optimizations
```sql
-- Indexes for common queries
CREATE INDEX idx_servers_owner_status ON servers(owner_id, status);
CREATE INDEX idx_backups_server_created ON backups(server_id, created_at DESC);
CREATE INDEX idx_groups_owner_type ON groups(owner_id, group_type);
CREATE INDEX idx_domain_events_aggregate ON domain_events(aggregate_type, aggregate_id);

-- Partial indexes for active records
CREATE INDEX idx_users_active ON users(id) WHERE is_active = true AND is_approved = true;
CREATE INDEX idx_schedules_active ON backup_schedules(server_id, next_run) WHERE is_active = true;
```

### Caching Strategy
```python
# Redis caching layers
CACHE_KEYS = {
    "server_status": "server:{server_id}:status",  # TTL: 30s
    "user_permissions": "user:{user_id}:perms",    # TTL: 15min
    "server_list": "servers:list:{owner_id}",      # TTL: 5min
    "backup_summary": "backup:summary:{server_id}" # TTL: 1hour
}

# Cache invalidation patterns
CACHE_INVALIDATION = {
    "ServerStarted": ["server:{server_id}:status", "servers:list:*"],
    "BackupCreated": ["backup:summary:{server_id}"],
    "UserRoleChanged": ["user:{user_id}:perms"]
}
```

### Async Operations
```python
# Background job queues
JOB_QUEUES = {
    "high_priority": ["server_start", "server_stop"],
    "normal_priority": ["backup_create", "file_upload"],
    "low_priority": ["metrics_collection", "cleanup_tasks"]
}

# Async service implementations
class AsyncServerService:
    async def start_server(self, server_id: UUID) -> None:
        # Non-blocking server start with progress tracking
        job = await self.job_queue.enqueue(
            "start_server_job", 
            server_id, 
            queue="high_priority"
        )
        await self.event_publisher.publish(
            ServerStartRequested(server_id=server_id, job_id=job.id)
        )
```

## Testing Strategy

### Test Architecture
```
tests/
├── unit/
│   ├── domain/
│   │   ├── test_entities.py
│   │   ├── test_value_objects.py
│   │   └── test_services.py
│   ├── application/
│   │   ├── test_command_handlers.py
│   │   └── test_query_handlers.py
│   └── infrastructure/
│       ├── test_repositories.py
│       └── test_adapters.py
├── integration/
│   ├── test_api_endpoints.py
│   ├── test_database_operations.py
│   └── test_event_handling.py
├── e2e/
│   ├── test_user_workflows.py
│   ├── test_server_lifecycle.py
│   └── test_backup_workflows.py
└── performance/
    ├── test_load_scenarios.py
    └── test_concurrent_users.py
```

### Test Coverage Goals
- Unit Tests: >90% coverage
- Integration Tests: All API endpoints
- E2E Tests: Critical user journeys
- Performance Tests: Load testing for concurrent operations

## Deployment Architecture

### Container Strategy
```dockerfile
# Multi-stage build for production
FROM python:3.12-slim as builder
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim as runtime
COPY --from=builder /app/.venv /app/.venv
COPY ./app /app/app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose Setup
```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/mcapi
      - REDIS_URL=redis://redis:6379
    depends_on:
      - postgres
      - redis
      
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=mcapi
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
      
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
      
  worker:
    build: .
    command: rq worker --url redis://redis:6379
    depends_on:
      - redis
      - postgres
      
volumes:
  postgres_data:
  redis_data:
```

### Production Deployment
```yaml
# Kubernetes deployment example
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcapi-deployment
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcapi
  template:
    metadata:
      labels:
        app: mcapi
    spec:
      containers:
      - name: mcapi
        image: mcapi:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: mcapi-secrets
              key: database-url
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
```

## Migration Strategy

### Phase 1: Foundation (Weeks 1-2)
1. Set up new project structure
2. Implement shared kernel and core domain models
3. Set up database and basic CRUD operations
4. Implement authentication and authorization

### Phase 2: Core Domains (Weeks 3-6)
1. User Management domain
2. Server Management domain (basic operations)
3. Group Management domain
4. Basic API endpoints and validation

### Phase 3: Advanced Features (Weeks 7-10)
1. Backup Management domain
2. File Management domain
3. Background job processing

### Phase 4: Real-time & Monitoring (Weeks 11-12)
1. WebSocket implementation
2. Monitoring and metrics
3. Event-driven architecture completion
4. Performance optimization

### Phase 5: Migration & Deployment (Weeks 13-14)
1. Data migration from V1
2. Production deployment
3. Load testing and optimization
4. Documentation and training

## Success Metrics

### Technical Metrics
- Code coverage: >90%
- API response time: <200ms (95th percentile)
- Database query time: <50ms (average)
- Memory usage: <512MB per instance
- CPU usage: <50% under normal load

### Business Metrics
- Support for 500+ concurrent servers
- 99.9% uptime
- Zero data loss
- <1 second real-time event propagation
- Support for 1000+ concurrent WebSocket connections

## Conclusion

This architecture design provides a solid foundation for rebuilding the Minecraft Server Dashboard API with improved maintainability, scalability, and testability. The domain-driven design approach ensures clear separation of concerns, while the event-driven architecture enables loose coupling and better extensibility.

The migration from V1 to V2 will be executed in phases to minimize disruption while delivering immediate value through improved code organization and reduced technical debt.