# API Design - Minecraft Server Dashboard API V2

## Overview

This document provides comprehensive API design for the Minecraft Server Dashboard API V2, including RESTful endpoints, WebSocket connections, authentication mechanisms, request/response schemas, error handling, and OpenAPI specification.

## API Architecture

### Design Principles
1. **RESTful Design**: Resource-oriented URLs with proper HTTP methods
2. **Consistent Naming**: Snake_case for JSON fields, kebab-case for URLs
3. **Versioning**: URL-based versioning (`/api/v2/`)
4. **Stateless**: No server-side session state for REST endpoints
5. **HATEOAS**: Include relevant links in responses
6. **Content Negotiation**: Support JSON (primary) and optional formats

### Technology Stack
- **Framework**: FastAPI with automatic OpenAPI generation
- **Authentication**: JWT Bearer tokens
- **Validation**: Pydantic models with comprehensive validation
- **Documentation**: Auto-generated OpenAPI/Swagger docs
- **Rate Limiting**: Redis-based rate limiting
- **Real-time**: WebSocket connections for live updates

## Authentication & Authorization

### JWT Token Structure
```json
{
  "sub": "user_id",
  "username": "john_doe",
  "email": "john@example.com",
  "role": "operator",
  "permissions": [
    "server:read",
    "server:write",
    "group:read",
    "backup:read"
  ],
  "iat": 1640995200,
  "exp": 1641081600,
  "jti": "token_id"
}
```

### Permission System
```python
class Permissions:
    # Admin permissions
    ADMIN_ALL = "admin:*"
    USER_MANAGE = "user:manage"
    
    # User permissions
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    
    # Server permissions
    SERVER_READ = "server:read"
    SERVER_WRITE = "server:write"
    SERVER_CONTROL = "server:control"
    SERVER_CONSOLE = "server:console"
    SERVER_DELETE = "server:delete"
    
    # Group permissions
    GROUP_READ = "group:read"
    GROUP_WRITE = "group:write"
    GROUP_DELETE = "group:delete"
    
    # Backup permissions
    BACKUP_READ = "backup:read"
    BACKUP_WRITE = "backup:write"
    BACKUP_DELETE = "backup:delete"
    
    # Template permissions
    TEMPLATE_READ = "template:read"
    TEMPLATE_WRITE = "template:write"
    TEMPLATE_PUBLIC = "template:public"
    
    # File permissions
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"
    
    # Monitoring permissions
    METRICS_READ = "metrics:read"
    AUDIT_READ = "audit:read"
```

## API Endpoints

### Base URL
- **Production**: `https://api.mcserver.example.com/api/v2`
- **Development**: `http://localhost:8000/api/v2`

### 1. Authentication Endpoints

#### POST /auth/register
Register a new user account.

**Request Body:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "SecurePassword123!",
  "full_name": "John Doe"
}
```

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "role": "user",
  "is_active": true,
  "is_approved": false,
  "created_at": "2024-01-15T10:30:00Z",
  "message": "Registration successful. Account requires admin approval."
}
```

#### POST /auth/login
Authenticate user and receive access tokens.

**Request Body:**
```json
{
  "username": "john_doe",
  "password": "SecurePassword123!"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "john_doe",
    "email": "john@example.com",
    "role": "operator",
    "permissions": ["server:read", "server:write"]
  }
}
```

#### POST /auth/refresh
Refresh access token using refresh token.

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### POST /auth/logout
Logout and revoke tokens.

**Headers:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### 2. User Management Endpoints

