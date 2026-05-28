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

**PID File Location**: `{server_directory}/server.pid`

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

The full inventory of 23 `DAEMON_*` environment variables — with defaults,
validators, and cross-field constraints — is documented in
[`docs/CONFIGURATION.md` § "Daemon process settings"](CONFIGURATION.md#daemon-process-settings-daemon_).
That section is the single source of truth; this document only covers the
behavioural / architectural context for those knobs.

Quick reference: groupings are *process creation*, *monitoring*,
*resource limits* (`DaemonProcessLimits`), *logging*, *security*, *RCON*,
and *recovery*. The defaults are appropriate for production — only override
when there is a concrete operational reason.

### Configuration Class

```python
from app.core.daemon_config import DaemonConfig, DaemonMode

config = DaemonConfig(
    daemon_mode=DaemonMode.DOUBLE_FORK,
    enable_process_persistence=True,
    monitoring_interval_seconds=5,
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

If you are **upgrading an existing deployment** from a pre-PR-#60 commit,
follow the dedicated guide:
[`docs/DAEMON_MIGRATION.md`](DAEMON_MIGRATION.md). It covers the full
pre-upgrade checklist (stop every server first — old `asyncio`-tracked
processes cannot be adopted), the step-by-step upgrade, post-upgrade
verification, and rollback procedure.

Short summary:

1. Stop every Minecraft server via `POST /api/v1/servers/{server_id}/stop`.
2. Back up the application DB and the `servers/` directory.
3. Record the current git SHA (needed for rollback).
4. Pull the new code, run `uv sync`, and review new `DAEMON_*` env vars.
5. Restart the API; auto-sync rehydrates `server.pid` files for any
   freshly-started daemons.
6. Verify with `curl /api/v1/health`, `ps -eo pid,ppid,args | grep server.jar`,
   and inspection of `server.pid` JSON.

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

The HTTP surface that interacts with the daemon manager is the existing
server-control router under `/api/v1/servers/` (see
`app/servers/routers/control.py`):

```text
POST   /api/v1/servers/{server_id}/start    # creates daemon via _create_daemon_process
POST   /api/v1/servers/{server_id}/stop     # graceful daemon shutdown (RCON /stop, then SIGTERM)
POST   /api/v1/servers/{server_id}/restart  # stop + start
GET    /api/v1/servers/{server_id}/status   # ServerStatusResponse; reflects post-AUTO_SYNC state
```

There are **no dedicated `/api/v1/processes/…` endpoints** and **no
bulk `shutdown-all` endpoint** at this time. Bulk shutdown happens
implicitly when the API exits **and** `KEEP_SERVERS_ON_SHUTDOWN=False`
(see [`docs/DAEMON_MIGRATION.md`](DAEMON_MIGRATION.md) §3.1). For
introspecting individual daemons from outside the API, read the
`server.pid` JSON directly or use `ps -eo pid,ppid,args`.

### Health endpoints (Issue #21)

```text
GET /healthz                   # cheap liveness, no DB I/O
GET /readyz                    # readiness; runs all registered checks
GET /api/v1/health             # legacy back-compat alias
GET /api/v1/health/detail      # admin-only verbose report
```

This architecture provides a robust, scalable, and maintainable solution for Minecraft server process management while ensuring security, performance, and reliability.
