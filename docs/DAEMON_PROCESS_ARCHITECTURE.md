# Daemon Process Architecture

This document describes the daemon process architecture implemented for Minecraft server management, including process creation, monitoring, persistence, and recovery mechanisms.

## Overview

The Minecraft Server Dashboard API uses a sophisticated daemon process architecture to manage Minecraft servers independently of the main API process. This ensures server continuity across API restarts and provides robust process isolation.

## Architecture Components

### 1. Daemon Process Creation

#### Double-Fork Technique
The system uses the traditional Unix double-fork technique to create true daemon processes:

```
Parent Process (API)
    └── Fork 1 (Intermediate)
        └── Fork 2 (Daemon) → Minecraft Server
```

**Benefits:**
- Complete detachment from parent process
- Process becomes child of init (PID 1)
- No zombie processes
- Independent process lifecycle

#### Process Characteristics
- **Session Leader**: Daemon becomes session leader
- **Process Group Leader**: Creates new process group
- **Working Directory**: Set to server directory
- **File Descriptors**: stdin/stdout/stderr redirected
- **Signal Handling**: Custom signal handlers for graceful shutdown

### 2. Process Persistence

#### PID File Management
Each daemon process creates a PID file containing:

```json
{
    "pid": 12345,
    "server_id": 1,
    "port": 25565,
    "cmd": ["java", "-Xmx1024M", "-jar", "server.jar"],
    "rcon_port": 25575,
    "rcon_password": "secure_password",
    "created_at": "2024-01-01T12:00:00Z"
}
```

**PID File Location**: `{server_directory}/minecraft_server.pid`

#### Auto-Recovery on Startup
When the API starts, it:
1. Scans server directories for PID files
2. Verifies process existence using `psutil`
3. Restores process tracking for running servers
4. Updates database status accordingly

### 3. Process Monitoring

#### Real-Time Monitoring
- **Health Checks**: Every 5 seconds (configurable)
- **Process Verification**: Using PID and `/proc` filesystem
- **Resource Monitoring**: Memory, CPU, file descriptors
- **Log Monitoring**: File-based log reading with rotation

#### Status Transitions
```
STARTING → RUNNING → STOPPED/ERROR
```

- **STARTING**: Process created, initial verification
- **RUNNING**: Process stable, accepting commands
- **STOPPED**: Graceful shutdown completed
- **ERROR**: Process crashed or failed

### 4. Log Management

#### File-Based Log Reading
Since daemon processes are detached, logs are read from files:

```python
async def _read_server_logs(self, server_process: ServerProcess):
    log_file = server_directory / "server.log"
    # Tail-follow implementation with queue management
```

**Features:**
- **Real-time updates**: File watching with asyncio
- **Queue management**: Configurable size with overflow protection
- **Log rotation**: Automatic handling of rotated logs
- **Error resilience**: Continues on temporary file access issues

### 5. RCON Integration

#### Real-Time Command Execution
```python
class RealTimeServerCommands:
    async def execute_command(self, server_id: int, command: str):
        # RCON connection and command execution
```

**Supported Commands:**
- `/whitelist reload`
- `/op <player>`
- `/deop <player>`
- Custom server commands

**Configuration:**
- Auto-generated RCON passwords
- Configurable ports (default: 25575)
- Connection pooling and retry logic

## Configuration

### Environment Variables

```bash
# Daemon Process Settings
DAEMON_MODE=double_fork                    # Creation method
DAEMON_ENABLE_PERSISTENCE=true            # PID file creation
DAEMON_PID_DIRECTORY=/path/to/pids        # Custom PID directory

# Monitoring Settings
DAEMON_ENABLE_MONITORING=true             # Process monitoring
DAEMON_MONITORING_INTERVAL=5              # Check interval (seconds)
DAEMON_STARTUP_TIMEOUT=30                 # Startup verification timeout

# Resource Limits
DAEMON_MAX_MEMORY_MB=2048                 # Maximum memory per process
DAEMON_MAX_CPU_PERCENT=80.0               # CPU usage limit
DAEMON_MAX_OPEN_FILES=1024                # File descriptor limit

# Logging
DAEMON_LOG_LEVEL=info                     # Log verbosity
DAEMON_ENABLE_LOGS=true                   # Daemon operation logging
DAEMON_LOG_ROTATION_SIZE=100              # Log rotation size (MB)

# Security
DAEMON_ENABLE_ISOLATION=true              # Process isolation verification
DAEMON_VERIFY_DETACHMENT=true             # Detachment verification
DAEMON_SECURE_ENVIRONMENT=true            # Secure environment variables

# RCON Settings
DAEMON_ENABLE_RCON=true                   # RCON integration
DAEMON_RCON_TIMEOUT=10                    # Connection timeout
DAEMON_RCON_RETRY_ATTEMPTS=3              # Retry attempts

# Recovery Settings
DAEMON_ENABLE_AUTO_RECOVERY=true          # Auto-recovery on startup
DAEMON_RECOVERY_TIMEOUT=60                # Recovery operation timeout
DAEMON_MAX_RECOVERY_ATTEMPTS=3            # Maximum recovery attempts
```

