# RCON Integration Guide

This document describes the RCON (Remote Console) integration system for real-time Minecraft server command execution and management.

## Overview

The RCON integration enables real-time command execution on Minecraft servers without requiring direct process interaction. This is essential for the daemon architecture where servers run as detached processes.

## Architecture

### Components

```
API Request → RCON Service → Minecraft Server (RCON Protocol)
     ↓              ↓              ↓
Group Management → Command Queue → Server Response
```

### Key Classes

#### 1. RealTimeServerCommands
Main service for RCON command execution:

```python
class RealTimeServerCommands:
    async def execute_command(server_id: int, command: str) -> bool
    async def handle_group_change_commands(...)
    async def reload_whitelist(server_id: int) -> bool
    async def op_player(server_id: int, player: dict) -> bool
    async def deop_player(server_id: int, player: dict) -> bool
```

#### 2. RCON Configuration Management
Automatic RCON setup and password management:

```python
async def _ensure_rcon_configured(server_dir: Path, server_id: int):
    # Auto-generate RCON password
    # Configure server.properties
    # Return RCON connection details
```

## RCON Protocol Implementation

### Connection Management

```python
class RCONConnection:
    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password
        self.socket = None

    async def connect(self) -> bool:
        # TCP connection establishment
        # Authentication handshake

    async def send_command(self, command: str) -> str:
        # Command packet construction
        # Response parsing

    async def disconnect(self):
        # Clean connection closure
```

### Protocol Details

#### Packet Structure
```
┌─────────────┬──────────┬──────────┬─────────────┬─────────────┐
│   Length    │ Request  │   Type   │   Payload   │  Null Term  │
│  (4 bytes)  │   ID     │(4 bytes) │ (variable)  │  (2 bytes)  │
│             │(4 bytes) │          │             │             │
└─────────────┴──────────┴──────────┴─────────────┴─────────────┘
```

#### Packet Types
- **0x03**: Login (Authentication)
- **0x02**: Command Execution
- **0x00**: Response Data

#### Authentication Flow
1. Send login packet with password
2. Receive authentication response
3. Verify successful authentication
4. Ready for command execution

## Configuration

### Automatic RCON Setup

The system automatically configures RCON for each server:

```python
async def configure_rcon(server_dir: Path, server_id: int):
    """Auto-configure RCON for a server"""

    # Generate secure password
    rcon_password = secrets.token_urlsafe(16)

    # Find available port
    rcon_port = await find_available_port(25575)

    # Update server.properties
    properties = {
        'enable-rcon': 'true',
        'rcon.port': str(rcon_port),
        'rcon.password': rcon_password,
        'broadcast-rcon-to-ops': 'false'
    }

    await update_server_properties(server_dir, properties)

    return rcon_port, rcon_password
```

### Manual Configuration

For custom RCON setup, modify `server.properties`:

```properties
# Enable RCON
enable-rcon=true

# RCON port (default: 25575)
rcon.port=25575

# RCON password (secure random string)
rcon.password=your_secure_password

# Disable RCON broadcast to ops (security)
broadcast-rcon-to-ops=false

# Optional: RCON IP binding
rcon.ip=127.0.0.1
```

## Command System

### Supported Commands

#### 1. Whitelist Management
```python
# Reload whitelist from file
await rcon_service.reload_whitelist(server_id)
# Executes: /whitelist reload
```

#### 2. Operator Management
```python
# Grant operator privileges
await rcon_service.op_player(server_id, {
    "username": "player123",
    "uuid": "123e4567-e89b-12d3-a456-426614174000"
})
# Executes: /op player123

# Revoke operator privileges
await rcon_service.deop_player(server_id, {
    "username": "player123",
    "uuid": "123e4567-e89b-12d3-a456-426614174000"
})
# Executes: /deop player123
```

#### 3. Custom Commands
```python
# Execute any Minecraft command
result = await rcon_service.execute_command(server_id, "say Hello World!")
# Executes: /say Hello World!
```

