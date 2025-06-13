# API Reference

Complete API documentation for the Minecraft Server Dashboard API.

## Base Information

**Base URL**: `/api/v1/`  
**Authentication**: JWT Bearer token (except where noted)  
**Content Type**: `application/json`

### Authentication Header
```
Authorization: Bearer <access_token>
```

### WebSocket Authentication
WebSocket endpoints use token as query parameter:
```
?token=<access_token>
```

## Response Formats

### Success Response
```json
{
  "id": 1,
  "name": "example",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Paginated Response
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "size": 20
}
```

### Error Response
```json
{
  "detail": "Error description"
}
```

### HTTP Status Codes
- `200` - Success
- `201` - Created
- `204` - No Content
- `400` - Bad Request
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `422` - Validation Error
- `500` - Internal Server Error

## Endpoints

### System Monitoring

#### Health Check
```http
GET /health
```
**Authentication**: None  
**Description**: Get system health status with service information

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "services": {
    "database": "operational",
    "database_integration": "operational", 
    "backup_scheduler": "operational",
    "websocket_service": "operational"
  },
  "failed_services": [],
  "message": "All services operational"
}
```

#### Performance Metrics
```http
GET /metrics
```
**Authentication**: None  
**Description**: Get performance metrics and statistics

---

### Authentication

#### Login
```http
POST /auth/token
```
**Authentication**: None  
**Content-Type**: `application/x-www-form-urlencoded`

**Request Body**:
```
username=user@example.com&password=password123
```

**Response**:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

#### Refresh Token
```http
POST /auth/refresh
```
**Authentication**: None

**Request Body**:
```json
{
  "refresh_token": "eyJ..."
}
```

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

#### Logout
```http
POST /auth/logout
```
**Authentication**: Required

**Request Body**:
```json
{
  "refresh_token": "eyJ..."
}
```

---

### User Management

#### Register User
```http
POST /users/register
```
**Authentication**: None

**Request Body**:
```json
{
  "username": "newuser",
  "email": "user@example.com", 
  "password": "password123",
  "full_name": "New User"
}
```

#### Get Current User
```http
GET /users/me
```
**Authentication**: Required

#### Update Current User
```http
PUT /users/me
```
**Authentication**: Required

**Request Body**:
```json
{
  "full_name": "Updated Name",
  "email": "newemail@example.com"
}
```

#### Update Password
```http
PUT /users/me/password
```
**Authentication**: Required

**Request Body**:
```json
{
  "current_password": "oldpass",
  "new_password": "newpass"
}
```

#### Delete Own Account
```http
DELETE /users/me
```
**Authentication**: Required

#### List All Users (Admin Only)
```http
GET /users/
```
**Authentication**: Admin role required

#### Approve User (Admin Only)
```http
POST /users/approve/{user_id}
```
**Authentication**: Admin role required

#### Change User Role (Admin Only)
```http
PUT /users/role/{user_id}
```
**Authentication**: Admin role required

**Request Body**:
```json
{
  "role": "operator"
}
```

#### Delete User (Admin Only)
```http
DELETE /users/{user_id}
```
**Authentication**: Admin role required

---

### Server Management

#### Create Server
```http
POST /servers/
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "name": "MyServer",
  "version": "1.20.1",
  "server_type": "vanilla",
  "max_memory": 2048,
  "description": "My Minecraft server"
}
```

#### List Servers
```http
GET /servers/
```
**Authentication**: Required  
**Query Parameters**:
- `page` (int): Page number (default: 1)
- `size` (int): Page size (default: 20)
- `search` (string): Search term

#### Get Server Details
```http
GET /servers/{server_id}
```
**Authentication**: Owner/Admin access required

#### Update Server
```http
PUT /servers/{server_id}
```
**Authentication**: Owner/Admin access required

**Request Body**:
```json
{
  "name": "Updated Server Name",
  "description": "Updated description",
  "max_memory": 4096
}
```

#### Delete Server
```http
DELETE /servers/{server_id}
```
**Authentication**: Owner/Admin access required

#### Start Server
```http
POST /servers/{server_id}/start
```
**Authentication**: Owner/Admin access required

#### Stop Server
```http
POST /servers/{server_id}/stop
```
**Authentication**: Owner/Admin access required

#### Restart Server
```http
POST /servers/{server_id}/restart
```
**Authentication**: Owner/Admin access required

#### Get Server Status
```http
GET /servers/{server_id}/status
```
**Authentication**: Owner/Admin access required

**Response**:
```json
{
  "status": "running",
  "pid": 12345,
  "uptime": 3600,
  "memory_usage": 1024
}
```

#### Send Console Command
```http
POST /servers/{server_id}/command
```
**Authentication**: Owner/Admin access required

**Request Body**:
```json
{
  "command": "say Hello World"
}
```

#### Get Server Logs
```http
GET /servers/{server_id}/logs
```
**Authentication**: Owner/Admin access required  
**Query Parameters**:
- `lines` (int): Number of log lines (default: 100)

#### Export Server
```http
GET /servers/{server_id}/export
```
**Authentication**: Owner/Admin access required  
**Response**: ZIP file download

#### Import Server
```http
POST /servers/import
```
**Authentication**: Operator+ role required  
**Content-Type**: `multipart/form-data`

**Request Body**:
- `file`: ZIP file
- `name`: Server name
- `description`: Server description

#### Get Supported Versions
```http
GET /servers/versions/supported
```
**Authentication**: Required

**Response**:
```json
{
  "versions": [
    {
      "version": "1.20.1",
      "type": "release",
      "url": "https://..."
    }
  ]
}
```

#### Sync Server States (Admin Only)
```http
POST /servers/sync
```
**Authentication**: Admin role required

#### Get Cache Statistics (Admin Only)
```http
GET /servers/cache/stats
```
**Authentication**: Admin role required

#### Cleanup Cache (Admin Only)
```http
POST /servers/cache/cleanup
```
**Authentication**: Admin role required

---

### Group Management

#### Create Group
```http
POST /groups/
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "name": "Admins",
  "group_type": "op",
  "description": "Server administrators"
}
```

#### List Groups
```http
GET /groups/
```
**Authentication**: Required (shows user's groups)

#### Get Group Details
```http
GET /groups/{group_id}
```
**Authentication**: Owner/Admin access required

#### Update Group
```http
PUT /groups/{group_id}
```
**Authentication**: Owner/Admin access required

**Request Body**:
```json
{
  "name": "Updated Group Name",
  "description": "Updated description"
}
```

#### Delete Group
```http
DELETE /groups/{group_id}
```
**Authentication**: Owner/Admin access required

#### Add Player to Group
```http
POST /groups/{group_id}/players
```
**Authentication**: Owner/Admin access required

**Request Body**:
```json
{
  "username": "player123"
}
```

#### Remove Player from Group
```http
DELETE /groups/{group_id}/players/{player_uuid}
```
**Authentication**: Owner/Admin access required

#### Attach Group to Server
```http
POST /groups/{group_id}/servers
```
**Authentication**: Owner/Admin access required

**Request Body**:
```json
{
  "server_id": 1,
  "priority": 1
}
```

#### Detach Group from Server
```http
DELETE /groups/{group_id}/servers/{server_id}
```
**Authentication**: Owner/Admin access required

#### Get Servers Attached to Group
```http
GET /groups/{group_id}/servers
```
**Authentication**: Owner/Admin access required

#### Get Groups Attached to Server
```http
GET /groups/servers/{server_id}
```
**Authentication**: Owner/Admin access required

---

### Backup Management

#### Create Backup
```http
POST /backups/servers/{server_id}/backups
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "name": "Weekly Backup",
  "description": "Weekly server backup"
}
```

#### List Server Backups
```http
GET /backups/servers/{server_id}/backups
```
**Authentication**: Owner/Admin access required

#### List All Backups (Admin Only)
```http
GET /backups/backups
```
**Authentication**: Admin role required

#### Get Backup Details
```http
GET /backups/backups/{backup_id}
```
**Authentication**: Owner/Admin access required

#### Restore Backup
```http
POST /backups/backups/{backup_id}/restore
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "server_name": "Restored Server",
  "description": "Server restored from backup"
}
```

#### Restore Backup with Template
```http
POST /backups/backups/{backup_id}/restore-with-template
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "server_name": "Restored Server",
  "template_name": "Backup Template",
  "template_description": "Template from backup"
}
```

#### Delete Backup
```http
DELETE /backups/backups/{backup_id}
```
**Authentication**: Operator+ role required

#### Get Server Backup Statistics
```http
GET /backups/servers/{server_id}/backups/statistics
```
**Authentication**: Owner/Admin access required

#### Get Global Backup Statistics (Admin Only)
```http
GET /backups/backups/statistics
```
**Authentication**: Admin role required

---

### Backup Scheduler

#### Create Backup Schedule
```http
POST /backup-scheduler/scheduler/servers/{server_id}/schedule
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "cron_expression": "0 2 * * *",
  "enabled": true,
  "backup_name_template": "auto-backup-{timestamp}",
  "description": "Daily 2AM backup"
}
```

#### Get Backup Schedule
```http
GET /backup-scheduler/scheduler/servers/{server_id}/schedule
```
**Authentication**: Owner/Admin access required

#### Update Backup Schedule
```http
PUT /backup-scheduler/scheduler/servers/{server_id}/schedule
```
**Authentication**: Operator+ role required

#### Delete Backup Schedule
```http
DELETE /backup-scheduler/scheduler/servers/{server_id}/schedule
```
**Authentication**: Operator+ role required

#### Get Schedule Execution Logs
```http
GET /backup-scheduler/scheduler/servers/{server_id}/logs
```
**Authentication**: Owner/Admin access required

#### Get Scheduler Status (Admin Only)
```http
GET /backup-scheduler/scheduler/status
```
**Authentication**: Admin role required

#### List All Schedules (Admin Only)
```http
GET /backup-scheduler/scheduler/schedules
```
**Authentication**: Admin role required

---

### Template Management

#### Create Template from Server
```http
POST /templates/from-server/{server_id}
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "name": "My Template",
  "description": "Template created from server",
  "is_public": false
}
```

#### Create Custom Template
```http
POST /templates/
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "name": "Custom Template",
  "description": "Custom server template",
  "version": "1.20.1",
  "server_type": "vanilla",
  "configuration": {
    "max_memory": 2048,
    "server_properties": {...}
  },
  "is_public": false
}
```

#### List Templates
```http
GET /templates/
```
**Authentication**: Required  
**Query Parameters**:
- `page` (int): Page number
- `size` (int): Page size
- `public_only` (bool): Show only public templates

#### Get Template Details
```http
GET /templates/{template_id}
```
**Authentication**: Required (public templates or owned templates)

#### Update Template
```http
PUT /templates/{template_id}
```
**Authentication**: Owner/Admin access required

#### Delete Template
```http
DELETE /templates/{template_id}
```
**Authentication**: Owner/Admin access required

#### Clone Template
```http
POST /templates/{template_id}/clone
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "server_name": "Cloned Server",
  "description": "Server from template"
}
```

#### Get Template Statistics
```http
GET /templates/statistics
```
**Authentication**: Required

---

### File Management

#### List Files/Directories
```http
GET /files/servers/{server_id}/files[/{path}]
```
**Authentication**: Owner/Admin access required  
**Path Parameter**: Optional file path

#### Read File Content
```http
GET /files/servers/{server_id}/files/{file_path}/read
```
**Authentication**: Owner/Admin access required

#### Download File/Directory
```http
GET /files/servers/{server_id}/files/{file_path}/download
```
**Authentication**: Owner/Admin access required

#### Write File Content
```http
PUT /files/servers/{server_id}/files/{file_path}
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "content": "file content here",
  "encoding": "utf-8"
}
```

#### Delete File/Directory
```http
DELETE /files/servers/{server_id}/files/{file_path}
```
**Authentication**: Operator+ role required

#### Rename File/Directory
```http
PATCH /files/servers/{server_id}/files/{file_path}/rename
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "new_name": "new_filename.txt"
}
```

#### Upload File
```http
POST /files/servers/{server_id}/files/upload
```
**Authentication**: Operator+ role required  
**Content-Type**: `multipart/form-data`

**Request Body**:
- `file`: File to upload
- `path`: Target directory path (optional)

#### Search Files
```http
POST /files/servers/{server_id}/files/search
```
**Authentication**: Owner/Admin access required

**Request Body**:
```json
{
  "query": "search term",
  "path": "/specific/directory",
  "file_types": [".txt", ".json"]
}
```

#### Create Directory
```http
POST /files/servers/{server_id}/files/{directory_path}/directories
```
**Authentication**: Operator+ role required

**Request Body**:
```json
{
  "name": "new_directory"
}
```

#### Get File Edit History
```http
GET /files/servers/{server_id}/files/{file_path}/history
```
**Authentication**: Owner/Admin access required

#### Get Version Content
```http
GET /files/servers/{server_id}/files/{file_path}/history/{version}
```
**Authentication**: Owner/Admin access required

#### Restore from Version
```http
POST /files/servers/{server_id}/files/{file_path}/history/{version}/restore
```
**Authentication**: Operator+ role required

#### Delete Version (Admin Only)
```http
DELETE /files/servers/{server_id}/files/{file_path}/history/{version}
```
**Authentication**: Admin role required

#### Get File History Statistics
```http
GET /files/servers/{server_id}/files/history/statistics
```
**Authentication**: Owner/Admin access required

---

### WebSocket Endpoints

#### Server Logs and Status
```
WS /ws/servers/{server_id}/logs?token=<access_token>
```
**Authentication**: Owner/Admin access required

**Messages Received**:
```json
{
  "type": "log",
  "data": "Server log line",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

```json
{
  "type": "status",
  "data": {
    "status": "running",
    "pid": 12345
  }
}
```

#### Server Status Only
```
WS /ws/servers/{server_id}/status?token=<access_token>
```
**Authentication**: Owner/Admin access required

#### System Notifications
```
WS /ws/notifications?token=<access_token>
```
**Authentication**: Required

**Messages Received**:
```json
{
  "type": "notification",
  "message": "System notification",
  "level": "info"
}
```

---

### Audit Logs

#### Get Audit Logs
```http
GET /audit/logs
```
**Authentication**: Required (own logs) / Admin (all logs)  
**Query Parameters**:
- `page` (int): Page number
- `size` (int): Page size  
- `action` (string): Filter by action
- `start_date` (string): Start date (ISO format)
- `end_date` (string): End date (ISO format)

#### Get Security Alerts (Admin Only)
```http
GET /audit/security-alerts
```
**Authentication**: Admin role required

#### Get User Activity
```http
GET /audit/user/{user_id}/activity
```
**Authentication**: Own activity or Admin role required

#### Get Audit Statistics (Admin Only)
```http
GET /audit/statistics
```
**Authentication**: Admin role required

---

## Role-Based Access Control

### User Roles
- **User**: View own resources, basic file read access
- **Operator**: Create/manage servers, groups, templates, backups; full file operations  
- **Admin**: Full system access including user management and system operations

### Access Patterns
- **Public**: Health checks, supported versions, user registration
- **Authenticated**: Own resource access, basic operations
- **Owner/Admin**: Resource-specific operations (owners for their resources, admins for all)
- **Operator+**: Resource creation, file modifications, backup operations
- **Admin Only**: System-wide operations, user management, security features

### Resource Ownership
Users can only access resources they own, except Admins who can access all resources. Some operations require specific roles regardless of ownership.