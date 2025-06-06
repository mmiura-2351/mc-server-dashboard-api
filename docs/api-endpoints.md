# API Endpoints Documentation

This document provides a comprehensive overview of all API endpoints implemented in the Minecraft Server Dashboard API.

## Base URL

All API endpoints are prefixed with `/api/v1/`

## Authentication

Most endpoints require authentication via JWT token. Include the token in the Authorization header:
```
Authorization: Bearer <token>
```

## Server Management (UC1-11)

### Server CRUD Operations

- **POST** `/servers` - Create a new server
  - Body: `ServerCreateRequest`
  - Response: `ServerResponse`
  - Permissions: operator, admin
  - Features: Template application, group attachment, JAR download

- **GET** `/servers` - List servers with pagination
  - Query: `page`, `size`
  - Response: `ServerListResponse`
  - Permissions: All users (filtered by ownership)

- **GET** `/servers/{server_id}` - Get server details
  - Response: `ServerResponse`
  - Permissions: Owner or admin

- **PUT** `/servers/{server_id}` - Update server configuration
  - Body: `ServerUpdateRequest`
  - Response: `ServerResponse`
  - Permissions: Owner or admin

- **DELETE** `/servers/{server_id}` - Delete server (soft delete)
  - Permissions: Owner or admin

### Server Process Control

- **POST** `/servers/{server_id}/start` - Start server
  - Response: `ServerStatusResponse`
  - Permissions: Owner or admin

- **POST** `/servers/{server_id}/stop` - Stop server
  - Query: `force` (boolean)
  - Permissions: Owner or admin

- **POST** `/servers/{server_id}/restart` - Restart server
  - Permissions: Owner or admin

- **GET** `/servers/{server_id}/status` - Get server status
  - Response: `ServerStatusResponse`
  - Permissions: Owner or admin

- **POST** `/servers/{server_id}/command` - Send console command
  - Body: `ServerCommandRequest`
  - Permissions: Owner or admin

- **GET** `/servers/{server_id}/logs` - Get server logs
  - Query: `lines` (1-1000)
  - Response: `ServerLogsResponse`
  - Permissions: Owner or admin

### Utility Endpoints

- **GET** `/servers/versions/supported` - Get supported Minecraft versions
  - Response: `SupportedVersionsResponse`
  - Permissions: Public

- **POST** `/servers/sync` - Sync server states (admin only)
  - Permissions: Admin

## Group Management (UC12-19)

### Group Operations

- **POST** `/groups` - Create a new group
  - Body: `GroupCreateRequest`
  - Response: `GroupResponse`
  - Permissions: operator, admin

- **GET** `/groups` - List user's groups
  - Query: `group_type` (op/whitelist)
  - Response: `GroupListResponse`
  - Permissions: All users

- **GET** `/groups/{group_id}` - Get group details
  - Response: `GroupResponse`
  - Permissions: Owner or admin

- **PUT** `/groups/{group_id}` - Update group
  - Body: `GroupUpdateRequest`
  - Response: `GroupResponse`
  - Permissions: Owner or admin

- **DELETE** `/groups/{group_id}` - Delete group
  - Permissions: Owner or admin

### Player Management

- **POST** `/groups/{group_id}/players` - Add player to group
  - Body: `PlayerAddRequest`
  - Response: `GroupResponse`
  - Permissions: Owner or admin

- **DELETE** `/groups/{group_id}/players/{player_uuid}` - Remove player from group
  - Response: `GroupResponse`
  - Permissions: Owner or admin

### Server Attachment

- **POST** `/groups/{group_id}/servers` - Attach group to server
  - Body: `ServerAttachRequest`
  - Permissions: Owner or admin

- **DELETE** `/groups/{group_id}/servers/{server_id}` - Detach group from server
  - Permissions: Owner or admin

- **GET** `/groups/{group_id}/servers` - Get servers attached to group
  - Response: `GroupServersResponse`
  - Permissions: Owner or admin

- **GET** `/groups/servers/{server_id}` - Get groups attached to server
  - Response: `ServerGroupsResponse`
  - Permissions: Owner or admin