### Group Integration

#### Whitelist Group Changes
```python
async def handle_whitelist_group_change(server_id: int, change_type: str):
    """Handle whitelist group attach/detach"""
    if change_type in ["attach", "detach", "update"]:
        success = await rcon_service.reload_whitelist(server_id)
        if success:
            logger.info(f"Whitelist reloaded for server {server_id}")
        else:
            logger.warning(f"Failed to reload whitelist for server {server_id}")
```

#### OP Group Changes
```python
async def handle_op_group_change(server_id: int, change_type: str, removed_players: list):
    """Handle OP group changes with deop commands"""
    if change_type == "detach" and removed_players:
        # Send deop commands for all removed players
        for player in removed_players:
            success = await rcon_service.deop_player(server_id, player)
            if success:
                logger.info(f"Deopped {player['username']} on server {server_id}")
            else:
                logger.warning(f"Failed to deop {player['username']} on server {server_id}")

    # Always reload whitelist for consistency
    await rcon_service.reload_whitelist(server_id)
```

## Error Handling

### Connection Errors

```python
class RCONConnectionError(Exception):
    """RCON connection failed"""
    pass

class RCONAuthenticationError(Exception):
    """RCON authentication failed"""
    pass

class RCONCommandError(Exception):
    """RCON command execution failed"""
    pass
```

### Retry Logic

```python
async def execute_with_retry(server_id: int, command: str, max_retries: int = 3):
    """Execute RCON command with retry logic"""
    for attempt in range(max_retries):
        try:
            return await rcon_service.execute_command(server_id, command)
        except RCONConnectionError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

### Fallback Mechanisms

When RCON fails, the system falls back to:

1. **File-based operations**: Direct whitelist.json modification
2. **Scheduled reload**: Mark for reload on next server restart
3. **User notification**: Inform about manual intervention needed

## Security Considerations

### Password Management

```python
def generate_rcon_password() -> str:
    """Generate cryptographically secure RCON password"""
    return secrets.token_urlsafe(32)  # 256-bit entropy

def store_rcon_credentials(server_id: int, password: str):
    """Securely store RCON credentials"""
    # Encrypt password before storage
    encrypted = encrypt_with_server_key(password, server_id)
    # Store in secure configuration
```

### Network Security

- **Localhost Only**: RCON binds to 127.0.0.1 by default
- **Firewall Rules**: Block external RCON access
- **Port Isolation**: Unique port per server
- **Connection Limits**: Rate limiting and connection pooling

### Command Validation

```python
def validate_rcon_command(command: str) -> bool:
    """Validate RCON command for security"""

    # Whitelist allowed commands
    allowed_commands = {
        'whitelist', 'op', 'deop', 'say', 'tellraw',
        'kick', 'ban', 'pardon', 'list'
    }

    cmd_parts = command.strip().split()
    if not cmd_parts:
        return False

    base_command = cmd_parts[0].lstrip('/')
    return base_command in allowed_commands
```

## Performance Optimization

### Connection Pooling

```python
class RCONConnectionPool:
    def __init__(self, max_connections: int = 10):
        self.pool = {}
        self.max_connections = max_connections

    async def get_connection(self, server_id: int) -> RCONConnection:
        """Get pooled connection for server"""
        if server_id not in self.pool:
            self.pool[server_id] = await self.create_connection(server_id)
        return self.pool[server_id]

    async def release_connection(self, server_id: int):
        """Release connection back to pool"""
        # Keep connection alive for reuse
```

### Command Batching

```python
async def batch_execute_commands(server_id: int, commands: List[str]):
    """Execute multiple commands in single connection"""
    connection = await pool.get_connection(server_id)

    results = []
    for command in commands:
        result = await connection.send_command(command)
        results.append(result)

    await pool.release_connection(server_id)
    return results
