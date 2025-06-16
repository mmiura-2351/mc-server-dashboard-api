# Current API Endpoints - Minecraft Server Dashboard API V1

## Overview

This document provides a comprehensive inventory of all currently implemented API endpoints in the Minecraft Server Dashboard API V1. The API is built with FastAPI and provides comprehensive functionality for managing multiple Minecraft servers with authentication, real-time monitoring, backup management, and file operations.

## API Structure

- **Base URL**: `/api/v1`
- **Authentication**: JWT Bearer Token
- **Response Format**: JSON
- **Total Endpoints**: 65+
- **Domains**: 9 functional domains

## Domain Overview

| Domain | Endpoints | Key Features |
|--------|-----------|--------------|
| System Management | 2 | Health checks, metrics |
| Authentication | 3 | JWT login, refresh, logout |
| User Management | 9 | Registration, approval, profile management |
| Server Management | 17 | CRUD, control, monitoring, Java compatibility |
| Group Management | 9 | OP/whitelist groups, player management |
| Backup Management | 10 | Create, restore, download, statistics |
| File Management | 12 | CRUD, upload/download, version history |
| WebSocket | 3 | Real-time logs, status, notifications |
| Audit Logs | 4 | Security monitoring, activity tracking |

## Detailed Endpoint Inventory

### 1. System Management

#### Health & Monitoring
```
GET    /health                           # System health check (no auth)
GET    /metrics                          # Performance metrics (no auth)
```

### 2. Authentication (`/api/v1/auth`)

```
POST   /api/v1/auth/token               # User login (OAuth2 password flow)
POST   /api/v1/auth/refresh             # Refresh access token
POST   /api/v1/auth/logout              # User logout
```

### 3. User Management (`/api/v1/users`)

#### Registration & Approval
```
POST   /api/v1/users/register           # User registration (no auth)
POST   /api/v1/users/approve/{user_id}  # Approve user (Admin only)
PUT    /api/v1/users/role/{user_id}     # Change user role (Admin only)
```

#### Profile Management
```
GET    /api/v1/users/me                 # Get current user info
PUT    /api/v1/users/me                 # Update user info
PUT    /api/v1/users/me/password        # Change password
DELETE /api/v1/users/me                 # Delete account
```

#### User Administration
```
GET    /api/v1/users/                   # List all users (Admin only)
DELETE /api/v1/users/{user_id}          # Delete user (Admin only)
```

### 4. Server Management (`/api/v1/servers`)

#### Server CRUD Operations
```
POST   /api/v1/servers                  # Create server (Operator/Admin)
GET    /api/v1/servers                  # List servers (paginated)
GET    /api/v1/servers/{server_id}      # Get server details
PUT    /api/v1/servers/{server_id}      # Update server settings
DELETE /api/v1/servers/{server_id}      # Delete server
```

#### Server Control
```
POST   /api/v1/servers/{server_id}/start    # Start server
POST   /api/v1/servers/{server_id}/stop     # Stop server
POST   /api/v1/servers/{server_id}/restart  # Restart server
GET    /api/v1/servers/{server_id}/status   # Get server status
POST   /api/v1/servers/{server_id}/command  # Send server command
GET    /api/v1/servers/{server_id}/logs     # Get server logs
```

#### Utilities & Management
```
GET    /api/v1/servers/versions/supported           # List supported MC versions
GET    /api/v1/servers/cache/stats                 # JAR cache statistics (Admin only)
POST   /api/v1/servers/cache/cleanup               # Cache cleanup (Admin only)
GET    /api/v1/servers/java/compatibility          # Java compatibility info
GET    /api/v1/servers/java/validate/{mc_version}  # Validate Java for MC version
```

#### Import/Export
```
GET    /api/v1/servers/{server_id}/export  # Export server (ZIP)
POST   /api/v1/servers/import              # Import server (Operator/Admin)
```

### 5. Group Management (`/api/v1/groups`)

#### Group CRUD
```
POST   /api/v1/groups                   # Create group (Operator/Admin)
GET    /api/v1/groups                   # List groups (filtered)
GET    /api/v1/groups/{group_id}        # Get group details
PUT    /api/v1/groups/{group_id}        # Update group
DELETE /api/v1/groups/{group_id}        # Delete group
```

#### Player Management
```
POST   /api/v1/groups/{group_id}/players             # Add player
DELETE /api/v1/groups/{group_id}/players/{player_uuid}  # Remove player
```

#### Server Attachments
```
POST   /api/v1/groups/{group_id}/servers           # Attach group to server
DELETE /api/v1/groups/{group_id}/servers/{server_id}  # Detach from server
GET    /api/v1/groups/{group_id}/servers           # List attached servers
GET    /api/v1/groups/servers/{server_id}          # List groups on server
```

### 6. Backup Management (`/api/v1/backups`)

#### Backup CRUD
```
POST   /api/v1/backups/servers/{server_id}/backups        # Create backup (Operator/Admin)
POST   /api/v1/backups/servers/{server_id}/backups/upload # Upload backup (Operator/Admin)
GET    /api/v1/backups/servers/{server_id}/backups        # List server backups
GET    /api/v1/backups/backups                            # List all backups (Admin only)
GET    /api/v1/backups/backups/{backup_id}                # Get backup details
DELETE /api/v1/backups/backups/{backup_id}                # Delete backup (Operator/Admin)
```

#### Backup Operations
```
POST   /api/v1/backups/backups/{backup_id}/restore                    # Restore backup (Operator/Admin)
GET    /api/v1/backups/backups/{backup_id}/download                   # Download backup
```