## Backup Management (UC21-28)

### Backup Operations

- **POST** `/servers/{server_id}/backups` - Create backup
  - Body: `BackupCreateRequest`
  - Response: `BackupResponse`
  - Permissions: operator, admin

- **GET** `/servers/{server_id}/backups` - List server backups
  - Query: `page`, `size`, `backup_type`
  - Response: `BackupListResponse`
  - Permissions: Owner or admin

- **GET** `/backups` - List all backups (admin only)
  - Query: `page`, `size`, `backup_type`
  - Response: `BackupListResponse`
  - Permissions: Admin

- **GET** `/backups/{backup_id}` - Get backup details
  - Response: `BackupResponse`
  - Permissions: Owner or admin

- **POST** `/backups/{backup_id}/restore` - Restore backup
  - Body: `BackupRestoreRequest`
  - Response: `BackupOperationResponse`
  - Permissions: operator, admin

- **POST** `/backups/{backup_id}/restore-with-template` - Restore backup and create template
  - Body: `BackupRestoreWithTemplateRequest`
  - Response: `BackupRestoreWithTemplateResponse`
  - Permissions: operator, admin

- **DELETE** `/backups/{backup_id}` - Delete backup
  - Permissions: operator, admin

### Backup Statistics

- **GET** `/servers/{server_id}/backups/statistics` - Get server backup statistics
  - Response: `BackupStatisticsResponse`
  - Permissions: Owner or admin

- **GET** `/backups/statistics` - Get global backup statistics
  - Response: `BackupStatisticsResponse`
  - Permissions: Admin

### Backup Scheduling

- **POST** `/backups/scheduled` - Create scheduled backups
  - Body: `ScheduledBackupRequest`
  - Response: `BackupOperationResponse`
  - Permissions: Admin

- **GET** `/scheduler/status` - Get scheduler status
  - Permissions: Admin

- **POST** `/scheduler/servers/{server_id}/schedule` - Add server to backup schedule
  - Query: `interval_hours`, `max_backups`
  - Permissions: Admin

- **PUT** `/scheduler/servers/{server_id}/schedule` - Update server backup schedule
  - Query: `interval_hours`, `max_backups`, `enabled`
  - Permissions: Admin

- **DELETE** `/scheduler/servers/{server_id}/schedule` - Remove server from backup schedule
  - Permissions: Admin

## Template Management (UC7, UC37)

### Template Operations

- **POST** `/templates` - Create custom template
  - Body: `TemplateCreateRequest`
  - Response: `TemplateResponse`
  - Permissions: operator, admin

- **POST** `/templates/from-server` - Create template from server
  - Body: `TemplateFromServerRequest`
  - Response: `TemplateResponse`
  - Permissions: operator, admin

- **GET** `/templates` - List templates
  - Query: `page`, `size`, `minecraft_version`, `server_type`, `is_public`
  - Response: `TemplateListResponse`
  - Permissions: All users (filtered by access)

- **GET** `/templates/{template_id}` - Get template details
  - Response: `TemplateResponse`
  - Permissions: Owner, admin, or public

- **PUT** `/templates/{template_id}` - Update template
  - Body: `TemplateUpdateRequest`
  - Response: `TemplateResponse`
  - Permissions: Owner or admin

- **DELETE** `/templates/{template_id}` - Delete template
  - Permissions: Owner or admin

- **POST** `/templates/{template_id}/clone` - Clone template
  - Body: `TemplateCloneRequest`
  - Response: `TemplateResponse`
  - Permissions: All users (if accessible)

- **GET** `/templates/statistics` - Get template statistics
  - Response: `TemplateStatisticsResponse`
  - Permissions: All users

## File Management (UC29-37)

### File Operations

- **GET** `/servers/{server_id}/files` - List server files
  - Query: `path`, `file_type`
  - Response: `FileListResponse`
  - Permissions: Owner or admin

- **GET** `/servers/{server_id}/files/read` - Read file content
  - Query: `file_path`, `encoding`
  - Response: `FileReadResponse`
  - Permissions: Owner or admin