#### GET /users/me
Get current user profile.

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "role": "operator",
  "is_active": true,
  "is_approved": true,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-16T08:15:00Z",
  "last_login": "2024-01-16T09:00:00Z",
  "permissions": ["server:read", "server:write", "group:read"],
  "statistics": {
    "servers_count": 5,
    "groups_count": 3,
    "backups_count": 15
  },
  "_links": {
    "self": "/api/v2/users/me",
    "servers": "/api/v2/servers?owner_id=550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### PUT /users/me
Update current user profile.

**Request Body:**
```json
{
  "email": "newemail@example.com",
  "full_name": "John Smith",
  "password": "NewSecurePassword123!"
}
```

#### GET /users
List all users (Admin only).

**Query Parameters:**
- `page` (integer, default: 1): Page number
- `limit` (integer, default: 20, max: 100): Items per page
- `role` (string): Filter by role
- `is_approved` (boolean): Filter by approval status
- `search` (string): Search by username or email

**Response (200 OK):**
```json
{
  "users": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "username": "john_doe",
      "email": "john@example.com",
      "full_name": "John Doe",
      "role": "operator",
      "is_active": true,
      "is_approved": true,
      "created_at": "2024-01-15T10:30:00Z",
      "last_login": "2024-01-16T09:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "pages": 1
  },
  "_links": {
    "self": "/api/v2/users?page=1&limit=20",
    "next": null,
    "prev": null
  }
}
```

#### PATCH /users/{user_id}/approve
Approve user registration (Admin only).

**Request Body:**
```json
{
  "is_approved": true,
  "role": "operator"
}
```

### 3. Server Management Endpoints

#### GET /servers
List user's servers.

**Query Parameters:**
- `page` (integer): Page number
- `limit` (integer): Items per page
- `status` (string): Filter by status
- `server_type` (string): Filter by server type
- `search` (string): Search by name or description
- `sort` (string): Sort field (created_at, name, status)
- `order` (string): Sort order (asc, desc)

**Response (200 OK):**
```json
{
  "servers": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "survival-world",
      "description": "Main survival server",
      "status": "running",
      "port": 25565,
      "minecraft_version": "1.21.5",
      "server_type": "paper",
      "memory_mb": 4096,
      "player_count": 5,
      "max_players": 20,
      "created_at": "2024-01-15T10:30:00Z",
      "last_started_at": "2024-01-16T08:00:00Z",
      "owner": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "john_doe"
      },
      "statistics": {
        "uptime_hours": 168,
        "total_playtime_hours": 2340,
        "backup_count": 8,
        "attached_groups": 2
      },
      "_links": {
        "self": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000",
        "start": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/start",
        "stop": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/stop",
        "console": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/console",
        "logs": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/logs",
        "backups": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/backups"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "pages": 1
  },
  "summary": {
    "total_servers": 1,
    "running_servers": 1,
    "stopped_servers": 0,
    "total_memory_mb": 4096
  }
}
```

#### POST /servers
Create a new server.

**Request Body:**
```json
{
  "name": "creative-build",
  "description": "Creative building server",
  "minecraft_version": "1.21.5",
  "server_type": "paper",
  "memory_mb": 2048,
  "port": 25566,
  "auto_start": false,
  "auto_restart": true,
  "java_args": "-XX:+UseG1GC -XX:MaxGCPauseMillis=50",
  "configuration": {
    "gamemode": "creative",
    "difficulty": "peaceful",
    "max_players": 10,
    "view_distance": 8,
    "spawn_protection": 0
  }
}
```

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "creative-build",
  "description": "Creative building server",
  "status": "stopped",
  "port": 25566,
  "minecraft_version": "1.21.5",
  "server_type": "paper",
  "memory_mb": 2048,
  "owner_id": "440e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-16T10:30:00Z",
  "configuration": {
    "gamemode": "creative",
    "difficulty": "peaceful",
    "max_players": 10,
    "view_distance": 8,
    "spawn_protection": 0
  },
  "_links": {
    "self": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000",
    "start": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/start"
  }
}
```

#### GET /servers/{server_id}
Get server details.

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "survival-world",
  "description": "Main survival server",
  "status": "running",
  "port": 25565,
  "minecraft_version": "1.21.5",
  "server_type": "paper",
  "memory_mb": 4096,
  "java_args": "-XX:+UseG1GC -XX:MaxGCPauseMillis=50",
  "auto_start": false,
  "auto_restart": true,
  "process_id": 12345,
  "created_at": "2024-01-15T10:30:00Z",
  "last_started_at": "2024-01-16T08:00:00Z",
  "owner": {
    "id": "440e8400-e29b-41d4-a716-446655440000",
    "username": "john_doe",
    "full_name": "John Doe"
  },
  "configuration": {
    "gamemode": "survival",
    "difficulty": "normal",
    "max_players": 20,
    "view_distance": 10,
    "spawn_protection": 16,
    "enable_whitelist": true
  },
  "runtime_info": {
    "uptime_seconds": 28800,
    "cpu_usage_percent": 15.5,
    "memory_usage_mb": 3072,
    "disk_usage_mb": 2048,
    "tps": 19.8,
    "player_count": 5,
    "players_online": [
      {
        "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        "username": "player1",
        "display_name": "Player One"
      }
    ]
  },
  "file_structure": {
    "world_size_mb": 150,
    "plugin_count": 8,
    "mod_count": 0
  },
  "_links": {
    "self": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000",
    "start": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/start",
    "stop": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/stop",
    "restart": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/restart",
    "console": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/console",
    "logs": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/logs",
    "files": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files",
    "backups": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/backups",
    "groups": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/groups"
  }
}
```

