# Database Schema

Complete database schema documentation for the Minecraft Server Dashboard API.

## Overview

The system uses SQLAlchemy ORM with SQLite as the default database, designed for scalability and data integrity.

### Key Characteristics
- **Database Type**: SQLite (default) with support for PostgreSQL, MySQL via SQLAlchemy
- **Primary Keys**: Auto-incrementing integer primary keys on all tables
- **Timestamps**: Automatic `created_at` and `updated_at` fields with timezone support
- **Foreign Keys**: Enforced relationships with appropriate cascade options
- **Data Integrity**: Comprehensive constraints, unique indexes, and validation
- **Soft Deletes**: Implemented where data retention is important

## Entity Relationship Overview

```
Users (1:N) ────┐
                ├─ Servers (1:N) ── Backups
                ├─ Groups (N:M) ──── Servers (via server_groups)
                ├─ Templates
                ├─ RefreshTokens
                └─ AuditLogs (audit trail)

Servers (1:N) ── ServerConfigurations
           ├── FileEditHistory  
           └── BackupSchedules (1:1)

BackupSchedules (1:N) ── BackupScheduleLogs
```

## Table Schemas

### 1. Users (`users`)

**Purpose**: Core user management and authentication

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Unique user identifier |
| username | String(50) | UNIQUE, NOT NULL, INDEXED | - | Login username |
| email | String(255) | UNIQUE, NOT NULL, INDEXED | - | User email address |
| full_name | String(255) | NULLABLE | - | User's full name |
| hashed_password | String(255) | NOT NULL | - | Bcrypt hashed password |
| role | Enum(Role) | NOT NULL | Role.user | User role (admin/operator/user) |
| is_active | Boolean | NOT NULL | True | Account activation status |
| is_approved | Boolean | NOT NULL | False | Admin approval status |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Account creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**Business Rules**:
- First registered user automatically becomes admin with approval
- Users require admin approval before full access
- Email and username must be unique across the system

### 2. Refresh Tokens (`refresh_tokens`)

**Purpose**: JWT refresh token management for secure authentication

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Token identifier |
| token | Text | UNIQUE, NOT NULL, INDEXED | - | Refresh token string |
| user_id | Integer | NOT NULL, FOREIGN KEY (users.id) CASCADE DELETE | - | Token owner |
| expires_at | DateTime(timezone=True) | NOT NULL | - | Token expiration |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Token creation time |
| is_revoked | Boolean | NOT NULL | False | Token revocation status |

**Business Rules**:
- Tokens automatically cleaned up when user is deleted
- Expired tokens are considered invalid
- Revoked tokens cannot be used for authentication

### 3. Servers (`servers`)

**Purpose**: Minecraft server instance management

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Server identifier |
| name | String(100) | NOT NULL | - | Server display name |
| description | Text | NULLABLE | - | Server description |
| minecraft_version | String(20) | NOT NULL | - | Minecraft version (e.g., "1.20.1") |
| server_type | Enum(ServerType) | NOT NULL | - | Server type (vanilla/forge/paper) |
| status | Enum(ServerStatus) | NOT NULL | ServerStatus.stopped | Current server status |
| directory_path | String(500) | NOT NULL | - | Filesystem path |
| port | Integer | NOT NULL | 25565 | Server port number |
| max_memory | Integer | NOT NULL | 1024 | Max memory in MB |
| max_players | Integer | NOT NULL | 20 | Max player count |
| owner_id | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Server owner |
| template_id | Integer | NULLABLE, FOREIGN KEY (templates.id) | - | Source template |
| is_deleted | Boolean | NOT NULL | False | Soft delete flag |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**Business Rules**:
- Soft delete preserves data while hiding from normal operations
- Each server has exactly one owner
- Directory path must be unique per server

### 4. Server Configurations (`server_configurations`)

**Purpose**: Flexible key-value configuration storage for servers

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Configuration identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) CASCADE DELETE | - | Associated server |
| configuration_key | String(100) | NOT NULL | - | Configuration key |
| configuration_value | Text | NULLABLE | - | Configuration value |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**Constraints**:
- UNIQUE (server_id, configuration_key) - One value per key per server

### 5. Groups (`groups`)

