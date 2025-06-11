# Comprehensive Database Schema Documentation

This document provides a comprehensive analysis of all database models in the Minecraft Server Management Dashboard API, including all tables, columns, relationships, constraints, and indexes.

## Table of Contents
1. [Database Overview](#database-overview)
2. [Table Schemas](#table-schemas)
3. [Relationships](#relationships)
4. [Enumerations](#enumerations)
5. [Indexes](#indexes)
6. [JSON Field Structures](#json-field-structures)
7. [Constraints](#constraints)

## Database Overview

The system uses SQLAlchemy ORM with the following key characteristics:
- **Database Type**: SQLite (default) with support for other databases via SQLAlchemy
- **Primary Keys**: All tables use auto-incrementing integer primary keys
- **Timestamps**: Most tables include `created_at` and `updated_at` fields with automatic timezone support
- **Foreign Keys**: Enforced relationships with appropriate cascade options
- **Soft Deletes**: Implemented via `is_deleted` flag on servers table

## Table Schemas

### 1. Users Table (`users`)

**Purpose**: Stores user accounts with authentication and authorization details

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Unique user identifier |
| username | String(50) | UNIQUE, NOT NULL, INDEXED | - | Unique username for login |
| email | String(255) | UNIQUE, NOT NULL, INDEXED | - | User email address |
| hashed_password | String(255) | NOT NULL | - | Bcrypt hashed password |
| role | Enum(Role) | NOT NULL | Role.user | User role (admin/operator/user) |
| is_active | Boolean | NOT NULL | True | Whether user can authenticate |
| is_approved | Boolean | NOT NULL | False | Whether admin has approved user |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Account creation timestamp |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update timestamp |

### 2. Refresh Tokens Table (`refresh_tokens`)

**Purpose**: Manages JWT refresh tokens for secure authentication

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Token identifier |
| token | Text | UNIQUE, NOT NULL, INDEXED | - | The refresh token string |
| user_id | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Associated user |
| expires_at | DateTime(timezone=True) | NOT NULL | - | Token expiration time |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Token creation time |
| is_revoked | Boolean | NOT NULL | False | Whether token is revoked |

### 3. Servers Table (`servers`)

**Purpose**: Represents Minecraft server instances with configuration

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Server identifier |
| name | String(100) | NOT NULL | - | Server display name |
| description | Text | NULLABLE | - | Server description |
| minecraft_version | String(20) | NOT NULL | - | Minecraft version (e.g., "1.20.1") |
| server_type | Enum(ServerType) | NOT NULL | - | Server type (vanilla/forge/paper) |
| status | Enum(ServerStatus) | NOT NULL | ServerStatus.stopped | Current server status |
| directory_path | String(500) | NOT NULL | - | Filesystem path to server |
| port | Integer | NOT NULL | 25565 | Server port number |
| max_memory | Integer | NOT NULL | 1024 | Max memory in MB |
| max_players | Integer | NOT NULL | 20 | Max player count |
| owner_id | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Server owner |
| template_id | Integer | NULLABLE, FOREIGN KEY (templates.id) | - | Source template if any |
| is_deleted | Boolean | NOT NULL | False | Soft delete flag |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation timestamp |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update timestamp |

### 4. Backups Table (`backups`)

**Purpose**: Tracks server backup files and metadata

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Backup identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) | - | Associated server |
| name | String(100) | NOT NULL | - | Backup display name |
| description | Text | NULLABLE | - | Backup description |
| file_path | String(500) | NOT NULL | - | Path to backup file |
| file_size | BigInteger | NOT NULL | - | Backup size in bytes |
| backup_type | Enum(BackupType) | NOT NULL | BackupType.manual | Type of backup |
| status | Enum(BackupStatus) | NOT NULL | BackupStatus.creating | Backup status |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Backup creation time |

### 5. Server Configurations Table (`server_configurations`)

**Purpose**: Key-value store for server-specific configurations

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Configuration identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) | - | Associated server |
| configuration_key | String(100) | NOT NULL | - | Configuration key |
| configuration_value | Text | NOT NULL | - | Configuration value |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

**Unique Constraint**: (server_id, configuration_key)

### 6. Templates Table (`templates`)

**Purpose**: Reusable server configurations and settings

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Template identifier |
| name | String(100) | NOT NULL | - | Template name |
| description | Text | NULLABLE | - | Template description |
| minecraft_version | String(20) | NOT NULL | - | Target Minecraft version |
| server_type | Enum(ServerType) | NOT NULL | - | Server type |
| configuration | JSON | NOT NULL | - | Server properties and settings |
| default_groups | JSON | NULLABLE | - | Default group attachments |
| created_by | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Template creator |
| is_public | Boolean | NOT NULL | False | Whether template is public |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

### 7. Groups Table (`groups`)

**Purpose**: Manages player groups for OPs and whitelists

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Group identifier |
| name | String(100) | NOT NULL | - | Group name |
| description | Text | NULLABLE | - | Group description |
| type | Enum(GroupType) | NOT NULL | - | Group type (op/whitelist) |
| players | JSON | NOT NULL | - | Array of player objects |
| owner_id | Integer | NOT NULL, FOREIGN KEY (users.id) | - | Group owner |
| is_template | Boolean | NOT NULL | False | Whether group is a template |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Creation time |
| updated_at | DateTime(timezone=True) | NOT NULL | func.now() | Last update time |

### 8. Server Groups Table (`server_groups`)

**Purpose**: Junction table linking servers to groups

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Relationship identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) | - | Associated server |
| group_id | Integer | NOT NULL, FOREIGN KEY (groups.id) | - | Associated group |
| priority | Integer | NOT NULL | 0 | Group priority order |
| attached_at | DateTime(timezone=True) | NOT NULL | func.now() | Attachment time |

**Unique Constraint**: (server_id, group_id)

### 9. Audit Logs Table (`audit_logs`)

**Purpose**: Tracks all system actions for security and compliance

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | Log entry identifier |
| user_id | Integer | NULLABLE, FOREIGN KEY (users.id) | - | User who performed action |
| action | String(100) | NOT NULL | - | Action performed |
| resource_type | String(50) | NOT NULL | - | Type of resource affected |
| resource_id | Integer | NULLABLE | - | ID of affected resource |
| details | JSON | NULLABLE | - | Additional action details |
| ip_address | String(45) | NULLABLE | - | IP address (IPv6 support) |
| created_at | DateTime(timezone=True) | NOT NULL | func.now() | Action timestamp |

### 10. File Edit History Table (`file_edit_history`)

**Purpose**: Tracks file modification history with versioning

| Column | Type | Constraints | Default | Description |
|--------|------|-------------|---------|-------------|
| id | Integer | PRIMARY KEY, AUTO_INCREMENT | - | History entry identifier |
| server_id | Integer | NOT NULL, FOREIGN KEY (servers.id) ON DELETE CASCADE | - | Associated server |
| file_path | String(500) | NOT NULL | - | Relative path from server root |
| version_number | Integer | NOT NULL | - | File version number |
| backup_file_path | String(500) | NOT NULL | - | Absolute path to backup |
| file_size | BigInteger | NOT NULL | - | File size in bytes |
| content_hash | String(64) | NULLABLE | - | SHA256 hash for deduplication |
| editor_user_id | Integer | NULLABLE, FOREIGN KEY (users.id) ON DELETE SET NULL | - | User who edited file |
| created_at | DateTime | NOT NULL | datetime.utcnow | Edit timestamp |
| description | Text | NULLABLE | - | Optional edit description |

## Relationships

### One-to-Many Relationships

1. **User → Servers**: One user can own multiple servers
   - `User.servers` ← → `Server.owner`
   - Cascade: None (servers remain if user deleted)

2. **User → Groups**: One user can own multiple groups
   - `User.groups` ← → `Group.owner`
   - Cascade: None

3. **User → Templates**: One user can create multiple templates
   - `User.templates` ← → `Template.creator`
   - Cascade: None

4. **User → RefreshTokens**: One user can have multiple refresh tokens
   - `User.refresh_tokens` ← → `RefreshToken.user`
   - Cascade: all, delete-orphan

5. **Server → Backups**: One server can have multiple backups
   - `Server.backups` ← → `Backup.server`
   - Cascade: all, delete-orphan

6. **Server → ServerConfigurations**: One server can have multiple configurations
   - `Server.configurations` ← → `ServerConfiguration.server`
   - Cascade: all, delete-orphan

7. **Server → FileEditHistory**: One server can have multiple file edits
   - `Server.file_edit_history` ← → `FileEditHistory.server`
   - Cascade: all, delete-orphan

8. **Template → Servers**: One template can be used by multiple servers
   - `Template.servers` ← → `Server.template`
   - Cascade: None

### Many-to-Many Relationships

1. **Servers ← → Groups**: Via ServerGroups junction table
   - `Server.server_groups` ← → `ServerGroup.server`
   - `Group.server_groups` ← → `ServerGroup.group`
   - Cascade: all, delete-orphan on both sides

## Enumerations

### Role (User roles)
- `admin`: Full system access
- `operator`: Server management access
- `user`: Basic user access

### ServerStatus
- `stopped`: Server is not running
- `starting`: Server is starting up
- `running`: Server is operational
- `stopping`: Server is shutting down
- `error`: Server encountered an error

### ServerType
- `vanilla`: Official Minecraft server
- `forge`: Forge modded server
- `paper`: Paper server (performance-optimized)

### BackupType
- `manual`: User-initiated backup
- `scheduled`: Automated scheduled backup
- `pre_update`: Backup before server update

### BackupStatus
- `creating`: Backup in progress
- `completed`: Backup successful
- `failed`: Backup failed

### GroupType
- `op`: Operator group
- `whitelist`: Whitelist group

## Indexes

### Explicitly Defined Indexes
1. `users.username` - UNIQUE INDEX
2. `users.email` - UNIQUE INDEX
3. `users.id` - PRIMARY KEY INDEX
4. `refresh_tokens.token` - UNIQUE INDEX
5. `refresh_tokens.id` - PRIMARY KEY INDEX
6. `servers.id` - PRIMARY KEY INDEX
7. All other primary keys have implicit indexes

### Composite Unique Constraints (Creating Indexes)
1. `server_configurations(server_id, configuration_key)`
2. `server_groups(server_id, group_id)`

## JSON Field Structures

### groups.players
```json
[
  {
    "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "username": "player_name",
    "added_at": "2024-01-01T00:00:00Z"
  }
]
```

### templates.configuration
```json
{
  "server_properties": {
    "difficulty": "normal",
    "gamemode": "survival",
    "max_players": 20,
    "pvp": true,
    "spawn_protection": 16
  },
  "jvm_args": ["-Xmx2G", "-Xms1G"],
  "plugins": ["plugin1", "plugin2"]
}
```

### templates.default_groups
```json
{
  "op_groups": [1, 2],
  "whitelist_groups": [3, 4]
}
```

### audit_logs.details
```json
{
  "old_value": "previous_state",
  "new_value": "new_state",
  "affected_fields": ["field1", "field2"],
  "metadata": {}
}
```

## Constraints

### Foreign Key Constraints
1. `servers.owner_id` → `users.id`
2. `servers.template_id` → `templates.id`
3. `backups.server_id` → `servers.id`
4. `server_configurations.server_id` → `servers.id` (ON DELETE CASCADE)
5. `templates.created_by` → `users.id`
6. `groups.owner_id` → `users.id`
7. `server_groups.server_id` → `servers.id` (ON DELETE CASCADE)
8. `server_groups.group_id` → `groups.id` (ON DELETE CASCADE)
9. `audit_logs.user_id` → `users.id`
10. `refresh_tokens.user_id` → `users.id`
11. `file_edit_history.server_id` → `servers.id` (ON DELETE CASCADE)
12. `file_edit_history.editor_user_id` → `users.id` (ON DELETE SET NULL)

### Check Constraints (Implicit via SQLAlchemy)
- All boolean fields constrained to TRUE/FALSE
- All enum fields constrained to their defined values
- Port numbers constrained to valid integer range
- Memory values constrained to positive integers

### Default Values
- Most timestamp fields default to current time
- Boolean flags default to False (except `is_active` = True)
- Numeric fields have sensible defaults (port: 25565, memory: 1024MB, etc.)
- Enums default to appropriate values (status: stopped, role: user, etc.)

## Additional Notes

### Cascade Behaviors
- **all, delete-orphan**: Child records are deleted when parent is deleted
- **ON DELETE CASCADE**: Database-level cascade for junction tables
- **ON DELETE SET NULL**: Preserves records but nullifies reference

### Timezone Handling
- All DateTime fields use timezone-aware timestamps
- Server default uses `func.now()` for database-native timestamps
- Python code uses `datetime.utcnow` for consistency

### Model Methods
Several models include helper methods:
- `Group`: get_players(), set_players(), add_player(), remove_player(), has_player()
- `Template`: get_configuration(), set_configuration(), get_default_groups(), set_default_groups()
- `AuditLog`: create_log() class method for easy log creation
- `RefreshToken`: is_expired(), is_valid() for token validation

### Security Considerations
- Password fields store bcrypt hashes, never plain text
- Refresh tokens are unique and indexed for fast lookup
- Audit logs track user actions with IP addresses
- File paths are validated to prevent directory traversal
- Soft deletes preserve data integrity