#### Statistics & Scheduling
```
GET    /api/v1/backups/servers/{server_id}/backups/statistics  # Server backup stats
GET    /api/v1/backups/backups/statistics                      # Global backup stats (Admin only)
POST   /api/v1/backups/backups/scheduled                       # Create scheduled backup (Admin only)
```

### 7. File Management (`/api/v1/files`)

#### File Operations
```
GET    /api/v1/files/servers/{server_id}/files[/{path:path}]           # List files/directories
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/read   # Read file
PUT    /api/v1/files/servers/{server_id}/files/{file_path:path}        # Write file (Operator/Admin)
DELETE /api/v1/files/servers/{server_id}/files/{file_path:path}        # Delete file (Operator/Admin)
PATCH  /api/v1/files/servers/{server_id}/files/{file_path:path}/rename # Rename file (Operator/Admin)
```

#### Upload/Download
```
POST   /api/v1/files/servers/{server_id}/files/upload                     # Upload file (Operator/Admin)
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/download   # Download file
```

#### Directories & Search
```
POST   /api/v1/files/servers/{server_id}/files/{directory_path:path}/directories  # Create directory (Operator/Admin)
POST   /api/v1/files/servers/{server_id}/files/search                             # Search files
```

#### File History Management
```
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/history           # File edit history
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/history/{version} # Get version content
POST   /api/v1/files/servers/{server_id}/files/{file_path:path}/history/{version}/restore  # Restore version (Operator/Admin)
DELETE /api/v1/files/servers/{server_id}/files/{file_path:path}/history/{version}  # Delete version (Admin only)
GET    /api/v1/files/servers/{server_id}/files/history/statistics                 # File history stats
```

### 8. WebSocket (`/api/v1/ws`)

#### Real-time Communication
```
WebSocket  /api/v1/ws/servers/{server_id}/logs     # Server log streaming
WebSocket  /api/v1/ws/servers/{server_id}/status   # Server status updates
WebSocket  /api/v1/ws/notifications                # System notifications
```

### 9. Audit Logs (`/api/v1/audit`)

#### Audit Log Management
```
GET    /api/v1/audit/logs                      # List audit logs (filtered, paginated)
GET    /api/v1/audit/security-alerts          # Security alerts (Admin only)
GET    /api/v1/audit/user/{user_id}/activity  # User activity
GET    /api/v1/audit/statistics               # Audit statistics (Admin only)
```

## Authentication & Authorization

### JWT Token System
- **Access Token**: Short-lived (30 minutes)
- **Refresh Token**: Long-lived (7 days)
- **Token Blacklisting**: Supported for logout
- **Bearer Token**: Required in `Authorization` header for protected endpoints

### Role-Based Access Control (RBAC)

#### Role Hierarchy
1. **admin** - Full system access
2. **operator** - Server, group, backup, file management
3. **user** - Read-only access to owned resources

#### Permission Matrix

| Operation | User | Operator | Admin |
|-----------|------|----------|-------|
| View own servers | ✅ | ✅ | ✅ |
| Create/modify servers | ❌ | ✅ | ✅ |
| Server control (start/stop) | ❌ | ✅ | ✅ |
| Send server commands | ❌ | ✅ | ✅ |
| Create/manage groups | ❌ | ✅ | ✅ |
| Create/restore backups | ❌ | ✅ | ✅ |
| Modify files | ❌ | ✅ | ✅ |
| User management | ❌ | ❌ | ✅ |
| System administration | ❌ | ❌ | ✅ |
| View audit logs (all) | ❌ | ❌ | ✅ |

### Resource Ownership
- Users can only access resources they own or have been granted access to
- Operators can access all servers/groups/backups
- Admins have unrestricted access

## Key Features

### Security Features
- JWT authentication with refresh tokens
- Comprehensive audit logging
- Role-based access control
- Complete server command logging
- IP address and user agent tracking

### Real-time Features
- WebSocket-based server log streaming
- Real-time server status updates
- System-wide notifications
- Live console sessions

### Advanced Features
- File edit history and version management
- Java version compatibility management
- Server import/export functionality
- File search and content indexing

### Monitoring & Analytics
- Performance metrics endpoint
- Backup statistics and analytics
- File operation statistics
- User activity tracking
- Security alert system

## Error Handling

### Standard HTTP Status Codes
- `200` - Success
- `201` - Created
- `204` - No Content
- `400` - Bad Request
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `409` - Conflict
- `422` - Validation Error
- `500` - Internal Server Error

### Error Response Format
```json
{
  "detail": "Error message",
  "error_code": "SPECIFIC_ERROR_CODE",
  "field_errors": {
    "field_name": ["Field specific error"]
  }
}
```

## Pagination & Filtering

### Standard Pagination Parameters
- `skip` - Number of records to skip (default: 0)
- `limit` - Maximum records to return (default: 10, max: 100)

### Common Filter Parameters
- `search` - Text search across relevant fields
- `sort_by` - Field to sort by
- `sort_order` - `asc` or `desc`
- `created_after` / `created_before` - Date range filtering

## Rate Limiting

### Default Limits
- **General API**: 1000 requests per hour per user
- **Authentication**: 10 requests per minute per IP
- **Server Commands**: 60 requests per minute per user
- **File Operations**: 100 requests per minute per user

This streamlined API provides essential functionality for managing multiple Minecraft servers, covering core use cases with enterprise-grade security, monitoring, and management capabilities.