- **POST** `/servers/{server_id}/files/write` - Write file content
  - Body: `FileWriteRequest`
  - Response: `FileWriteResponse`
  - Permissions: Owner or admin (restricted files: admin only)

- **DELETE** `/servers/{server_id}/files` - Delete file/directory
  - Query: `file_path`
  - Response: `FileDeleteResponse`
  - Permissions: Owner or admin (restricted files: admin only)

- **POST** `/servers/{server_id}/files/upload` - Upload file
  - Form: `file`, `destination_path`, `extract_if_archive`
  - Response: `FileUploadResponse`
  - Permissions: Owner or admin

- **GET** `/servers/{server_id}/files/download` - Download file
  - Query: `file_path`
  - Response: File download
  - Permissions: Owner or admin

- **POST** `/servers/{server_id}/files/directory` - Create directory
  - Body: `DirectoryCreateRequest`
  - Response: `DirectoryCreateResponse`
  - Permissions: Owner or admin

- **GET** `/servers/{server_id}/files/search` - Search files
  - Query: `query`, `file_type`, `include_content`, `max_results`
  - Response: `FileSearchResponse`
  - Permissions: Owner or admin

## User Management (UC38-42)

### Authentication

- **POST** `/auth/register` - Register new user
  - Body: `UserRegisterRequest`
  - Response: `UserResponse`
  - Permissions: Public

- **POST** `/auth/token` - Login and get token
  - Body: `OAuth2PasswordRequestForm`
  - Response: `TokenResponse`
  - Permissions: Public

- **GET** `/auth/me` - Get current user info
  - Response: `UserResponse`
  - Permissions: Authenticated

### User Operations

- **GET** `/users` - List users (admin only)
  - Query: `page`, `size`, `is_approved`
  - Response: `UserListResponse`
  - Permissions: Admin

- **GET** `/users/{user_id}` - Get user details (admin only)
  - Response: `UserResponse`
  - Permissions: Admin

- **PUT** `/users/{user_id}` - Update user (admin only)
  - Body: `UserUpdateRequest`
  - Response: `UserResponse`
  - Permissions: Admin

- **POST** `/users/{user_id}/approve` - Approve user (admin only)
  - Permissions: Admin

- **DELETE** `/users/{user_id}` - Deactivate user (admin only)
  - Permissions: Admin

## WebSocket Endpoints (UC20)

### Real-time Communication

- **WebSocket** `/ws/server/{server_id}/logs` - Real-time server logs
  - Permissions: Owner or admin

- **WebSocket** `/ws/server/{server_id}/status` - Real-time status updates
  - Permissions: Owner or admin

- **WebSocket** `/ws/notifications` - Global notifications
  - Permissions: Authenticated

## Role-based Access Control

### User Roles

1. **User** - Basic role with limited permissions
   - Can view own servers and groups
   - Cannot create servers, groups, or backups

2. **Operator** - Advanced user with server management permissions
   - Can create and manage servers
   - Can create groups and backups
   - Cannot access admin functions

3. **Admin** - Full system access
   - All operator permissions
   - User management
   - Global statistics and monitoring
   - System configuration

### Access Control Rules

- **Server Access**: Users can only access servers they own, admins can access all servers
- **Group Access**: Users can only access groups they created, admins can access all groups
- **Backup Access**: Users can only access backups from their servers, admins can access all backups
- **Template Access**: Users can access public templates and their own, admins can access all templates
- **File Access**: Same as server access, with additional restrictions on system files

## Error Handling

All endpoints return standard HTTP status codes:

- **200** - Success
- **201** - Created
- **204** - No Content
- **400** - Bad Request (validation errors)
- **401** - Unauthorized (authentication required)
- **403** - Forbidden (insufficient permissions)
- **404** - Not Found
- **409** - Conflict (resource conflict)
- **422** - Unprocessable Entity (request validation failed)
- **500** - Internal Server Error

Error responses include detailed error messages and validation details where applicable.

## Rate Limiting and Security

- All endpoints implement proper authentication and authorization
- File operations include path traversal protection
- Upload operations validate file types and sizes
- Database operations use parameterized queries to prevent SQL injection
- Sensitive operations require explicit confirmation parameters