#### PUT /servers/{server_id}
Update server configuration.

**Request Body:**
```json
{
  "name": "updated-survival-world",
  "description": "Updated description",
  "memory_mb": 6144,
  "auto_restart": false,
  "configuration": {
    "max_players": 25,
    "view_distance": 12
  }
}
```

#### DELETE /servers/{server_id}
Delete a server (soft delete).

**Response (204 No Content)**

#### POST /servers/{server_id}/start
Start a server.

**Request Body (Optional):**
```json
{
  "force": false,
  "wait_for_startup": true
}
```

**Response (202 Accepted):**
```json
{
  "message": "Server start initiated",
  "job_id": "660e8400-e29b-41d4-a716-446655440000",
  "estimated_startup_time": 30,
  "_links": {
    "status": "/api/v2/jobs/660e8400-e29b-41d4-a716-446655440000",
    "server": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### POST /servers/{server_id}/stop
Stop a server.

**Request Body (Optional):**
```json
{
  "force": false,
  "save_world": true,
  "timeout_seconds": 30
}
```

#### POST /servers/{server_id}/restart
Restart a server.

#### GET /servers/{server_id}/status
Get real-time server status.

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "process_id": 12345,
  "uptime_seconds": 28800,
  "last_updated": "2024-01-16T14:30:00Z",
  "metrics": {
    "cpu_usage_percent": 15.5,
    "memory_usage_mb": 3072,
    "memory_max_mb": 4096,
    "disk_usage_mb": 2048,
    "network_in_kbps": 125,
    "network_out_kbps": 87,
    "tps": 19.8,
    "player_count": 5
  },
  "health": {
    "is_responding": true,
    "last_response_time_ms": 45,
    "error_count_last_hour": 0
  }
}
```

#### POST /servers/{server_id}/console
Send console command.

**Request Body:**
```json
{
  "command": "say Hello, world!",
  "wait_for_response": true,
  "timeout_seconds": 5
}
```

**Response (200 OK):**
```json
{
  "command": "say Hello, world!",
  "executed_at": "2024-01-16T14:30:00Z",
  "response": "[Server] Hello, world!",
  "execution_time_ms": 15,
  "success": true
}
```

#### GET /servers/{server_id}/logs
Get server logs.

**Query Parameters:**
- `lines` (integer, default: 100): Number of log lines
- `since` (ISO datetime): Get logs since timestamp
- `level` (string): Filter by log level
- `search` (string): Search in log content

**Response (200 OK):**
```json
{
  "logs": [
    {
      "timestamp": "2024-01-16T14:30:00Z",
      "level": "INFO",
      "thread": "Server thread",
      "message": "[Server] Hello, world!",
      "raw_line": "[14:30:00] [Server thread/INFO]: [Server] Hello, world!"
    }
  ],
  "total_lines": 1,
  "has_more": false,
  "_links": {
    "websocket": "/ws/servers/550e8400-e29b-41d4-a716-446655440000/logs"
  }
}
```

### 4. Group Management Endpoints

#### GET /groups
List user's groups.

**Response (200 OK):**
```json
{
  "groups": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "admins",
      "description": "Server administrators",
      "group_type": "op",
      "is_public": false,
      "player_count": 3,
      "server_count": 2,
      "created_at": "2024-01-15T10:30:00Z",
      "players": [
        {
          "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
          "username": "player1",
          "display_name": "Player One",
          "added_at": "2024-01-15T11:00:00Z"
        }
      ],
      "_links": {
        "self": "/api/v2/groups/550e8400-e29b-41d4-a716-446655440000"
      }
    }
  ]
}
```

#### POST /groups
Create a new group.

**Request Body:**
```json
{
  "name": "moderators",
  "description": "Server moderators",
  "group_type": "op",
  "is_public": false
}
```

