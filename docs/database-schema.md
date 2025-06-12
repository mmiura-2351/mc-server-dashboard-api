# Database Schema

## Overview

The Minecraft Server Dashboard API uses SQLite with SQLAlchemy ORM. The database consists of 10 tables managing users, servers, groups, backups, templates, and system operations.

## Entity Relationships

```
Users (1) ←→ (N) Servers
Users (1) ←→ (N) Groups  
Users (1) ←→ (N) Templates
Users (1) ←→ (N) RefreshTokens
Servers (1) ←→ (N) Backups
Servers (1) ←→ (N) ServerConfigurations
Servers (1) ←→ (N) FileEditHistory
Servers (N) ←→ (N) Groups (via ServerGroups)
All entities → AuditLogs
```

## Tables

### users
User accounts and authentication
- `id` (INTEGER, PK)
- `username` (VARCHAR 50, UNIQUE)
- `email` (VARCHAR 255, UNIQUE)
- `full_name` (VARCHAR 255)
- `hashed_password` (VARCHAR 255)
- `role` (ENUM: user/operator/admin)
- `is_active` (BOOLEAN)
- `is_approved` (BOOLEAN)
- `created_at` (DATETIME)
- `updated_at` (DATETIME)

### refresh_tokens
JWT refresh token management
- `id` (INTEGER, PK)
- `token` (VARCHAR 255, UNIQUE)
- `user_id` (INTEGER, FK → users)
- `expires_at` (DATETIME)
- `created_at` (DATETIME)

### servers
Minecraft server instances
- `id` (INTEGER, PK)
- `name` (VARCHAR 100)
- `description` (TEXT)
- `minecraft_version` (VARCHAR 20)
- `server_type` (ENUM: vanilla/paper/spigot/forge/fabric)
- `status` (ENUM: stopped/starting/running/stopping/error)
- `directory_path` (VARCHAR 500)
- `port` (INTEGER)
- `max_memory` (INTEGER)
- `min_memory` (INTEGER)
- `max_players` (INTEGER)
- `owner_id` (INTEGER, FK → users)
- `template_id` (INTEGER, FK → templates)
- `is_deleted` (BOOLEAN)
- `created_at` (DATETIME)
- `updated_at` (DATETIME)

### groups
Player groups for OP/whitelist management
- `id` (INTEGER, PK)
- `name` (VARCHAR 100)
- `description` (TEXT)
- `group_type` (ENUM: op/whitelist)
- `players` (JSON) - Array of player objects
- `owner_id` (INTEGER, FK → users)
- `is_template` (BOOLEAN)
- `created_at` (DATETIME)
- `updated_at` (DATETIME)

### server_groups
Junction table for server-group relationships
- `id` (INTEGER, PK)
- `server_id` (INTEGER, FK → servers)
- `group_id` (INTEGER, FK → groups)
- `priority` (INTEGER)
- `attached_at` (DATETIME)
- UNIQUE(server_id, group_id)

### backups
Server backup records
- `id` (INTEGER, PK)
- `server_id` (INTEGER, FK → servers)
- `name` (VARCHAR 100)
- `description` (TEXT)
- `file_path` (VARCHAR 500)
- `file_size` (BIGINT)
- `metadata` (JSON)
- `backup_type` (ENUM: manual/scheduled/pre_update)
- `status` (ENUM: creating/completed/failed)
- `created_at` (DATETIME)

### server_configurations
Key-value configuration storage
- `id` (INTEGER, PK)
- `server_id` (INTEGER, FK → servers)
- `configuration_key` (VARCHAR 100)
- `configuration_value` (TEXT)
- `updated_at` (DATETIME)
- UNIQUE(server_id, configuration_key)

### templates
Reusable server configurations
- `id` (INTEGER, PK)
- `name` (VARCHAR 100)
- `description` (TEXT)
- `minecraft_version` (VARCHAR 20)
- `server_type` (ENUM: vanilla/paper/spigot/forge/fabric)
- `configuration` (JSON)
- `created_by` (INTEGER, FK → users)
- `is_public` (BOOLEAN)
- `usage_count` (INTEGER)
- `created_at` (DATETIME)
- `updated_at` (DATETIME)

### file_edit_history
File version tracking
- `id` (INTEGER, PK)
- `server_id` (INTEGER, FK → servers)
- `file_path` (VARCHAR 500)
- `content` (TEXT)
- `content_hash` (VARCHAR 64)
- `version` (INTEGER)
- `edited_by` (INTEGER, FK → users)
- `comment` (TEXT)
- `file_size` (INTEGER)
- `created_at` (DATETIME)
- INDEX(server_id, file_path, version)

### audit_logs
System activity tracking
- `id` (INTEGER, PK)
- `user_id` (INTEGER, FK → users)
- `action` (VARCHAR 100)
- `resource_type` (VARCHAR 50)
- `resource_id` (INTEGER)
- `details` (JSON)
- `ip_address` (VARCHAR 45)
- `created_at` (DATETIME)

## Key Features

### JSON Field Structures

**groups.players**
```json
[{
  "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "username": "player_name",
  "added_at": "2024-01-01T00:00:00Z"
}]
```

**templates.configuration**
```json
{
  "server_properties": {
    "difficulty": "normal",
    "gamemode": "survival"
  },
  "jvm_args": ["-Xmx2G", "-Xms1G"]
}
```

**backups.metadata**
```json
{
  "minecraft_version": "1.20.1",
  "world_size": 1234567890,
  "player_data_included": true
}
```

### Indexes
- User lookups: username, email, role, is_approved
- Server queries: owner_id, status, is_deleted
- Group searches: owner_id, group_type, name
- Performance: foreign keys, timestamps, status fields

### Constraints
- Cascade deletes for dependent records
- Unique constraints on critical fields
- Foreign key integrity
- Soft delete support on servers

## Security Considerations
- Passwords hashed with bcrypt
- Row-level security through ownership checks
- Audit logging for all modifications
- Content deduplication via SHA256 hashing