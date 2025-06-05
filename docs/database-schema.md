# Database Schema

This document defines the database schema for the Minecraft Server Management Dashboard.

## Entity Relationship Overview

```
Users (1) ←→ (N) Servers
Users (1) ←→ (N) Groups  
Users (1) ←→ (N) Templates
Servers (1) ←→ (N) Backups
Servers (N) ←→ (N) Groups (via ServerGroups junction table)
Templates (1) ←→ (N) Servers
```

## Table Definitions

### Users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'operator', 'user') DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    is_approved BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Servers Table
```sql
CREATE TABLE servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    minecraft_version VARCHAR(20) NOT NULL,
    server_type ENUM('vanilla', 'forge', 'paper') NOT NULL,
    status ENUM('stopped', 'starting', 'running', 'stopping', 'error') DEFAULT 'stopped',
    directory_path VARCHAR(500) NOT NULL,
    port INTEGER DEFAULT 25565,
    max_memory INTEGER DEFAULT 1024, -- MB
    max_players INTEGER DEFAULT 20,
    owner_id INTEGER NOT NULL,
    template_id INTEGER NULL,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (template_id) REFERENCES templates(id)
);
```

### Groups Table
```sql
CREATE TABLE groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    type ENUM('op', 'whitelist') NOT NULL,
    players JSON NOT NULL, -- Array of player objects
    owner_id INTEGER NOT NULL,
    is_template BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id)
);
```

### ServerGroups Table (Junction)
```sql
CREATE TABLE server_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    priority INTEGER DEFAULT 0,
    attached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
    UNIQUE(server_id, group_id)
);
```

### Templates Table
```sql
CREATE TABLE templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    minecraft_version VARCHAR(20) NOT NULL,
    server_type ENUM('vanilla', 'forge', 'paper') NOT NULL,
    configuration JSON NOT NULL, -- server.properties and other settings
    default_groups JSON, -- Default group attachments
    created_by INTEGER NOT NULL,
    is_public BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
);
```

### Backups Table
```sql
CREATE TABLE backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL, -- bytes
    backup_type ENUM('manual', 'scheduled', 'pre_update') DEFAULT 'manual',
    status ENUM('creating', 'completed', 'failed') DEFAULT 'creating',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (server_id) REFERENCES servers(id)
);
```

### ServerConfigurations Table
```sql
CREATE TABLE server_configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    configuration_key VARCHAR(100) NOT NULL,
    configuration_value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
    UNIQUE(server_id, configuration_key)
);
```

### AuditLog Table
```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id INTEGER,
    details JSON,
    ip_address VARCHAR(45),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

## Indexes

### Performance Indexes
```sql
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_is_approved ON users(is_approved);

CREATE INDEX idx_servers_owner_id ON servers(owner_id);
CREATE INDEX idx_servers_status ON servers(status);
CREATE INDEX idx_servers_is_deleted ON servers(is_deleted);
CREATE INDEX idx_servers_template_id ON servers(template_id);

CREATE INDEX idx_groups_owner_id ON groups(owner_id);
CREATE INDEX idx_groups_type ON groups(type);
CREATE INDEX idx_groups_name ON groups(name);

CREATE INDEX idx_server_groups_server_id ON server_groups(server_id);
CREATE INDEX idx_server_groups_group_id ON server_groups(group_id);

CREATE INDEX idx_backups_server_id ON backups(server_id);
CREATE INDEX idx_backups_created_at ON backups(created_at);
CREATE INDEX idx_backups_status ON backups(status);

CREATE INDEX idx_templates_created_by ON templates(created_by);
CREATE INDEX idx_templates_is_public ON templates(is_public);

CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
```

## Data Types and Constraints

### JSON Field Structures

#### Groups.players
```json
[
    {
        "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "username": "player_name",
        "added_at": "2024-01-01T00:00:00Z"
    }
]
```

#### Templates.configuration
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

#### Templates.default_groups
```json
{
    "op_groups": [1, 2],
    "whitelist_groups": [3, 4]
}
```

#### AuditLog.details
```json
{
    "old_value": "previous_state",
    "new_value": "new_state",
    "affected_fields": ["field1", "field2"],
    "metadata": {}
}
```

## Migration Strategy

### Initial Setup
1. Create tables in dependency order
2. Insert default admin user
3. Create default templates
4. Set up indexes

### Version Updates
- Use SQLAlchemy migrations for schema changes
- Backup database before major migrations
- Test migrations on development data

## Security Considerations

### Data Protection
- Hash passwords using bcrypt
- Encrypt sensitive configuration values
- Sanitize JSON inputs
- Validate foreign key relationships

### Access Control
- Row-level security for user-owned resources
- Admin override capabilities
- Audit logging for all modifications
- Soft delete for data retention

## Performance Considerations

### Query Optimization
- Use appropriate indexes for common queries
- Implement pagination for large result sets
- Cache frequently accessed configuration data
- Optimize JSON field queries

### Scalability
- Consider partitioning for audit logs
- Implement backup cleanup policies
- Monitor index usage and performance
- Plan for horizontal scaling if needed