# API Reference

## Base URL

All API endpoints use the `/api/v1/` prefix.

## Authentication

Most endpoints require JWT Bearer token authentication:
```
Authorization: Bearer <your-jwt-token>
```

## API Endpoints

### 🔐 Authentication (`/api/v1/auth`)

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/token` | Login with username/password | No |
| POST | `/refresh` | Refresh access token | No |
| POST | `/logout` | Logout and revoke token | No |

### 👤 Users (`/api/v1/users`)

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/register` | Register new user | No |
| GET | `/me` | Get current user info | Yes |
| PUT | `/me` | Update user profile | Yes |
| PUT | `/me/password` | Change password | Yes |
| DELETE | `/me` | Delete own account | Yes |
| GET | `/` | List all users | Admin |
| POST | `/approve/{user_id}` | Approve user | Admin |
| PUT | `/role/{user_id}` | Change user role | Admin |
| DELETE | `/{user_id}` | Delete user | Admin |

### 🖥️ Servers (`/api/v1/servers`)

#### CRUD Operations
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/` | Create server | Operator/Admin |
| GET | `/` | List servers | Yes |
| GET | `/{server_id}` | Get server details | Owner/Admin |
| PUT | `/{server_id}` | Update server | Owner/Admin |
| DELETE | `/{server_id}` | Delete server | Owner/Admin |

#### Server Control
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/{server_id}/start` | Start server | Owner/Admin |
| POST | `/{server_id}/stop` | Stop server | Owner/Admin |
| POST | `/{server_id}/restart` | Restart server | Owner/Admin |
| GET | `/{server_id}/status` | Get status | Owner/Admin |
| POST | `/{server_id}/command` | Send command | Owner/Admin |
| GET | `/{server_id}/logs` | Get logs | Owner/Admin |

#### Utilities
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/versions/supported` | List MC versions | Yes |
| POST | `/sync` | Sync servers | Admin |
| GET | `/cache/stats` | Cache statistics | Admin |
| POST | `/cache/cleanup` | Clean cache | Admin |
| GET | `/{server_id}/export` | Export server | Owner/Admin |
| POST | `/import` | Import server | Operator/Admin |

### 👥 Groups (`/api/v1/groups`)

#### Group Management
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/` | Create group | Operator/Admin |
| GET | `/` | List groups | Yes |
| GET | `/{group_id}` | Get group details | Owner/Admin |
| PUT | `/{group_id}` | Update group | Owner/Admin |
| DELETE | `/{group_id}` | Delete group | Owner/Admin |

#### Player Management
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/{group_id}/players` | Add player | Owner/Admin |
| DELETE | `/{group_id}/players/{player_uuid}` | Remove player | Owner/Admin |

#### Server Attachments
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/{group_id}/servers` | Attach to server | Owner/Admin |
| DELETE | `/{group_id}/servers/{server_id}` | Detach from server | Owner/Admin |
| GET | `/{group_id}/servers` | List attached servers | Owner/Admin |
| GET | `/servers/{server_id}` | List server groups | Owner/Admin |

### 💾 Backups (`/api/v1/backups`)

#### Backup Operations
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/servers/{server_id}/backups` | Create backup | Operator/Admin |
| GET | `/servers/{server_id}/backups` | List server backups | Owner/Admin |
| GET | `/backups` | List all backups | Admin |
| GET | `/backups/{backup_id}` | Get backup details | Owner/Admin |
| POST | `/backups/{backup_id}/restore` | Restore backup | Operator/Admin |
| POST | `/backups/{backup_id}/restore-with-template` | Restore with template | Operator/Admin |
| DELETE | `/backups/{backup_id}` | Delete backup | Operator/Admin |

#### Statistics
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/servers/{server_id}/backups/statistics` | Server backup stats | Owner/Admin |
| GET | `/backups/statistics` | Global backup stats | Admin |

#### Scheduling
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/backups/scheduled` | Create scheduled backups | Admin |
| GET | `/scheduler/status` | Scheduler status | Admin |
| POST | `/scheduler/servers/{server_id}/schedule` | Add schedule | Admin |
| PUT | `/scheduler/servers/{server_id}/schedule` | Update schedule | Admin |
| GET | `/scheduler/servers/{server_id}/schedule` | Get schedule | Owner/Admin |
| DELETE | `/scheduler/servers/{server_id}/schedule` | Remove schedule | Admin |

### 📄 Templates (`/api/v1/templates`)

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/` | Create custom template | Operator/Admin |
| POST | `/from-server/{server_id}` | Create from server | Operator/Admin |
| GET | `/` | List templates | Yes |
| GET | `/{template_id}` | Get template details | Yes |
| PUT | `/{template_id}` | Update template | Owner/Admin |
| DELETE | `/{template_id}` | Delete template | Owner/Admin |
| POST | `/{template_id}/clone` | Clone template | Operator/Admin |
| GET | `/statistics` | Template statistics | Yes |

### 📁 Files (`/api/v1/files`)

#### File Operations
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/servers/{server_id}/files` | List root files | Owner/Admin |
| GET | `/servers/{server_id}/files/{path}` | List files in path | Owner/Admin |
| GET | `/servers/{server_id}/files/{file_path}/read` | Read file | Owner/Admin |
| PUT | `/servers/{server_id}/files/{file_path}` | Write file | Operator/Admin |
| DELETE | `/servers/{server_id}/files/{file_path}` | Delete file | Operator/Admin |
| PATCH | `/servers/{server_id}/files/{file_path}/rename` | Rename file | Operator/Admin |

#### File Transfer
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/servers/{server_id}/files/upload` | Upload file | Operator/Admin |
| GET | `/servers/{server_id}/files/{file_path}/download` | Download file | Owner/Admin |

#### Directory & Search
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/servers/{server_id}/files/{directory_path}/directories` | Create directory | Operator/Admin |
| POST | `/servers/{server_id}/files/search` | Search files | Owner/Admin |

#### Version History
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/servers/{server_id}/files/{file_path}/history` | Get file history | Owner/Admin |
| GET | `/servers/{server_id}/files/{file_path}/history/{version}` | Get version content | Owner/Admin |
| POST | `/servers/{server_id}/files/{file_path}/history/{version}/restore` | Restore version | Operator/Admin |
| DELETE | `/servers/{server_id}/files/{file_path}/history/{version}` | Delete version | Admin |
| GET | `/servers/{server_id}/files/history/statistics` | History statistics | Owner/Admin |

### 🔌 WebSockets (`/api/v1/ws`)

| Protocol | Path | Description | Auth Required |
|----------|------|-------------|---------------|
| WS | `/servers/{server_id}/logs` | Real-time logs | Yes (token param) |
| WS | `/servers/{server_id}/status` | Real-time status | Yes (token param) |
| WS | `/notifications` | System notifications | Yes (token param) |

## 🛡️ Access Control

### User Roles
- **User**: Basic access to own resources
- **Operator**: Can create and manage servers, groups, templates
- **Admin**: Full system access including user management

### Resource Ownership
- Users can only access resources they own
- Admins can access all resources
- Some operations require specific roles regardless of ownership

## 📊 Response Formats

### Success Response
```json
{
  "id": 1,
  "name": "MyServer",
  "status": "running",
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
- `204` - No Content (successful deletion)
- `400` - Bad Request
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `422` - Validation Error
- `500` - Internal Server Error