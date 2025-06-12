# System Requirements

This document outlines the functional requirements for the Minecraft Server Management Dashboard.

## Overview

The system provides a comprehensive web-based dashboard for managing multiple Minecraft servers with user authentication, role-based access control, and extensive server management capabilities.

**Key Principle**: Administrators inherit all user capabilities in addition to their admin-specific functions.

## Functional Requirements

### 1. Server Management (UC1-7)

#### UC1: Multi-Server Management
- **Requirement**: System must support simultaneous management of multiple Minecraft servers
- **Implementation**: Unique server ID management, database storage of server metadata, frontend server list with status monitoring

#### UC2: Server Creation
- **Requirement**: Users can create new Minecraft servers
- **Implementation**: Server creation forms, automated directory setup, server JAR downloads, database registration

#### UC3: Version Selection
- **Requirement**: Support Minecraft versions 1.8 through 1.21.5
- **Implementation**: Integration with Minecraft official API, version dropdown/selection interface, automated JAR file downloads

#### UC4: Server Type Selection
- **Requirement**: Support server types (Vanilla, Forge, Paper)
- **Implementation**: Server type API management, selection interface, type-specific server file downloads

#### UC5: Server Configuration
- **Requirement**: Users can modify server settings
- **Implementation**: server.properties file read/write, form-based configuration interface, file update mechanisms

#### UC6: Memory Usage Configuration
- **Requirement**: Users can specify server memory allocation (maximum)
- **Implementation**: Dynamic JVM -Xmx parameter configuration, slider/numeric input interface, system memory constraint validation

#### UC7: Server Templates
- **Requirement**: Users can create servers from templates
- **Implementation**: Template database storage, configuration/file copying from templates, template browsing interface

### 2. Server Operations (UC8-11)

#### UC8: Server Deletion
- **Requirement**: Users can delete Minecraft servers
- **Implementation**: Confirmation dialogs, backend file retention (soft delete), database cleanup

#### UC9: Server Startup
- **Requirement**: Users can start Minecraft servers
- **Implementation**: Child process management, PID tracking, real-time log streaming

#### UC10: Server Shutdown
- **Requirement**: Users can stop Minecraft servers
- **Implementation**: Graceful shutdown via "stop" command, force termination option (low priority)

#### UC11: Configuration Updates
- **Requirement**: Users can update server configurations
- **Implementation**: Configuration change detection, validation, restart notification system

### 3. Player Management (UC12-19)

#### UC12: OP Permission Groups
- **Requirement**: Create and manage OP permission groups
- **Implementation**: Database group management (name, description, player list), CRUD interface, template functionality

#### UC13: Whitelist Groups
- **Requirement**: Create and manage whitelist groups
- **Implementation**: Database group management (name, description, player list), CRUD interface, template functionality

#### UC14: OP Group Server Attachment
- **Requirement**: Attach OP groups to specific servers
- **Implementation**: Database relationship management, server settings interface, automated ops.json updates

#### UC15: Whitelist Group Server Attachment
- **Requirement**: Attach whitelist groups to specific servers
- **Implementation**: Database relationship management, server settings interface, automated whitelist.json updates

#### UC16: Multiple Group Attachment
- **Requirement**: Attach multiple groups to same server
- **Implementation**: Multi-group relationship design, priority settings, duplicate player handling, management interface

#### UC17: Dynamic Group Updates
- **Requirement**: Automatic server reflection when groups are updated
- **Implementation**: Attached server lookup, automated file updates, live server console commands, update history/rollback

#### UC18: Individual Player Management
- **Requirement**: Direct player addition separate from groups
- **Implementation**: Server-specific settings, group/individual setting integration, conflict resolution logic

#### UC19: Server Properties Updates
- **Requirement**: Update server properties
- **Implementation**: server.properties parsing, type validation, categorized setting interface

### 4. Monitoring (UC20)

#### UC20: Server Status Monitoring
- **Requirement**: Real-time server status checking (running, stopped, error states)
- **Implementation**: Process monitoring, health checks, WebSocket updates, status indicators

### 5. Backup Management (UC21-28)

#### UC21-27: Backup Operations
- **Requirement**: Create, restore, and automate server backups
- **Implementation**: Directory compression/extraction, automated scheduling (cron/task scheduler), metadata management, backup interface

#### UC28: Server Creation from Backup
- **Requirement**: Create new servers from existing backups
- **Implementation**: Backup extraction to new directories, configuration adjustment, database registration

### 6. File Management (UC29-37)

#### UC29: Server List Display
- **Requirement**: Display comprehensive server list
- **Implementation**: Database queries, card/table display formats, search/filtering capabilities

#### UC30-34: File Operations
- **Requirement**: Complete file/directory operations within server directories
- **Implementation**: Filesystem API CRUD operations, security restrictions, file explorer interface, integrated code editor

#### UC35-36: Import/Export
- **Requirement**: Server import and export functionality
- **Implementation**: Directory compression/extraction, metadata file handling, upload/download interfaces

#### UC37: Template Management
- **Requirement**: Create and edit server templates
- **Implementation**: Template generation from existing servers, customization features, sharing/import capabilities

### 7. Account Management (UC38-42)

#### UC38-42: User Account Operations
- **Requirement**: Complete user account lifecycle management
- **Implementation**: JWT authentication, bcrypt password hashing, authentication forms, account settings interface, optional email verification

### 8. Administrative Functions (UC43-46)

#### UC43-46: Admin Privileges
- **Requirement**: User approval, listing, deletion, and role management
- **Implementation**: Role-based access control (RBAC), admin dashboard, user management APIs, admin user interface

## Technical Constraints

### Security Requirements
- File operations restricted to server directories
- Role-based access control enforcement
- Secure password handling (bcrypt)
- JWT token-based authentication

### Performance Requirements
- Real-time status updates via WebSocket
- Efficient multi-server management
- Responsive file operations

### Integration Requirements
- Minecraft official API integration
- Server type vendor API compatibility
- Database persistence for all configurations
- Frontend-backend API communication

## Data Models

### Core Entities
- **Users**: Authentication, roles, approval status
- **Servers**: Configuration, status, file paths
- **Groups**: OP/whitelist player collections
- **Templates**: Reusable server configurations
- **Backups**: Metadata and storage information

### Relationships
- Users → Servers (ownership/access)
- Groups → Servers (attachment relationships)
- Templates → Servers (instantiation)
- Servers → Backups (backup relationships)