**Purpose**: Player group management (OP/whitelist groups)

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Group identifier |
| name | String(100) | NOT NULL | - | Group display name |
| description | Text | NULLABLE | - | Group description |
| group_type | Enum(GroupType) | NOT NULL | - | Group type (op/whitelist) |
| players | JSON | NOT NULL | [] | Array of player objects |
| owner_id | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Group owner |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**JSON Structure (players)**:
```json
[
  {
    "uuid": "player-uuid-here",
    "username": "PlayerName"
  }
]
```

### 6. Server Groups (`server_groups`)

**Purpose**: Many-to-many relationship between servers and groups

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Relationship identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) CASCADE DELETE | - | Associated server |
| group_id | Integer | NOT NULL, FOREIGN KEY (groups.id) CASCADE DELETE | - | Associated group |
| priority | Integer | NOT NULL | 0 | Group priority order |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Attachment time |

**Constraints**:
- UNIQUE (server_id, group_id) - Each group can be attached to a server only once

### 7. Backups (`backups`)

**Purpose**: Server backup management and metadata

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Backup identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) CASCADE DELETE | - | Source server |
| name | String(100) | NOT NULL | - | Backup display name |
| description | Text | NULLABLE | - | Backup description |
| file_path | String(500) | NOT NULL | - | Backup file path |
| file_size | BigInteger | NOT NULL | - | Backup size in bytes |
| backup_type | Enum(BackupType) | NOT NULL | BackupType.manual | Backup type |
| status | Enum(BackupStatus) | NOT NULL | BackupStatus.creating | Backup status |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Backup creation time |

### 8. Backup Schedules (`backup_schedules`)

**Purpose**: Automated backup scheduling configuration

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Schedule identifier |
| server_id | Integer | UNIQUE, NOT NULL, FOREIGN KEY (servers.id) CASCADE DELETE | - | Target server |
| interval_hours | Integer | NOT NULL, CHECK (1 <= interval_hours <= 168) | - | Backup interval |
| max_backups | Integer | NOT NULL, CHECK (1 <= max_backups <= 30) | - | Max backups to keep |
| enabled | Boolean | NOT NULL, INDEXED | True | Schedule status |
| last_backup_at | DateTime(timezone=True) | NULLABLE | - | Last backup time |
| next_backup_at | DateTime(timezone=True) | NOT NULL, INDEXED | - | Next backup time |
| backup_name_template | String(200) | NOT NULL | - | Backup name template |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**Business Rules**:
- Each server can have at most one backup schedule
- Interval must be between 1 hour and 1 week (168 hours)
- Maximum 30 backups retained per server

### 9. Backup Schedule Logs (`backup_schedule_logs`)

**Purpose**: Audit trail for backup schedule operations

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Log identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) CASCADE DELETE | - | Target server |
| user_id | Integer | NULLABLE, FOREIGN KEY (users.id) SET NULL | - | Action executor |
| action | Enum(ScheduleAction) | NOT NULL | - | Action type |
| old_config | JSON | NULLABLE | - | Previous configuration |
| new_config | JSON | NULLABLE | - | New configuration |
| result | String(500) | NULLABLE | - | Action result |
| timestamp | DateTime(timezone=True) | NOT NULL | func.now() | Action timestamp |

### 10. Templates (`templates`)

**Purpose**: Reusable server configuration templates

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Template identifier |
| name | String(100) | NOT NULL | - | Template name |
| description | Text | NULLABLE | - | Template description |
| minecraft_version | String(20) | NOT NULL | - | Target Minecraft version |
| server_type | Enum(ServerType) | NOT NULL | - | Server type |
| configuration | JSON | NOT NULL | {} | Server configuration |
| default_groups | JSON | NULLABLE | - | Default group attachments |
| is_public | Boolean | NOT NULL | False | Public template flag |
| created_by_id | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Template creator |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**JSON Structure (configuration)**:
```json
{
  "max_memory": 2048,
  "max_players": 20,
  "server_properties": {
    "difficulty": "normal",
    "gamemode": "survival"
  }
}
```

### 11. File Edit History (`file_edit_history`)

