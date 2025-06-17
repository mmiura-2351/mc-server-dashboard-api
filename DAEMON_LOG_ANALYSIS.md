# Daemon Process Log Monitoring Analysis & Fixes

## Problem Summary

The daemon process log monitoring system was failing to detect Minecraft server startup completion, resulting in the error:
```
"Daemon server 1 startup completion not detected after 45s, but process is running - assuming started"
```

## Root Cause Analysis

### Primary Issue: Log File Redirection Failure
The daemon process creation code had critical flaws in the double-fork implementation that prevented proper log file redirection:

1. **File Descriptor Management Order**: The original code closed file descriptors before ensuring proper stream redirection
2. **Race Conditions**: Pipe communication for PID transfer could interfere with log redirection
3. **Buffer Issues**: Output buffering was not properly disabled for daemon processes

### Secondary Issues: Monitoring Logic
1. **Insufficient Diagnostics**: No visibility into why log detection was failing
2. **File Size Checks**: The monitoring didn't check if log files were actually being written to
3. **Limited Error Reporting**: No detailed information about log file states during timeout

## Implemented Fixes

### Fix 1: Improved Daemon Process Creation

**File**: `app/services/minecraft_server.py` - `_create_daemon_process()`

**Changes Made**:
- **Reordered operations**: Open and redirect log files BEFORE closing inherited file descriptors
- **Enhanced error handling**: Better error capture and reporting during daemon creation
- **Unbuffered output**: Added `PYTHONUNBUFFERED=1` environment variable to prevent output buffering
- **Improved file descriptor management**: Preserve stdin/stdout/stderr (0,1,2) during cleanup

**Key Code Changes**:
```python
# Open log files BEFORE closing inherited file descriptors
stdin_fd = os.open("/dev/null", os.O_RDONLY)
stdout_fd = os.open(str(log_file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
stderr_fd = os.open(str(error_file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

# Redirect streams first
os.dup2(stdin_fd, 0)
os.dup2(stdout_fd, 1) 
os.dup2(stderr_fd, 2)

# Now close other file descriptors
for fd in range(3, maxfd):
    try:
        os.close(fd)
    except OSError:
        pass

# Ensure output is not buffered
os.environ['PYTHONUNBUFFERED'] = '1'
```

### Fix 2: Alternative Daemon Creation Method

**File**: `app/services/minecraft_server.py` - `_create_daemon_process_alternative()`

**Added Fallback**: Implemented a subprocess-based daemon creation as a fallback if the double-fork method fails:

```python
process = subprocess.Popen(
    cmd,
    cwd=cwd,
    env=env,
    stdout=open(log_file_path, 'w'),
    stderr=open(error_file_path, 'w'),
    stdin=subprocess.DEVNULL,
    start_new_session=True,  # Detach from parent session
    preexec_fn=os.setsid if hasattr(os, 'setsid') else None
)
```

### Fix 3: Enhanced Log Monitoring Diagnostics

**File**: `app/services/minecraft_server.py` - `_monitor_daemon_process()`

**Improvements**:
- **File size checking**: Now verifies log files have content before attempting to read
- **Enhanced logging**: Reports file existence, size, and permissions every 5 seconds
- **Content sampling**: Shows log file content samples for debugging
- **Empty file detection**: Specific warnings for empty log files indicating redirection issues

**Key Diagnostic Function**:
```python
async def _diagnose_log_issues(self, server_id: int, server_dir: Path) -> str:
    """Diagnose potential log file issues for debugging"""
    # Checks file existence, size, permissions, and content
    # Returns comprehensive diagnostic string for logging
```

### Fix 4: Fallback Logic Integration

**File**: `app/services/minecraft_server.py` - `start_server()`

**Implementation**: Automatic fallback to alternative daemon creation if primary method fails:

```python
# Create daemon process using double-fork technique
daemon_pid = await self._create_daemon_process(cmd, str(abs_server_dir), env, server.id)

# If primary daemon creation fails, try alternative method
if not daemon_pid:
    logger.warning(f"Primary daemon creation failed for server {server.id}, trying alternative method")
    daemon_pid = await self._create_daemon_process_alternative(cmd, str(abs_server_dir), env, server.id)
```

## Expected Results

With these fixes, the daemon process log monitoring should now:

1. **Properly redirect output**: Minecraft server logs will be written to `server.log` files
2. **Detect startup completion**: The "Done" message will be detected within the 45-second window
3. **Provide better diagnostics**: Clear information about log file states and redirection issues
4. **Have reliable fallback**: Alternative daemon creation method if primary fails
5. **Faster detection**: Typical startup detection should occur within 3-10 seconds for healthy servers

## Testing Recommendations

1. **Create a new server** and monitor the logs during startup
2. **Check log file contents** to ensure they contain Minecraft server output
3. **Verify startup detection timing** - should be much faster than 45 seconds
4. **Monitor diagnostic messages** for any remaining issues

## Additional Debugging

If issues persist, check:

1. **Log file permissions**: Ensure the daemon process can write to log files
2. **Java version compatibility**: Verify correct Java version for Minecraft version
3. **Server directory permissions**: Ensure write access to server directories
4. **Resource limits**: Check if system limits are preventing proper daemon creation

The diagnostic logging will now provide detailed information about any remaining issues.