#### GET /groups/{group_id}
Get group details.

#### PUT /groups/{group_id}
Update group.

#### DELETE /groups/{group_id}
Delete group.

#### POST /groups/{group_id}/players
Add player to group.

**Request Body:**
```json
{
  "username": "new_player"
}
```

**Response (201 Created):**
```json
{
  "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
  "username": "new_player",
  "display_name": "New Player",
  "added_at": "2024-01-16T14:30:00Z",
  "skin_url": "https://textures.minecraft.net/texture/...",
  "profile": {
    "first_seen": "2024-01-10T12:00:00Z",
    "last_seen": "2024-01-16T13:45:00Z",
    "is_online": false
  }
}
```

#### DELETE /groups/{group_id}/players/{player_uuid}
Remove player from group.

#### POST /groups/{group_id}/servers/{server_id}
Attach group to server.

**Request Body:**
```json
{
  "priority": 10
}
```

#### DELETE /groups/{group_id}/servers/{server_id}
Detach group from server.

### 5. Backup Management Endpoints

#### GET /servers/{server_id}/backups
List server backups.

**Response (200 OK):**
```json
{
  "backups": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "daily-backup-2024-01-16",
      "description": "Automated daily backup",
      "file_path": "/backups/server_1_20240116_143000.tar.gz",
      "file_size_bytes": 157286400,
      "file_size_human": "150 MB",
      "compression_ratio": 0.65,
      "backup_type": "scheduled",
      "status": "completed",
      "world_name": "world",
      "minecraft_version": "1.21.5",
      "created_at": "2024-01-16T14:30:00Z",
      "completed_at": "2024-01-16T14:32:15Z",
      "duration_seconds": 135,
      "created_by": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "system"
      },
      "_links": {
        "self": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000",
        "download": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000/download",
        "restore": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000/restore"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "pages": 1
  },
  "summary": {
    "total_backups": 15,
    "total_size_bytes": 2361344000,
    "total_size_human": "2.2 GB",
    "success_rate": 98.5,
    "latest_backup": "2024-01-16T14:30:00Z"
  }
}
```

#### POST /servers/{server_id}/backups
Create a manual backup.

