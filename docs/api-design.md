# API Design Guidelines

This document provides guidelines for designing consistent APIs in the Minecraft Server Management Dashboard.

## API Structure

### Base URL Pattern
```
/api/v1/{resource}
```

### Authentication
All endpoints except public authentication routes require JWT Bearer token:
```
Authorization: Bearer <jwt_token>
```

## Resource Naming Conventions

### Endpoints by Feature Area

#### Server Management
```
GET    /api/v1/servers                    # List servers
POST   /api/v1/servers                    # Create server
GET    /api/v1/servers/{id}               # Get server details
PUT    /api/v1/servers/{id}               # Update server
DELETE /api/v1/servers/{id}               # Delete server

POST   /api/v1/servers/{id}/start         # Start server
POST   /api/v1/servers/{id}/stop          # Stop server
GET    /api/v1/servers/{id}/status        # Get server status
GET    /api/v1/servers/{id}/logs          # Get server logs (WebSocket)
```

#### Player Management
```
GET    /api/v1/groups/op                  # List OP groups
POST   /api/v1/groups/op                  # Create OP group
GET    /api/v1/groups/op/{id}             # Get OP group
PUT    /api/v1/groups/op/{id}             # Update OP group
DELETE /api/v1/groups/op/{id}             # Delete OP group

GET    /api/v1/groups/whitelist           # List whitelist groups
POST   /api/v1/groups/whitelist           # Create whitelist group
GET    /api/v1/groups/whitelist/{id}      # Get whitelist group
PUT    /api/v1/groups/whitelist/{id}      # Update whitelist group
DELETE /api/v1/groups/whitelist/{id}      # Delete whitelist group

POST   /api/v1/servers/{id}/groups/op/{group_id}        # Attach OP group
DELETE /api/v1/servers/{id}/groups/op/{group_id}        # Detach OP group
POST   /api/v1/servers/{id}/groups/whitelist/{group_id} # Attach whitelist group
DELETE /api/v1/servers/{id}/groups/whitelist/{group_id} # Detach whitelist group
```

#### File Management
```
GET    /api/v1/servers/{id}/files         # List files
GET    /api/v1/servers/{id}/files/{path}  # Get file content
PUT    /api/v1/servers/{id}/files/{path}  # Update file
POST   /api/v1/servers/{id}/files         # Create file
DELETE /api/v1/servers/{id}/files/{path}  # Delete file
```

#### Backup Management
```
GET    /api/v1/servers/{id}/backups       # List backups
POST   /api/v1/servers/{id}/backups       # Create backup
GET    /api/v1/servers/{id}/backups/{backup_id}     # Get backup info
DELETE /api/v1/servers/{id}/backups/{backup_id}     # Delete backup
POST   /api/v1/servers/{id}/backups/{backup_id}/restore # Restore backup
```

#### Template Management
```
GET    /api/v1/templates                  # List templates
POST   /api/v1/templates                  # Create template
GET    /api/v1/templates/{id}             # Get template
PUT    /api/v1/templates/{id}             # Update template
DELETE /api/v1/templates/{id}             # Delete template
POST   /api/v1/templates/{id}/instantiate # Create server from template
```

#### User Management
```
GET    /api/v1/users                      # List users (admin only)
GET    /api/v1/users/{id}                 # Get user details
PUT    /api/v1/users/{id}                 # Update user
DELETE /api/v1/users/{id}                 # Delete user
POST   /api/v1/users/{id}/approve         # Approve user (admin only)
PUT    /api/v1/users/{id}/role            # Change user role (admin only)
```

#### Authentication
```
POST   /api/v1/auth/register              # User registration
POST   /api/v1/auth/login                 # User login
POST   /api/v1/auth/logout                # User logout
POST   /api/v1/auth/refresh               # Refresh token
GET    /api/v1/auth/me                    # Get current user info
```

## Response Format Standards

### Success Response
```json
{
  "success": true,
  "data": {
    // Response data
  },
  "message": "Optional success message"
}
```

### Error Response
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable error message",
    "details": {
      // Additional error details
    }
  }
}
```

### Pagination
```json
{
  "success": true,
  "data": {
    "items": [...],
    "pagination": {
      "page": 1,
      "limit": 20,
      "total": 100,
      "totalPages": 5
    }
  }
}
```

## Status Codes

- `200 OK` - Successful GET, PUT
- `201 Created` - Successful POST
- `204 No Content` - Successful DELETE
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource conflict
- `422 Unprocessable Entity` - Validation errors
- `500 Internal Server Error` - Server error

## Validation and Error Handling

### Input Validation
- Use Pydantic models for request/response validation
- Provide detailed validation error messages
- Sanitize file paths and user inputs

### Role-Based Access Control
- Implement permission decorators
- Check user roles and ownership
- Provide clear permission error messages

### File Operation Security
- Restrict file access to server directories
- Validate file paths to prevent directory traversal
- Implement file type restrictions where appropriate

## WebSocket Endpoints

### Real-time Server Logs
```
WS /api/v1/servers/{id}/logs/stream
```

### Server Status Updates
```
WS /api/v1/servers/{id}/status/stream
```

### System Notifications
```
WS /api/v1/notifications
```

## Database Schema Considerations

### Foreign Key Relationships
- Servers → Users (owner_id)
- ServerGroups → Servers (server_id)
- ServerGroups → Groups (group_id)
- Backups → Servers (server_id)
- Templates → Users (created_by)

### Indexes
- User username/email for authentication
- Server status for monitoring
- Group names for searching
- Backup timestamps for sorting

### Soft Deletes
- Implement soft delete for servers (retention requirement)
- Hard delete for sensitive user data when requested
- Cleanup policies for backups and logs