**Purpose**: Version control for server file edits

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | History identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) CASCADE DELETE | - | Target server |
| file_path | String(500) | NOT NULL | - | Relative file path |
| version | String(50) | NOT NULL | - | Version identifier |
| content_backup_path | String(500) | NOT NULL | - | Backup file path |
| content_hash | String(64) | NULLABLE | - | SHA-256 content hash |
| file_size | BigInteger | NOT NULL | - | File size in bytes |
| created_by_id | Integer | NULLABLE, FOREIGN KEY (users.id) SET NULL | - | Editor user |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Edit timestamp |

**Business Rules**:
- Content hash enables deduplication of identical file versions
- Each edit creates a new version entry
- Backup files are stored separately from the main server files

### 12. Audit Logs (`audit_logs`)

**Purpose**: System-wide audit logging for security and compliance

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Log identifier |
| user_id | Integer | NULLABLE, FOREIGN KEY (users.id) SET NULL | - | Action performer |
| action | String(100) | NOT NULL | - | Action type |
| resource_type | String(50) | NULLABLE | - | Resource type |
| resource_id | Integer | NULLABLE | - | Resource identifier |
| details | JSON | NULLABLE | - | Additional details |
| ip_address | String(45) | NULLABLE | - | Client IP address |
| user_agent | String(500) | NULLABLE | - | Client user agent |
| timestamp | DateTime(timezone=True) | NOT NULL | func.now() | Action timestamp |

**Business Rules**:
- Captures all significant system actions
- User ID can be null for system-initiated actions
- IP address supports both IPv4 and IPv6

## Enumerations

### Role
- `admin` - Full system access
- `operator` - Server management capabilities  
- `user` - Basic access to owned resources

### ServerStatus
- `stopped` - Server is not running
- `starting` - Server is in startup process
- `running` - Server is active and accepting connections
- `stopping` - Server is in shutdown process
- `error` - Server encountered an error

### ServerType
- `vanilla` - Official Minecraft server
- `forge` - Modded Minecraft with Forge
- `paper` - High-performance Paper server

### GroupType
- `op` - Operator permissions group
- `whitelist` - Whitelist access group

### BackupType
- `manual` - User-initiated backup
- `scheduled` - Automatically created backup
- `pre_update` - Backup before server updates

### BackupStatus
- `creating` - Backup in progress
- `completed` - Backup successfully created
- `failed` - Backup creation failed

### ScheduleAction
- `created` - Schedule was created
- `updated` - Schedule configuration changed
- `deleted` - Schedule was removed
- `executed` - Scheduled backup was performed
- `skipped` - Scheduled backup was skipped

## Indexes and Performance

### Automatic Indexes
- Primary keys on all tables
- Foreign key indexes for relationship performance
- Unique constraint indexes (username, email, tokens)

### Special Indexes
- `backup_schedules.enabled` - For finding active schedules
- `backup_schedules.next_backup_at` - For schedule execution
- `refresh_tokens.token` - For authentication lookups

### Composite Indexes
- `(server_id, configuration_key)` on server_configurations
- `(server_id, group_id)` on server_groups

## Data Integrity Features

### Cascade Rules
- **DELETE CASCADE**: User refresh tokens, server backups, configurations, groups, file history
- **SET NULL**: File edit history editor references when user is deleted
- **RESTRICT**: Default behavior for other relationships

### Check Constraints
- Backup schedule intervals: 1-168 hours
- Backup retention limits: 1-30 backups maximum

### Soft Deletes
- Servers use `is_deleted` flag for data retention
- Allows recovery while hiding from normal operations

### Automatic Timestamps
- `created_at` set on record creation
- `updated_at` updated automatically on modification
- Timezone-aware datetime handling

## Data Migration Strategy

### Schema Evolution
- SQLAlchemy handles automatic table creation
- Foreign key relationships ensure referential integrity
- Soft deletes preserve historical data during cleanup
- JSON fields provide schema flexibility for configuration

### Backup and Recovery
- All critical data relationships are properly constrained
- File edit history provides configuration rollback capabilities
- Audit logs ensure complete activity tracking
- Backup system provides data recovery mechanisms

This database schema supports the complete feature set of the Minecraft Server Management Dashboard with strong data consistency, comprehensive audit trails, and scalable architecture for multi-server environments.