```

### Caching

```python
@lru_cache(maxsize=100, ttl=300)  # 5-minute cache
async def get_server_rcon_info(server_id: int):
    """Cached RCON connection information"""
    return await load_rcon_config(server_id)
```

## Monitoring and Logging

### Command Logging

```python
async def log_rcon_command(server_id: int, command: str, success: bool, response: str):
    """Log RCON command execution"""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "server_id": server_id,
        "command": command,
        "success": success,
        "response": response[:500],  # Truncate long responses
        "source": "rcon"
    }

    logger.info("RCON command executed", extra=log_entry)
```

### Health Monitoring

```python
async def monitor_rcon_health():
    """Monitor RCON connection health"""
    for server_id in active_servers:
        try:
            # Test connection with simple command
            await rcon_service.execute_command(server_id, "list")
            rcon_status[server_id] = "healthy"
        except Exception as e:
            rcon_status[server_id] = f"error: {e}"
            logger.warning(f"RCON health check failed for server {server_id}: {e}")
```

## API Integration

### REST Endpoints

```python
@router.post("/servers/{server_id}/commands")
async def execute_server_command(
    server_id: int,
    command: ServerCommand,
    current_user: User = Depends(get_current_active_user)
):
    """Execute command via RCON"""
    # Validate permissions
    # Execute command
    # Return result
```

### WebSocket Integration

```python
@websocket_router.websocket("/servers/{server_id}/console")
async def server_console(websocket: WebSocket, server_id: int):
    """Real-time server console via RCON"""
    await websocket.accept()

    try:
        while True:
            # Receive command from WebSocket
            command = await websocket.receive_text()

            # Execute via RCON
            result = await rcon_service.execute_command(server_id, command)

            # Send result back
            await websocket.send_text(result)
    except WebSocketDisconnect:
        pass
```

## Testing

### Unit Tests

```python
class TestRCONService:
    @pytest.mark.asyncio
    async def test_execute_command_success(self):
        """Test successful command execution"""

    @pytest.mark.asyncio  
    async def test_connection_failure_retry(self):
        """Test retry logic on connection failure"""

    @pytest.mark.asyncio
    async def test_group_change_commands(self):
        """Test group change command handling"""
```

### Integration Tests

```python
class TestRCONIntegration:
    @pytest.mark.asyncio
    async def test_server_lifecycle_with_rcon(self):
        """Test complete server lifecycle with RCON"""

    @pytest.mark.asyncio
    async def test_group_operations_end_to_end(self):
        """Test group operations through RCON"""
```

### Load Testing

```python
async def rcon_load_test():
    """Test RCON performance under load"""
    tasks = []
    for i in range(100):
        task = asyncio.create_task(
            rcon_service.execute_command(1, f"say Test {i}")
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    success_rate = sum(1 for r in results if r) / len(results)
    print(f"RCON load test success rate: {success_rate:.2%}")
```

## Troubleshooting

### Common Issues

#### 1. Connection Refused
**Cause**: RCON not enabled or wrong port
**Solution**: Check server.properties configuration

#### 2. Authentication Failed
**Cause**: Wrong password or authentication timeout
**Solution**: Verify password, check server logs

#### 3. Command Not Recognized
**Cause**: Invalid command syntax or server version incompatibility
**Solution**: Validate command format, check Minecraft version

#### 4. Timeout Errors
**Cause**: Network issues or server overload
**Solution**: Increase timeout, check server performance

### Debug Commands

```bash
# Test RCON connectivity
telnet localhost 25575

# Check server RCON logs
grep "RCON" servers/*/logs/latest.log

# Verify RCON configuration
cat servers/*/server.properties | grep rcon
```

### Log Analysis

```python
# RCON command success rate
success_commands = grep "RCON command executed.*success.*true" logs/
total_commands = grep "RCON command executed" logs/
success_rate = len(success_commands) / len(total_commands)
```

This RCON integration provides robust, real-time command execution capabilities essential for modern Minecraft server management while maintaining security and performance standards.