### Configuration Class

```python
from app.core.daemon_config import DaemonConfig

config = DaemonConfig(
    daemon_mode=DaemonMode.DOUBLE_FORK,
    enable_process_persistence=True,
    monitoring_interval_seconds=5
)
```

## Security Considerations

### Process Isolation
- **User/Group Isolation**: Processes run under restricted user
- **Resource Limits**: Memory, CPU, and file descriptor limits
- **Filesystem Access**: Limited to server directories
- **Network Access**: Only required ports (Minecraft + RCON)

### Signal Handling
```python
def setup_signal_handlers():
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGHUP, reload_config)
```

### Environment Sanitization
```python
def create_secure_environment():
    env = {
        "TERM": "dumb",
        "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true",
        "PATH": "/usr/bin:/bin"
    }
    return env
```

## Error Handling

### Common Issues and Solutions

#### 1. Process Creation Failure
**Symptoms**: Daemon process not created
**Solutions**:
- Check user permissions
- Verify resource limits
- Review system ulimits

#### 2. Process Detachment Failure
**Symptoms**: Process remains attached to parent
**Solutions**:
- Verify double-fork implementation
- Check session/process group creation
- Review signal handling

#### 3. PID File Issues
**Symptoms**: Recovery fails on startup
**Solutions**:
- Check directory permissions
- Verify PID file format
- Review file locking

#### 4. RCON Connection Issues
**Symptoms**: Commands not executing
**Solutions**:
- Verify RCON configuration
- Check port availability
- Review password generation

## Performance Optimization

### Resource Management
- **Memory**: JVM heap size optimization
- **CPU**: Process affinity and scheduling
- **I/O**: Async file operations
- **Network**: Connection pooling

### Monitoring Efficiency
- **Batch Operations**: Multiple checks per cycle
- **Lazy Loading**: Process info only when needed
- **Caching**: Status and metadata caching
- **Throttling**: Rate limiting for resource-intensive operations

## Troubleshooting

### Debug Mode
```bash
DAEMON_LOG_LEVEL=debug
```

### Process Inspection
```bash
# Check running daemon processes
ps aux | grep java

# Verify process hierarchy
pstree -p <daemon_pid>

# Check resource usage
cat /proc/<daemon_pid>/status
```

### Log Analysis
```bash
# Daemon operation logs
tail -f logs/daemon_operations.log

# Server-specific logs
tail -f servers/<server_id>/server.log

# RCON command logs
grep "RCON" logs/app.log
```

## Migration Guide

### From Subprocess to Daemon

1. **Backup Current State**
   ```bash
   # Stop all servers
   curl -X POST /api/v1/servers/shutdown-all

   # Backup database
   cp app.db app.db.backup
   ```

2. **Update Configuration**
   ```bash
   export DAEMON_MODE=double_fork
   export DAEMON_ENABLE_PERSISTENCE=true
   ```

3. **Restart API**
   ```bash
   # API will auto-detect and migrate
   uv run fastapi dev
   ```

4. **Verify Migration**
   ```bash
   # Check process restoration
   curl /api/v1/health

   # Verify server status
   curl /api/v1/servers/
   ```

## Future Enhancements

### Planned Features
- **Container Integration**: Docker/Podman support
- **Distributed Deployment**: Multi-node server management
- **Advanced Monitoring**: Prometheus metrics
- **Auto-scaling**: Dynamic resource allocation

### Performance Improvements
- **Zero-downtime Updates**: Rolling daemon updates
- **Load Balancing**: Server distribution across nodes
- **Resource Prediction**: ML-based resource planning

## API Integration

### Server Lifecycle Endpoints

```python
# Start server (creates daemon)
POST /api/v1/servers/{server_id}/start

# Stop server (graceful daemon shutdown)
POST /api/v1/servers/{server_id}/stop

# Server status (includes daemon process info)
GET /api/v1/servers/{server_id}/status

# Process information
GET /api/v1/servers/{server_id}/process-info
```

### Process Management Endpoints

```python
# List all daemon processes
GET /api/v1/processes/

# Process details
GET /api/v1/processes/{pid}

# Force cleanup
DELETE /api/v1/processes/{pid}
```

This architecture provides a robust, scalable, and maintainable solution for Minecraft server process management while ensuring security, performance, and reliability.