**Request Body:**
```json
{
  "name": "pre-update-backup",
  "description": "Backup before updating to 1.21.6",
  "include_world": true,
  "include_plugins": true,
  "include_config": true,
  "compress": true
}
```

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Backup creation initiated",
  "job_id": "660e8400-e29b-41d4-a716-446655440000",
  "estimated_duration_seconds": 120,
  "_links": {
    "status": "/api/v2/jobs/660e8400-e29b-41d4-a716-446655440000",
    "backup": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### GET /backups/{backup_id}
Get backup details.

#### DELETE /backups/{backup_id}
Delete backup.

#### POST /backups/{backup_id}/restore
Restore backup to new server.

**Request Body:**
```json
{
  "new_server_name": "restored-survival",
  "port": 25567,
  "memory_mb": 4096,
  "start_after_restore": false
}
```

#### GET /backups/{backup_id}/download
Download backup file.

**Response**: Binary file download with appropriate headers.

#### GET /servers/{server_id}/backup-schedules
List backup schedules.

#### POST /servers/{server_id}/backup-schedules
Create backup schedule.

**Request Body:**
```json
{
  "name": "nightly-backup",
  "cron_expression": "0 2 * * *",
  "timezone": "UTC",
  "retention_count": 7,
  "retention_days": 30,
  "only_if_players_online": false,
  "compress_backup": true,
  "is_active": true
}
```

### 6. Template Management Endpoints

#### GET /templates
List templates.

**Query Parameters:**
- `category` (string): Filter by category
- `minecraft_version` (string): Filter by Minecraft version
- `server_type` (string): Filter by server type
- `is_public` (boolean): Show only public templates
- `tags` (array): Filter by tags
- `sort` (string): Sort by (rating, downloads, created_at)

**Response (200 OK):**
```json
{
  "templates": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Survival Plus",
      "description": "Enhanced survival experience with quality-of-life plugins",
      "category": "survival",
      "minecraft_version": "1.21.5",
      "server_type": "paper",
      "memory_mb": 2048,
      "tags": ["survival", "plugins", "economy"],
      "is_public": true,
      "rating": 4.7,
      "download_count": 156,
      "created_at": "2024-01-10T10:00:00Z",
      "created_by": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "template_creator"
      },
      "preview": {
        "plugin_count": 12,
        "configuration_files": 8,
        "estimated_setup_time": "5 minutes"
      },
      "_links": {
        "self": "/api/v2/templates/550e8400-e29b-41d4-a716-446655440000",
        "clone": "/api/v2/templates/550e8400-e29b-41d4-a716-446655440000/clone"
      }
    }
  ]
}
```

#### POST /templates
Create template.

#### GET /templates/{template_id}
Get template details.

#### POST /templates/{template_id}/clone
Clone template to create new server.

**Request Body:**
```json
{
  "server_name": "my-survival-server",
  "port": 25565,
  "memory_mb": 4096,
  "configuration_overrides": {
    "max_players": 15,
    "difficulty": "hard"
  }
}
```

### 7. File Management Endpoints

#### GET /servers/{server_id}/files
Browse server files.

**Query Parameters:**
- `path` (string): Directory path to browse
- `file_type` (string): Filter by file type
- `search` (string): Search filenames

**Response (200 OK):**
```json
{
  "current_path": "/plugins",
  "files": [
    {
      "name": "EssentialsX.jar",
      "path": "/plugins/EssentialsX.jar",
      "type": "file",
      "size_bytes": 1048576,
      "size_human": "1.0 MB",
      "mime_type": "application/java-archive",
      "is_editable": false,
      "modified_at": "2024-01-15T12:00:00Z",
      "permissions": "rw-r--r--",
      "_links": {
        "download": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/download?path=/plugins/EssentialsX.jar"
      }
    },
    {
      "name": "config.yml",
      "path": "/plugins/EssentialsX/config.yml",
      "type": "file",
      "size_bytes": 4096,
      "size_human": "4.0 KB",
      "mime_type": "text/yaml",
      "is_editable": true,
      "modified_at": "2024-01-16T10:30:00Z",
      "_links": {
        "view": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/view?path=/plugins/EssentialsX/config.yml",
        "edit": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/edit?path=/plugins/EssentialsX/config.yml",
        "history": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/history?path=/plugins/EssentialsX/config.yml"
      }
    }
  ],
  "breadcrumbs": [
    {
      "name": "root",
      "path": "/",
      "_links": {"browse": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files?path=/"}
    },
    {
      "name": "plugins",
      "path": "/plugins",
      "_links": {"browse": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files?path=/plugins"}
    }
  ]
}
```

#### GET /servers/{server_id}/files/view
View file content.

**Query Parameters:**
- `path` (string, required): File path

**Response (200 OK):**
```json
{
  "file_path": "/server.properties",
  "content": "# Minecraft server properties\nserver-port=25565\ngamemode=survival\n...",
  "content_type": "text/plain",
  "encoding": "utf-8",
  "size_bytes": 2048,
  "line_count": 45,
  "is_binary": false,
  "last_modified": "2024-01-16T10:30:00Z",
  "syntax_highlighting": "properties"
}
```

#### PUT /servers/{server_id}/files/edit
Edit file content.

**Query Parameters:**
- `path` (string, required): File path

**Request Body:**
```json
{
  "content": "# Updated Minecraft server properties\nserver-port=25565\ngamemode=creative\n...",
  "create_backup": true,
  "encoding": "utf-8"
}
```

#### POST /servers/{server_id}/files/upload
Upload files.

**Request**: Multipart form data with files

#### GET /servers/{server_id}/files/download
Download file.

**Query Parameters:**
- `path` (string, required): File path

#### DELETE /servers/{server_id}/files/delete
Delete file.

#### GET /servers/{server_id}/files/history
Get file edit history.

**Query Parameters:**
- `path` (string, required): File path

**Response (200 OK):**
```json
{
  "file_path": "/server.properties",
  "history": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "version": 3,
      "change_type": "modified",
      "size_bytes": 2048,
      "content_hash": "abc123...",
      "modified_at": "2024-01-16T10:30:00Z",
      "modified_by": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "john_doe"
      },
      "_links": {
        "view": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/history/550e8400-e29b-41d4-a716-446655440000",
        "restore": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/restore/550e8400-e29b-41d4-a716-446655440000"
      }
    }
  ]
}
```

### 8. Administrative Endpoints

#### GET /admin/users
List all users (Admin only).

#### GET /admin/servers
List all servers (Admin only).

#### GET /admin/system/info
Get system information.

**Response (200 OK):**
```json
{
  "version": "2.0.0",
  "uptime_seconds": 86400,
  "database": {
    "type": "postgresql",
    "version": "15.4",
    "connection_pool": {
      "active": 5,
      "idle": 15,
      "max": 20
    }
  },
  "cache": {
    "type": "redis",
    "version": "7.0.5",
    "memory_usage_mb": 128,
    "hit_rate": 0.95
  },
  "statistics": {
    "total_users": 42,
    "active_users": 38,
    "total_servers": 156,
    "running_servers": 23,
    "total_backups": 1247,
    "total_backup_size_gb": 45.6
  },
  "health": {
    "database": "healthy",
    "cache": "healthy",
    "file_system": "healthy",
    "background_jobs": "healthy"
  }
}
```

#### POST /admin/system/sync
Synchronize filesystem with database.

#### GET /admin/audit
Get audit logs.

#### GET /admin/metrics
Get system metrics.

### 9. Job Status Endpoints

#### GET /jobs/{job_id}
Get job status.

**Response (200 OK):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "type": "server_start",
  "status": "completed",
  "progress": 100,
  "started_at": "2024-01-16T14:30:00Z",
  "completed_at": "2024-01-16T14:30:45Z",
  "duration_seconds": 45,
  "result": {
    "server_id": "550e8400-e29b-41d4-a716-446655440000",
    "final_status": "running",
    "process_id": 12345
  },
  "logs": [
    {
      "timestamp": "2024-01-16T14:30:15Z",
      "level": "INFO",
      "message": "Starting server process..."
    },
    {
      "timestamp": "2024-01-16T14:30:45Z",
      "level": "INFO",
      "message": "Server started successfully"
    }
  ]
}
```

## WebSocket API

### Connection Endpoints

#### /ws/servers/{server_id}/status
Real-time server status updates.

**Connected Message:**
```json
{
  "type": "connected",
  "server_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-16T14:30:00Z"
}
```

**Status Update Message:**
```json
{
  "type": "status_update",
  "server_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "metrics": {
    "cpu_usage_percent": 15.5,
    "memory_usage_mb": 3072,
    "player_count": 5,
    "tps": 19.8
  },
  "timestamp": "2024-01-16T14:30:30Z"
}
```

#### /ws/servers/{server_id}/logs
Real-time log streaming.

**Log Message:**
```json
{
  "type": "log_line",
  "server_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-16T14:30:00Z",
  "level": "INFO",
  "thread": "Server thread",
  "message": "[Server] Player joined the game",
  "raw_line": "[14:30:00] [Server thread/INFO]: [Server] Player joined the game"
}
```

#### /ws/servers/{server_id}/console
Interactive console session.

**Send Command:**
```json
{
  "type": "command",
  "command": "list",
  "correlation_id": "cmd_123"
}
```

**Command Response:**
```json
{
  "type": "command_response",
  "correlation_id": "cmd_123",
  "command": "list",
  "response": "There are 5 of a max of 20 players online: player1, player2, player3, player4, player5",
  "success": true,
  "timestamp": "2024-01-16T14:30:00Z"
}
```

#### /ws/notifications
Global user notifications.

**Notification Message:**
```json
{
  "type": "notification",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "category": "server",
  "title": "Server Started",
  "message": "Your server 'survival-world' has started successfully",
  "severity": "info",
  "data": {
    "server_id": "550e8400-e29b-41d4-a716-446655440000",
    "server_name": "survival-world"
  },
  "timestamp": "2024-01-16T14:30:00Z",
  "read": false,
  "_links": {
    "server": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

## Error Handling

### Standard Error Response Format
```json
{
  "error": {
    "type": "validation_error",
    "code": "INVALID_INPUT",
    "message": "Request validation failed",
    "details": [
      {
        "field": "memory_mb",
        "message": "Memory must be between 512 and 32768 MB",
        "value": 100
      }
    ],
    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2024-01-16T14:30:00Z"
  },
  "_links": {
    "documentation": "/api/docs#error-codes"
  }
}
```

### HTTP Status Codes
- **200 OK**: Successful GET, PUT requests
- **201 Created**: Successful POST requests
- **202 Accepted**: Async operations initiated
- **204 No Content**: Successful DELETE requests
- **400 Bad Request**: Invalid request data
- **401 Unauthorized**: Authentication required
- **403 Forbidden**: Insufficient permissions
- **404 Not Found**: Resource not found
- **409 Conflict**: Resource conflict (e.g., port in use)
- **422 Unprocessable Entity**: Validation errors
- **429 Too Many Requests**: Rate limit exceeded
- **500 Internal Server Error**: Server errors

### Error Codes
```python
class ErrorCodes:
    # Authentication errors
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    ACCOUNT_NOT_APPROVED = "ACCOUNT_NOT_APPROVED"
    
    # Authorization errors
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    RESOURCE_NOT_OWNED = "RESOURCE_NOT_OWNED"
    
    # Validation errors
    INVALID_INPUT = "INVALID_INPUT"
    REQUIRED_FIELD = "REQUIRED_FIELD"
    FIELD_TOO_LONG = "FIELD_TOO_LONG"
    INVALID_FORMAT = "INVALID_FORMAT"
    
    # Resource errors
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    
    # Server management errors
    SERVER_NOT_RUNNING = "SERVER_NOT_RUNNING"
    SERVER_ALREADY_RUNNING = "SERVER_ALREADY_RUNNING"
    PORT_UNAVAILABLE = "PORT_UNAVAILABLE"
    INVALID_SERVER_TYPE = "INVALID_SERVER_TYPE"
    
    # System errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
```

## Rate Limiting

### Rate Limit Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640995200
X-RateLimit-Window: 60
```

### Rate Limits by Endpoint Category
- **Authentication**: 5 requests per minute
- **Server Control**: 10 requests per minute per server
- **Console Commands**: 30 requests per minute per server
- **General API**: 100 requests per minute
- **File Operations**: 20 requests per minute per server
- **WebSocket Connections**: 1000 messages per minute

## API Versioning

### URL Versioning
- Current version: `/api/v2/`
- Previous version: `/api/v1/` (deprecated)

### Version Headers
```
API-Version: 2.0
API-Deprecated-Version: 1.0
API-Sunset-Date: 2024-12-31
```

### Backward Compatibility
- V1 endpoints will be supported until 2024-12-31
- V2 endpoints are stable and will be maintained
- Breaking changes will increment major version

## OpenAPI Specification

The complete OpenAPI 3.0 specification is automatically generated by FastAPI and available at:
- **Swagger UI**: `/api/docs`
- **ReDoc**: `/api/redoc`
- **OpenAPI JSON**: `/api/openapi.json`

### Example OpenAPI Snippet
```yaml
openapi: 3.0.0
info:
  title: Minecraft Server Dashboard API V2
  version: 2.0.0
  description: A comprehensive API for managing multiple Minecraft servers
  contact:
    name: API Support
    email: api-support@example.com
  license:
    name: MIT License
    url: https://opensource.org/licenses/MIT

servers:
  - url: https://api.mcserver.example.com/api/v2
    description: Production server
  - url: http://localhost:8000/api/v2
    description: Development server

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    Server:
      type: object
      required:
        - name
        - minecraft_version
        - memory_mb
      properties:
        id:
          type: string
          format: uuid
          readOnly: true
        name:
          type: string
          minLength: 3
          maxLength: 50
          pattern: '^[a-zA-Z0-9_-]+$'
        description:
          type: string
          maxLength: 500
        status:
          type: string
          enum: [stopped, starting, running, stopping, crashed]
          readOnly: true
        port:
          type: integer
          minimum: 1024
          maximum: 65535
        minecraft_version:
          type: string
          pattern: '^\d+\.\d+(\.\d+)?$'
        memory_mb:
          type: integer
          minimum: 512
          maximum: 32768

paths:
  /servers:
    get:
      summary: List servers
      tags: [Servers]
      security:
        - BearerAuth: []
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            minimum: 1
            default: 1
        - name: limit
          in: query
          schema:
            type: integer
            minimum: 1
            maximum: 100
            default: 20
      responses:
        '200':
          description: List of servers
          content:
            application/json:
              schema:
                type: object
                properties:
                  servers:
                    type: array
                    items:
                      $ref: '#/components/schemas/Server'
```

This comprehensive API design provides a complete specification for implementing the Minecraft Server Dashboard API V2 with consistent patterns, proper error handling, and extensive functionality coverage.