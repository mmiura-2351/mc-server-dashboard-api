import asyncio
import json
import logging
import os
import secrets
import signal
import socket
import struct
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import psutil

from app.core.config import settings
from app.servers.models import Server, ServerStatus
from app.services.java_compatibility import java_compatibility_service

logger = logging.getLogger(__name__)


@dataclass
class ServerProcess:
    """Represents a running Minecraft server process"""

    server_id: int
    process: asyncio.subprocess.Process
    log_queue: asyncio.Queue
    status: ServerStatus
    started_at: datetime
    pid: Optional[int] = None
    # Directory path for the server (needed for log monitoring)
    server_directory: Optional[Path] = None
    # RCON configuration for command sending
    rcon_port: Optional[int] = None
    rcon_password: Optional[str] = None
    # Track background tasks for proper cleanup
    log_task: Optional[asyncio.Task] = None
    monitor_task: Optional[asyncio.Task] = None


class MinecraftServerManager:
    """Manages Minecraft server processes using asyncio"""

    def __init__(self, log_queue_size: Optional[int] = None):
        self.processes: Dict[int, ServerProcess] = {}
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)
        # Callback for database status updates
        self._status_update_callback: Optional[Callable[[int, ServerStatus], None]] = None
        # Configurable log queue size to prevent memory leaks
        self.log_queue_size = log_queue_size or settings.SERVER_LOG_QUEUE_SIZE
        self.java_check_timeout = settings.JAVA_CHECK_TIMEOUT

    def set_status_update_callback(self, callback: Callable[[int, ServerStatus], None]):
        """Set callback function to update database when server status changes"""
        self._status_update_callback = callback

    def _get_pid_file_path(self, server_id: int, server_dir: Path) -> Path:
        """Get path to PID file for server"""
        return server_dir / "server.pid"

    async def _create_daemon_process_alternative(
        self, cmd: List[str], cwd: str, env: Dict[str, str], server_id: int
    ) -> Optional[int]:
        """Alternative daemon creation using subprocess with detachment"""
        log_file_path = Path(cwd) / "server.log"
        error_file_path = Path(cwd) / "server_error.log"

        try:
            # Ensure log files exist
            log_file_path.touch(exist_ok=True)
            error_file_path.touch(exist_ok=True)

            # Create the process with proper detachment
            import subprocess

            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=open(log_file_path, "w"),
                stderr=open(error_file_path, "w"),
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent session
                preexec_fn=(
                    os.setsid if hasattr(os, "setsid") else None
                ),  # Create new process group
            )

            daemon_pid = process.pid
            logger.info(
                f"Created alternative daemon process {daemon_pid} for server {server_id}"
            )

            # Verify process is running
            if await self._is_process_running(daemon_pid):
                return daemon_pid
            else:
                logger.error(f"Alternative daemon process {daemon_pid} died immediately")
                return None

        except Exception as e:
            logger.error(
                f"Alternative daemon creation failed for server {server_id}: {e}"
            )
            return None

    async def _create_daemon_process(
        self, cmd: List[str], cwd: str, env: Dict[str, str], server_id: int
    ) -> Optional[int]:
        """Create a true daemon process using double-fork technique for complete detachment"""
        log_file_path = Path(cwd) / "server.log"
        error_file_path = Path(cwd) / "server_error.log"

        # Ensure log files exist
        log_file_path.touch(exist_ok=True)
        error_file_path.touch(exist_ok=True)

        def daemon_fork():
            """Double fork daemon creation in a separate thread"""
            try:
                # First fork
                pid = os.fork()
                if pid > 0:
                    # Parent process - wait for child and return its PID
                    os.waitpid(pid, 0)
                    return None  # This will be handled by the child
            except OSError as e:
                logger.error(f"First fork failed for server {server_id}: {e}")
                return None

            # First child process
            try:
                # Decouple from parent environment
                os.chdir(cwd)
                os.setsid()  # Create new session and become session leader
                os.umask(0)  # Clear umask for proper file permissions

                # Second fork to prevent acquiring controlling terminal
                pid = os.fork()
                if pid > 0:
                    # Exit first child
                    os._exit(0)
            except OSError as e:
                logger.error(f"Second fork failed for server {server_id}: {e}")
                os._exit(1)

            # Second child process (daemon)
            try:
                # Close all inherited file descriptors
                import resource

                maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
                if maxfd == resource.RLIM_INFINITY:
                    maxfd = 1024  # Default limit

                # Close all file descriptors except the ones we need
                for fd in range(3, maxfd):
                    try:
                        os.close(fd)
                    except OSError:
                        pass

                # Redirect standard streams to log files
                stdin_fd = os.open("/dev/null", os.O_RDONLY)
                stdout_fd = os.open(
                    str(log_file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
                )
                stderr_fd = os.open(
                    str(error_file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
                )

                # Duplicate file descriptors to standard streams
                os.dup2(stdin_fd, 0)  # stdin
                os.dup2(stdout_fd, 1)  # stdout
                os.dup2(stderr_fd, 2)  # stderr

                # Close the original file descriptors
                os.close(stdin_fd)
                os.close(stdout_fd)
                os.close(stderr_fd)

                # Execute the Minecraft server command
                os.execvpe(cmd[0], cmd, env)

            except Exception as e:
                # If anything fails, log and exit
                sys.stderr.write(f"Daemon process failed for server {server_id}: {e}\n")
                os._exit(1)

        # Use a thread to handle the fork operations
        daemon_pid = None
        exception_occurred = None

        def threaded_fork():
            nonlocal daemon_pid, exception_occurred
            try:
                # Create a pipe to communicate the daemon PID back to parent
                read_fd, write_fd = os.pipe()

                # First fork
                pid = os.fork()
                if pid > 0:
                    # Parent process
                    os.close(write_fd)
                    try:
                        # Read the daemon PID from pipe
                        pid_data = os.read(read_fd, 1024)
                        if pid_data:
                            daemon_pid = int(pid_data.decode().strip())
                        os.waitpid(pid, 0)  # Wait for intermediate child
                    finally:
                        os.close(read_fd)
                    return

                # Intermediate child process
                os.close(read_fd)
                try:
                    # Decouple from parent environment
                    os.chdir(cwd)
                    os.setsid()  # Create new session
                    os.umask(0)

                    # Second fork
                    pid = os.fork()
                    if pid > 0:
                        # Send daemon PID to parent and exit
                        os.write(write_fd, str(pid).encode())
                        os.close(write_fd)
                        os._exit(0)

                    # Daemon process
                    os.close(write_fd)

                    # Open log files BEFORE closing inherited file descriptors
                    # This ensures the file descriptors are available for redirection
                    stdin_fd = os.open("/dev/null", os.O_RDONLY)
                    stdout_fd = os.open(
                        str(log_file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
                    )
                    stderr_fd = os.open(
                        str(error_file_path),
                        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                        0o644,
                    )

                    # Redirect streams first
                    os.dup2(stdin_fd, 0)
                    os.dup2(stdout_fd, 1)
                    os.dup2(stderr_fd, 2)

                    # Close the original file descriptors
                    os.close(stdin_fd)
                    os.close(stdout_fd)
                    os.close(stderr_fd)

                    # Now close all OTHER inherited file descriptors (but preserve 0,1,2)
                    import resource

                    maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
                    if maxfd == resource.RLIM_INFINITY:
                        maxfd = 1024

                    # Close file descriptors starting from 3 (preserve stdin, stdout, stderr)
                    for fd in range(3, maxfd):
                        try:
                            os.close(fd)
                        except OSError:
                            pass

                    # Ensure output is not buffered
                    os.environ["PYTHONUNBUFFERED"] = "1"

                    # Execute command
                    os.execvpe(cmd[0], cmd, env)

                except Exception as e:
                    # Write error to stderr before exiting
                    try:
                        sys.stderr.write(f"Intermediate child failed: {e}\n")
                        sys.stderr.flush()
                    except Exception:
                        pass
                    os._exit(1)

            except Exception as e:
                exception_occurred = e

        # Run daemon creation in thread to avoid blocking asyncio
        thread = threading.Thread(target=threaded_fork)
        thread.start()
        thread.join(timeout=10.0)  # 10 second timeout

        if thread.is_alive():
            logger.error(f"Daemon creation timed out for server {server_id}")
            return None

        if exception_occurred:
            logger.error(
                f"Daemon creation failed for server {server_id}: {exception_occurred}"
            )
            return None

        if daemon_pid:
            logger.info(
                f"Successfully created daemon process {daemon_pid} for server {server_id}"
            )
            return daemon_pid
        else:
            logger.error(f"Failed to get daemon PID for server {server_id}")
            return None

    async def _stop_daemon_process(
        self, server_id: int, server_process: ServerProcess, force: bool = False
    ) -> bool:
        """Stop a daemon process by PID"""
        try:
            if not server_process.pid:
                logger.error(f"No PID available for daemon server {server_id}")
                return False

            # Check if process is still running
            if not await self._is_process_running(server_process.pid):
                logger.info(
                    f"Daemon server {server_id} (PID: {server_process.pid}) is already stopped"
                )
                await self._cleanup_server_process(server_id)
                self._notify_status_change(server_id, ServerStatus.stopped)
                return True

            # Start with graceful SIGTERM (even for non-force stops)
            # Note: Daemon processes can't receive stdin commands easily, so we use signals

            # Force stop with SIGTERM
            try:
                os.kill(server_process.pid, signal.SIGTERM)
                logger.info(
                    f"Sent SIGTERM to daemon server {server_id} (PID: {server_process.pid})"
                )

                # Wait up to 5 seconds for SIGTERM
                for i in range(5):
                    await asyncio.sleep(1)
                    if not await self._is_process_running(server_process.pid):
                        logger.info(f"Daemon server {server_id} stopped with SIGTERM")
                        await self._cleanup_server_process(server_id)
                        self._notify_status_change(server_id, ServerStatus.stopped)
                        return True

                # If SIGTERM doesn't work, use SIGKILL
                logger.warning(
                    f"SIGTERM failed for daemon server {server_id}, using SIGKILL"
                )
                os.kill(server_process.pid, signal.SIGKILL)

                # Wait up to 3 seconds for SIGKILL
                for i in range(3):
                    await asyncio.sleep(1)
                    if not await self._is_process_running(server_process.pid):
                        logger.info(f"Daemon server {server_id} stopped with SIGKILL")
                        await self._cleanup_server_process(server_id)
                        self._notify_status_change(server_id, ServerStatus.stopped)
                        return True

                logger.error(
                    f"Failed to stop daemon server {server_id} even with SIGKILL"
                )
                return False

            except ProcessLookupError:
                # Process already dead
                logger.info(f"Daemon server {server_id} process already terminated")
                await self._cleanup_server_process(server_id)
                self._notify_status_change(server_id, ServerStatus.stopped)
                return True
            except PermissionError:
                logger.error(
                    f"Permission denied when trying to stop daemon server {server_id}"
                )
                return False
            except Exception as e:
                logger.error(f"Error stopping daemon server {server_id}: {e}")
                return False

        except Exception as e:
            logger.error(
                f"Critical error stopping daemon server {server_id}: {e}", exc_info=True
            )
            return False

    async def _write_pid_file(
        self,
        server_id: int,
        server_dir: Path,
        process: asyncio.subprocess.Process,
        port: int,
        command: List[str],
        rcon_port: Optional[int] = None,
        rcon_password: Optional[str] = None,
    ) -> bool:
        """Write PID file with process metadata including RCON credentials"""
        try:
            pid_file_path = self._get_pid_file_path(server_id, server_dir)
            pid_data = {
                "server_id": server_id,
                "pid": process.pid,
                "port": port,
                "started_at": datetime.now().isoformat(),
                "command": command,
                "api_version": "1.0",  # For future compatibility
            }

            # Add RCON credentials if available
            if rcon_port and rcon_password:
                pid_data.update(
                    {
                        "rcon_port": rcon_port,
                        "rcon_password": rcon_password,
                    }
                )

            with open(pid_file_path, "w") as f:
                json.dump(pid_data, f, indent=2)

            logger.info(f"Created PID file for server {server_id}: {pid_file_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to write PID file for server {server_id}: {e}")
            return False

    async def _read_pid_file(
        self, server_id: int, server_dir: Path
    ) -> Optional[Dict[str, Any]]:
        """Read PID file and return process metadata"""
        try:
            pid_file_path = self._get_pid_file_path(server_id, server_dir)
            if not pid_file_path.exists():
                return None

            with open(pid_file_path, "r") as f:
                pid_data = json.load(f)

            # Validate required fields
            required_fields = ["server_id", "pid", "port", "started_at"]
            if not all(field in pid_data for field in required_fields):
                logger.warning(f"Invalid PID file format for server {server_id}")
                return None

            return pid_data

        except Exception as e:
            logger.error(f"Failed to read PID file for server {server_id}: {e}")
            return None

    async def _remove_pid_file(self, server_id: int, server_dir: Path) -> bool:
        """Remove PID file for server"""
        try:
            pid_file_path = self._get_pid_file_path(server_id, server_dir)
            if pid_file_path.exists():
                pid_file_path.unlink()
                logger.info(f"Removed PID file for server {server_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove PID file for server {server_id}: {e}")
            return False

    async def _is_process_running(self, pid: int) -> bool:
        """Check if process with given PID is still running"""
        try:
            if not psutil.pid_exists(pid):
                return False

            # Additional check to ensure process is accessible
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        except Exception as e:
            logger.error(f"Error checking process {pid}: {e}")
            return False

    async def _restore_process_from_pid(self, server_id: int, server_dir: Path) -> bool:
        """Restore running process from PID file if still active"""
        try:
            pid_data = await self._read_pid_file(server_id, server_dir)
            if not pid_data:
                return False

            pid = pid_data["pid"]
            if not await self._is_process_running(pid):
                logger.info(f"Process {pid} for server {server_id} is no longer running")
                await self._remove_pid_file(server_id, server_dir)
                return False

            # Verify this is actually a Java process (additional safety check)
            try:
                process = psutil.Process(pid)
                cmd_line = process.cmdline()
                if not any("java" in arg.lower() for arg in cmd_line):
                    logger.warning(f"Process {pid} doesn't appear to be Java process")
                    await self._remove_pid_file(server_id, server_dir)
                    return False
            except Exception as e:
                logger.warning(f"Could not verify process {pid} command line: {e}")

            # Create a pseudo subprocess object for monitoring
            # Note: We can't fully recreate the original subprocess, but we can monitor the PID
            log_queue = asyncio.Queue(maxsize=self.log_queue_size)

            # Parse started_at time
            try:
                started_at = datetime.fromisoformat(pid_data["started_at"])
            except Exception:
                started_at = datetime.now()  # Fallback to current time

            # Extract RCON credentials if available
            rcon_port = pid_data.get("rcon_port")
            rcon_password = pid_data.get("rcon_password")

            server_process = ServerProcess(
                server_id=server_id,
                process=None,  # We'll set this to None since we can't recreate subprocess
                log_queue=log_queue,
                status=ServerStatus.running,  # Assume running since process exists
                started_at=started_at,
                pid=pid,
                server_directory=server_dir,  # Store correct directory path for monitoring
                rcon_port=rcon_port,  # Restore RCON configuration
                rcon_password=rcon_password,
            )

            self.processes[server_id] = server_process

            # Start monitoring task for the restored process and track it
            server_process.monitor_task = asyncio.create_task(
                self._monitor_restored_process(server_process)
            )

            logger.info(f"Restored server {server_id} process (PID: {pid}) from PID file")
            return True

        except Exception as e:
            logger.error(f"Failed to restore process for server {server_id}: {e}")
            await self._remove_pid_file(server_id, server_dir)
            return False

    async def _monitor_restored_process(self, server_process: ServerProcess):
        """Monitor a restored process that we don't have subprocess handle for"""
        try:
            server_id = server_process.server_id
            pid = server_process.pid

            logger.info(
                f"Starting monitoring for restored server {server_id} (PID: {pid})"
            )

            # Continuously check if process is still running
            while True:
                if not await self._is_process_running(pid):
                    logger.info(f"Restored server {server_id} process {pid} has stopped")
                    server_process.status = ServerStatus.stopped
                    self._notify_status_change(server_id, ServerStatus.stopped)

                    # Clean up
                    await self._cleanup_server_process(server_id)
                    break

                # Check every 5 seconds
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.debug(f"Restored process monitor cancelled for server {server_id}")
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(f"Error monitoring restored server {server_id}: {e}")
            server_process.status = ServerStatus.error
            self._notify_status_change(server_id, ServerStatus.error)
            await self._cleanup_server_process(server_id)

    async def discover_and_restore_processes(self) -> Dict[int, bool]:
        """Discover and restore all running server processes from PID files

        Returns:
            Dictionary mapping server_id to restoration success status
        """
        if not settings.AUTO_SYNC_ON_STARTUP:
            logger.info("Auto-sync on startup is disabled")
            return {}

        logger.info("Starting process discovery and restoration...")
        restoration_results = {}

        try:
            # Scan all server directories for PID files
            for server_dir in self.base_directory.iterdir():
                if not server_dir.is_dir():
                    continue

                # Try to extract server ID from directory name or PID file
                pid_file_path = server_dir / "server.pid"
                if not pid_file_path.exists():
                    continue

                try:
                    with open(pid_file_path, "r") as f:
                        pid_data = json.load(f)

                    server_id = pid_data.get("server_id")
                    if server_id is None:
                        logger.warning(f"No server_id in PID file: {pid_file_path}")
                        continue

                    # Skip if already managed
                    if server_id in self.processes:
                        logger.info(f"Server {server_id} already managed, skipping")
                        restoration_results[server_id] = True
                        continue

                    # Attempt restoration
                    success = await self._restore_process_from_pid(server_id, server_dir)
                    restoration_results[server_id] = success

                    if success:
                        logger.info(f"Successfully restored server {server_id}")
                        # Notify database of running status
                        self._notify_status_change(server_id, ServerStatus.running)
                    else:
                        logger.info(f"Failed to restore server {server_id}")

                except Exception as e:
                    logger.error(f"Error processing PID file {pid_file_path}: {e}")
                    continue

            logger.info(f"Process restoration completed. Results: {restoration_results}")
            return restoration_results

        except Exception as e:
            logger.error(f"Error during process discovery: {e}")
            return restoration_results

    def _notify_status_change(self, server_id: int, status: ServerStatus):
        """Notify about status changes to update database"""
        if self._status_update_callback:
            try:
                self._status_update_callback(server_id, status)
            except Exception as e:
                logger.error(
                    f"Failed to update database status for server {server_id}: {e}"
                )

    async def _diagnose_log_issues(self, server_id: int, server_dir: Path) -> str:
        """Diagnose potential log file issues for debugging"""
        try:
            log_file_path = server_dir / "server.log"
            error_file_path = server_dir / "server_error.log"

            diagnostics = []

            # Check log file
            if log_file_path.exists():
                stat = log_file_path.stat()
                diagnostics.append(
                    f"server.log: exists, size={stat.st_size}, readable={os.access(log_file_path, os.R_OK)}"
                )
            else:
                diagnostics.append("server.log: does not exist")

            # Check error file
            if error_file_path.exists():
                stat = error_file_path.stat()
                diagnostics.append(
                    f"server_error.log: exists, size={stat.st_size}, readable={os.access(error_file_path, os.R_OK)}"
                )

                # Read error file content if small enough
                if stat.st_size > 0 and stat.st_size < 1024:
                    try:
                        with open(
                            error_file_path, "r", encoding="utf-8", errors="ignore"
                        ) as f:
                            error_content = f.read().strip()
                        if error_content:
                            diagnostics.append(
                                f"server_error.log content: '{error_content[:200]}'"
                            )
                    except Exception as e:
                        diagnostics.append(f"server_error.log read error: {e}")
            else:
                diagnostics.append("server_error.log: does not exist")

            # Check directory permissions
            diagnostics.append(f"Directory writable: {os.access(server_dir, os.W_OK)}")

            return "; ".join(diagnostics)

        except Exception as e:
            return f"Diagnostic error: {e}"

    async def _monitor_daemon_process(self, server_process: ServerProcess):
        """Monitor a daemon process for status updates"""
        try:
            server_id = server_process.server_id
            pid = server_process.pid

            logger.info(f"Starting daemon monitoring for server {server_id} (PID: {pid})")

            # Wait for initial startup (check for 45 seconds to account for world generation)
            startup_timeout_seconds = 45
            startup_timeout_iterations = (
                startup_timeout_seconds * 2
            )  # 0.5s intervals = 90 iterations
            startup_detected = False

            logger.info(
                f"Monitoring daemon server {server_id} startup (timeout: {startup_timeout_seconds}s, checking every 0.5s)"
            )

            for i in range(startup_timeout_iterations):
                # Check if process is still running
                if not await self._is_process_running(pid):
                    logger.error(
                        f"Daemon server {server_id} process {pid} died during startup"
                    )
                    server_process.status = ServerStatus.error
                    self._notify_status_change(server_id, ServerStatus.error)
                    # Schedule cleanup without awaiting to avoid self-await issue
                    asyncio.create_task(self._cleanup_server_process(server_id))
                    return

                # Check log file for startup completion
                try:
                    server_dir = server_process.server_directory or (
                        self.base_directory / str(server_id)
                    )
                    log_file_path = server_dir / "server.log"

                    if i % 10 == 0:  # Log every 5 seconds (10 iterations at 0.5s)
                        file_exists = log_file_path.exists()
                        file_size = log_file_path.stat().st_size if file_exists else 0
                        elapsed_seconds = (i + 1) * 0.5
                        logger.info(
                            f"Checking startup for server {server_id}, {elapsed_seconds:.1f}s/{startup_timeout_seconds}s elapsed, "
                            f"log file: {log_file_path}, exists: {file_exists}, size: {file_size} bytes"
                        )

                    if log_file_path.exists() and log_file_path.stat().st_size > 0:
                        # Read log file to check for startup completion
                        try:
                            with open(
                                log_file_path, "r", encoding="utf-8", errors="ignore"
                            ) as f:
                                content = f.read()

                            # Enhanced diagnostic logging - show sample content more frequently
                            if (
                                i % 10 == 0 and content
                            ):  # Every 5 seconds, show sample content
                                # Show both beginning and end of log for better debugging
                                sample_start = content[:100].replace("\n", " ")
                                sample_end = (
                                    content[-100:].replace("\n", " ")
                                    if len(content) > 100
                                    else ""
                                )
                                elapsed_seconds = (i + 1) * 0.5
                                logger.info(
                                    f"Server {server_id} log sample at {elapsed_seconds:.1f}s ({len(content)} chars): "
                                    f"START: '{sample_start}' ... END: '{sample_end}'"
                                )

                            # Check for multiple startup completion patterns
                            startup_patterns = [
                                ("Done", "For help"),  # Classic pattern
                                ("Done", "Time elapsed"),  # Alternative pattern
                                ("Done", "seconds"),  # Generic time-based pattern
                                ("[Server thread/INFO]", "Done"),  # Modern format
                                ("Server started", ""),  # Alternative completion message
                                ("Ready to accept", "connections"),  # Network ready
                            ]

                            startup_detected_local = False
                            detected_pattern = None

                            # Debug: check each pattern individually
                            pattern_results = []
                            for pattern1, pattern2 in startup_patterns:
                                p1_found = pattern1 in content
                                p2_found = not pattern2 or pattern2 in content
                                pattern_results.append(
                                    f"{pattern1}:{p1_found}, {pattern2 or 'N/A'}:{p2_found}"
                                )

                                if p1_found and p2_found:
                                    startup_detected_local = True
                                    detected_pattern = (
                                        f"{pattern1}+{pattern2}" if pattern2 else pattern1
                                    )
                                    break

                            # Debug logging for pattern matching
                            if i % 10 == 0 and content:  # Every 5 seconds
                                logger.info(
                                    f"Server {server_id} pattern check at {(i+1)*0.5:.1f}s: {pattern_results[:2]}"
                                )

                            if startup_detected_local:
                                elapsed_seconds = (i + 1) * 0.5
                                logger.info(
                                    f"Daemon server {server_id} startup completed (detected pattern '{detected_pattern}' after {elapsed_seconds:.1f}s)"
                                )
                                server_process.status = ServerStatus.running
                                self._notify_status_change(
                                    server_id, ServerStatus.running
                                )
                                startup_detected = True
                                break

                        except Exception as read_error:
                            logger.warning(
                                f"Error reading log file for server {server_id}: {read_error}"
                            )
                            # Continue with the loop, file might not be ready yet
                    elif log_file_path.exists():
                        # File exists but is empty - this indicates a log redirection issue
                        if i % 10 == 0:  # Log every 5 seconds for empty files
                            # Check both log files for more diagnostic info
                            error_file_path = server_dir / "server_error.log"
                            error_size = (
                                error_file_path.stat().st_size
                                if error_file_path.exists()
                                else 0
                            )
                            elapsed_seconds = (i + 1) * 0.5

                            logger.warning(
                                f"Server {server_id} log redirection issue at {elapsed_seconds:.1f}s: server.log exists but empty, "
                                f"server_error.log size: {error_size} bytes. This suggests daemon stdout/stderr redirection failed."
                            )

                            # If error file has content, show it
                            if error_size > 0 and error_size < 500:
                                try:
                                    with open(
                                        error_file_path,
                                        "r",
                                        encoding="utf-8",
                                        errors="ignore",
                                    ) as f:
                                        error_content = f.read().strip()
                                    if error_content:
                                        logger.warning(
                                            f"Server {server_id} error output: {error_content}"
                                        )
                                except Exception:
                                    pass

                except Exception as e:
                    logger.warning(
                        f"Error checking startup status for daemon server {server_id}: {e}"
                    )

                # Check more frequently for faster detection (every 0.5 seconds)
                await asyncio.sleep(0.5)

            # If startup not detected after timeout, check if process is still running
            if not startup_detected:
                if await self._is_process_running(pid):
                    # Get diagnostic information about log files
                    server_dir = server_process.server_directory or (
                        self.base_directory / str(server_id)
                    )
                    diagnostic_info = await self._diagnose_log_issues(
                        server_id, server_dir
                    )

                    logger.warning(
                        f"Daemon server {server_id} startup completion not detected after {startup_timeout_seconds}s, "
                        f"but process is running - assuming started. Diagnostics: {diagnostic_info}"
                    )
                    server_process.status = ServerStatus.running
                    self._notify_status_change(server_id, ServerStatus.running)
                else:
                    logger.error(
                        f"Daemon server {server_id} process {pid} died during startup (timeout)"
                    )
                    server_process.status = ServerStatus.error
                    self._notify_status_change(server_id, ServerStatus.error)
                    # Schedule cleanup without awaiting to avoid self-await issue
                    asyncio.create_task(self._cleanup_server_process(server_id))
                    return

            # Continue monitoring for process termination
            while server_id in self.processes:
                if not await self._is_process_running(pid):
                    logger.info(f"Daemon server {server_id} process {pid} has stopped")
                    server_process.status = ServerStatus.stopped
                    self._notify_status_change(server_id, ServerStatus.stopped)
                    # Schedule cleanup without awaiting to avoid self-await issue
                    asyncio.create_task(self._cleanup_server_process(server_id))
                    break

                # Check every 5 seconds
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.debug(f"Daemon process monitor cancelled for server {server_id}")
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(
                f"Error monitoring daemon server {server_id}: {e}", exc_info=True
            )
            server_process.status = ServerStatus.error
            self._notify_status_change(server_id, ServerStatus.error)
            # Schedule cleanup without awaiting to avoid self-await issue
            asyncio.create_task(self._cleanup_server_process(server_id))

    async def _cleanup_server_process(self, server_id: int):
        """Clean up server process and associated resources"""
        try:
            if server_id in self.processes:
                server_process = self.processes[server_id]

                # Cancel background tasks with improved error handling
                tasks_to_cancel = []
                if server_process.log_task and not server_process.log_task.done():
                    tasks_to_cancel.append(server_process.log_task)
                if server_process.monitor_task and not server_process.monitor_task.done():
                    tasks_to_cancel.append(server_process.monitor_task)

                if tasks_to_cancel:
                    logger.debug(
                        f"Cancelling {len(tasks_to_cancel)} background tasks for server {server_id}"
                    )

                    # Cancel tasks individually to avoid recursion
                    for task in tasks_to_cancel:
                        try:
                            if not task.cancelled():
                                task.cancel()
                        except Exception as e:
                            logger.warning(
                                f"Error cancelling task for server {server_id}: {e}"
                            )

                    # Wait for cancellation with individual handling
                    for task in tasks_to_cancel:
                        try:
                            await asyncio.wait_for(task, timeout=1.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            # Expected for cancelled tasks
                            pass
                        except Exception as e:
                            logger.warning(f"Error waiting for task cancellation: {e}")

                    # Reset task references to None
                    server_process.log_task = None
                    server_process.monitor_task = None

                # Clear the log queue to free memory efficiently
                try:
                    queue_size = server_process.log_queue.qsize()
                    for _ in range(queue_size):
                        try:
                            server_process.log_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                except (AttributeError, TypeError):
                    # Handle mock objects in tests that don't have qsize()
                    # Fallback to while loop with safety limit
                    count = 0
                    while count < 1000:  # Safety limit to prevent infinite loops
                        try:
                            server_process.log_queue.get_nowait()
                            count += 1
                        except (asyncio.QueueEmpty, AttributeError, TypeError):
                            break

                # Remove PID file
                try:
                    server_dir = server_process.server_directory or (
                        self.base_directory / str(server_id)
                    )
                    await self._remove_pid_file(server_id, server_dir)
                except Exception as pid_error:
                    logger.warning(
                        f"Failed to remove PID file for server {server_id}: {pid_error}"
                    )

                # Remove from processes dict
                del self.processes[server_id]
                logger.debug(f"Cleaned up resources for server {server_id}")

        except Exception as e:
            # Use warning instead of error to reduce noise for expected cleanup issues
            logger.warning(
                f"Error during cleanup for server {server_id}: {type(e).__name__}: {e}"
            )

    async def _check_java_compatibility(
        self, minecraft_version: str
    ) -> tuple[bool, str, Optional[str]]:
        """Check Java availability and compatibility with Minecraft version"""
        try:
            # Get appropriate Java installation for Minecraft version
            java_version = await java_compatibility_service.get_java_for_minecraft(
                minecraft_version
            )

            if java_version is None:
                # Try to provide helpful error message
                installations = (
                    await java_compatibility_service.discover_java_installations()
                )
                if not installations:
                    return (
                        False,
                        (
                            "No Java installations found. "
                            "Please install OpenJDK and ensure it's accessible."
                        ),
                        None,
                    )
                else:
                    available_versions = list(installations.keys())
                    required_version = (
                        java_compatibility_service.get_required_java_version(
                            minecraft_version
                        )
                    )
                    return (
                        False,
                        (
                            f"Minecraft {minecraft_version} requires Java {required_version}, "
                            f"but only Java {available_versions} are available. "
                            f"Please install Java {required_version} or configure it in .env."
                        ),
                        None,
                    )

            logger.info(
                f"Selected Java {java_version.major_version} "
                f"({java_version.version_string}) at {java_version.executable_path}"
                + (f" [{java_version.vendor}]" if java_version.vendor else "")
            )

            # Validate compatibility with Minecraft version
            is_compatible, compatibility_message = (
                java_compatibility_service.validate_java_compatibility(
                    minecraft_version, java_version
                )
            )

            return is_compatible, compatibility_message, java_version.executable_path

        except Exception as e:
            error_message = f"Java compatibility check failed: {type(e).__name__}: {e}"
            logger.error(error_message, exc_info=True)
            return False, error_message, None

    async def _ensure_eula_accepted(self, server_dir: Path) -> bool:
        """Ensure EULA is accepted by creating eula.txt"""
        try:
            eula_path = server_dir / "eula.txt"
            if not eula_path.exists():
                logger.info(f"Creating EULA acceptance file: {eula_path}")
                with open(eula_path, "w") as f:
                    f.write("eula=true\n")
            else:
                # Check if EULA is already accepted
                with open(eula_path, "r") as f:
                    content = f.read()
                    if "eula=true" not in content:
                        logger.info(f"Updating EULA acceptance in: {eula_path}")
                        with open(eula_path, "w") as f:
                            f.write("eula=true\n")
            return True
        except Exception as e:
            logger.error(f"Failed to ensure EULA acceptance: {e}")
            return False

    def _generate_rcon_password(self) -> str:
        """Generate a secure RCON password"""
        return secrets.token_urlsafe(32)

    def _find_available_rcon_port(self, base_port: int = 25575) -> int:
        """Find an available RCON port starting from base_port"""
        for port in range(base_port, base_port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("localhost", port))
                    return port
            except OSError:
                continue
        raise RuntimeError("No available RCON ports found")

    async def _ensure_rcon_configured(
        self, server_dir: Path, server_id: int
    ) -> tuple[bool, int, str]:
        """Ensure RCON is configured in server.properties"""
        try:
            properties_path = server_dir / "server.properties"
            rcon_port = self._find_available_rcon_port()
            rcon_password = self._generate_rcon_password()

            # Read existing properties if file exists
            properties = {}
            if properties_path.exists():
                with open(properties_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            properties[key] = value

            # Update RCON settings
            properties.update(
                {
                    "enable-rcon": "true",
                    "rcon.port": str(rcon_port),
                    "rcon.password": rcon_password,
                    "broadcast-rcon-to-ops": "true",
                }
            )

            # Write updated properties back
            with open(properties_path, "w", encoding="utf-8") as f:
                f.write("#Minecraft server properties\n")
                f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
                for key, value in sorted(properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(f"Configured RCON for server {server_id}: port={rcon_port}")
            return True, rcon_port, rcon_password

        except Exception as e:
            logger.error(f"Failed to configure RCON for server {server_id}: {e}")
            return False, 0, ""

    async def _validate_server_files(self, server_dir: Path) -> tuple[bool, str]:
        """Validate that all required server files exist and are accessible"""
        try:
            # Check server.jar exists and is readable
            jar_path = server_dir / "server.jar"
            if not jar_path.exists():
                return False, f"Server JAR not found: {jar_path}"

            if not os.access(jar_path, os.R_OK):
                return False, f"Server JAR is not readable: {jar_path}"

            # Check directory permissions
            if not os.access(server_dir, os.W_OK):
                return False, f"Server directory is not writable: {server_dir}"

            return True, "All files validated successfully"

        except Exception as e:
            return False, f"File validation failed: {e}"

    async def _validate_port_availability(
        self, server: Server, db_session=None
    ) -> tuple[bool, str]:
        """Validate that the server's port is not already in use by another running server

        This method checks both:
        1. Database for servers using the same port and currently running/starting
        2. System-level port availability for external processes
        """
        try:
            # First check database for servers using the same port
            if db_session:
                from sqlalchemy import and_

                from app.servers.models import Server as ServerModel

                conflicting_server = (
                    db_session.query(ServerModel)
                    .filter(
                        and_(
                            ServerModel.port == server.port,
                            ServerModel.id != server.id,
                            ServerModel.is_deleted.is_(False),
                            ServerModel.status.in_(
                                [ServerStatus.running, ServerStatus.starting]
                            ),
                        )
                    )
                    .first()
                )

                if conflicting_server:
                    return (
                        False,
                        f"Port {server.port} is already in use by {conflicting_server.status.value} server '{conflicting_server.name}'. "
                        f"Stop the server to free up the port.",
                    )

            # Check if port is available at system level
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                result = sock.connect_ex(("localhost", server.port))
                if result == 0:
                    # Port is in use by some external process
                    return (
                        False,
                        f"Port {server.port} is already in use by another process. "
                        f"Please use a different port or stop the conflicting process.",
                    )

                return True, f"Port {server.port} is available"
            finally:
                sock.close()

        except Exception as e:
            return False, f"Port validation failed: {e}"

    async def start_server(self, server: Server, db_session=None) -> bool:
        """Start a Minecraft server with comprehensive pre-checks"""
        try:
            if server.id in self.processes:
                logger.warning(f"Server {server.id} is already running")
                return False

            server_dir = Path(server.directory_path)
            if not server_dir.exists():
                logger.error(f"Server directory not found: {server_dir}")
                return False

            # Pre-flight checks
            logger.info(f"Starting pre-flight checks for server {server.id}")

            # Check port availability
            port_available, port_message = await self._validate_port_availability(
                server, db_session
            )
            if not port_available:
                logger.error(
                    f"Port validation failed for server {server.id}: {port_message}"
                )
                return False
            logger.info(f"Port validation passed for server {server.id}: {port_message}")

            # Check Java compatibility with Minecraft version
            java_compatible, java_message, java_executable = (
                await self._check_java_compatibility(server.minecraft_version)
            )
            if not java_compatible:
                logger.error(
                    f"Java compatibility check failed for server {server.id}: {java_message}"
                )
                return False
            logger.info(
                f"Java compatibility verified for server {server.id}: {java_message}"
            )

            # Validate server files
            files_valid, validation_message = await self._validate_server_files(
                server_dir
            )
            if not files_valid:
                logger.error(
                    f"Server {server.id} file validation failed: {validation_message}"
                )
                return False
            logger.debug(f"Server {server.id} file validation: {validation_message}")

            # Ensure EULA is accepted
            if not await self._ensure_eula_accepted(server_dir):
                logger.error(f"Failed to ensure EULA acceptance for server {server.id}")
                return False

            # Configure RCON for real-time command support
            rcon_success, rcon_port, rcon_password = await self._ensure_rcon_configured(
                server_dir, server.id
            )
            if not rcon_success:
                logger.warning(
                    f"Failed to configure RCON for server {server.id}, continuing without real-time commands"
                )
                rcon_port, rcon_password = None, None

            # Prepare command with absolute paths
            jar_path = server_dir / "server.jar"
            abs_server_dir = server_dir.absolute()
            abs_jar_path = jar_path.absolute()

            # Use the selected Java executable for this Minecraft version
            cmd = [
                java_executable or "java",  # Fallback to system java if needed
                f"-Xmx{server.max_memory}M",
                f"-Xms{min(server.max_memory, 512)}M",
                "-jar",
                str(abs_jar_path),
                "nogui",
            ]

            logger.info(f"Starting server {server.id} in directory: {abs_server_dir}")
            logger.info(f"Command: {' '.join(cmd)}")
            logger.info(f"JAR path exists: {abs_jar_path.exists()}")
            logger.info(f"Directory writable: {os.access(abs_server_dir, os.W_OK)}")

            # Create truly detached daemon process
            try:
                # Prepare environment for daemon process
                env = dict(os.environ)
                env.update(
                    {
                        "TERM": "dumb",  # Prevent issues with terminal-specific features
                        "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true",  # Ensure headless mode
                        "PYTHONUNBUFFERED": "1",  # Disable Python output buffering
                        "_JAVA_OPTIONS": "-Djava.awt.headless=true -Dfile.encoding=UTF-8",
                    }
                )

                # Create daemon process using double-fork technique
                daemon_pid = await self._create_daemon_process(
                    cmd, str(abs_server_dir), env, server.id
                )

                # If primary daemon creation fails, try alternative method
                if not daemon_pid:
                    logger.warning(
                        f"Primary daemon creation failed for server {server.id}, trying alternative method"
                    )
                    daemon_pid = await self._create_daemon_process_alternative(
                        cmd, str(abs_server_dir), env, server.id
                    )

                if not daemon_pid:
                    logger.error(
                        f"All daemon creation methods failed for server {server.id}"
                    )
                    return False

            except Exception as e:
                logger.error(
                    f"Unexpected error creating daemon process for server {server.id}: {e}"
                )
                return False

            # Verify daemon process is running
            if not await self._is_process_running(daemon_pid):
                logger.error(
                    f"Daemon process {daemon_pid} is not running for server {server.id}"
                )
                return False

            # Additional verification - wait and check multiple times
            for i in range(3):  # Check 3 times over 300ms
                await asyncio.sleep(0.1)
                if not await self._is_process_running(daemon_pid):
                    logger.error(
                        f"Daemon process {daemon_pid} died within {(i+1)*100}ms for server {server.id}"
                    )
                    # Try to read any immediate error output from log files
                    try:
                        log_file_path = abs_server_dir / "server_error.log"
                        if log_file_path.exists():
                            with open(log_file_path, "r") as f:
                                error_content = f.read(1024)
                                if error_content.strip():
                                    logger.error(
                                        f"Server {server.id} immediate error: {error_content[:500]}"
                                    )
                    except Exception:
                        pass
                    return False

            logger.info(
                f"Daemon process verification successful for server {server.id} - PID: {daemon_pid}"
            )

            # Write PID file for process persistence
            # Create a mock process object for PID file writing
            class DaemonProcess:
                def __init__(self, pid):
                    self.pid = pid

            mock_process = DaemonProcess(daemon_pid)
            pid_file_success = await self._write_pid_file(
                server.id,
                server_dir,
                mock_process,
                server.port,
                cmd,
                rcon_port,
                rcon_password,
            )
            if not pid_file_success:
                logger.warning(
                    f"Failed to create PID file for server {server.id}, continuing anyway"
                )

            # Create server process tracking (without process object for daemon)
            log_queue = asyncio.Queue(maxsize=self.log_queue_size)
            server_process = ServerProcess(
                server_id=server.id,
                process=None,  # No process object for daemon processes
                log_queue=log_queue,
                status=ServerStatus.starting,
                started_at=datetime.now(),
                pid=daemon_pid,
                server_directory=server_dir,  # Store correct directory path for monitoring
                rcon_port=rcon_port,  # Store RCON configuration
                rcon_password=rcon_password,
            )

            self.processes[server.id] = server_process

            # Start background tasks and track them for proper cleanup
            server_process.log_task = asyncio.create_task(
                self._read_server_logs(server_process)
            )

            # For daemon processes, use direct monitoring instead of subprocess waiting
            if server_process.process is None:
                server_process.monitor_task = asyncio.create_task(
                    self._monitor_daemon_process(server_process)
                )
            else:
                server_process.monitor_task = asyncio.create_task(
                    self._monitor_server(server_process)
                )

            # Notify database of status change
            self._notify_status_change(server.id, ServerStatus.starting)

            logger.info(
                f"Successfully started daemon server {server.id} with PID {daemon_pid}"
            )
            return True

        except Exception as e:
            logger.error(
                f"Critical error starting server {server.id}: {e}", exc_info=True
            )
            # Cleanup if process was partially created
            if server.id in self.processes:
                del self.processes[server.id]
            return False

    async def stop_server(self, server_id: int, force: bool = False) -> bool:
        """Stop a Minecraft server (daemon or regular process)"""
        try:
            if server_id not in self.processes:
                logger.warning(f"Server {server_id} is not running")
                return False

            server_process = self.processes[server_id]
            server_process.status = ServerStatus.stopping

            # Notify database of status change
            self._notify_status_change(server_id, ServerStatus.stopping)

            # Handle daemon processes (no process object)
            if server_process.process is None:
                return await self._stop_daemon_process(server_id, server_process, force)

            # Handle regular processes (with process object)
            # Check if process is already terminated
            if server_process.process.returncode is not None:
                logger.info(f"Server {server_id} process already terminated")
                # Clean up immediately if process is already dead
                await self._cleanup_server_process(server_id)
                self._notify_status_change(server_id, ServerStatus.stopped)
                return True

            if not force:
                # Send graceful stop command
                try:
                    # Check if stdin is available and process is still running
                    if (
                        server_process.process.stdin
                        and not server_process.process.stdin.is_closing()
                    ):
                        server_process.process.stdin.write(b"stop\n")
                        await server_process.process.stdin.drain()

                        # Wait for graceful shutdown with shorter timeout
                        await asyncio.wait_for(
                            server_process.process.wait(), timeout=15.0
                        )
                    else:
                        logger.warning(
                            f"Server {server_id} stdin not available, forcing termination"
                        )
                        force = True
                except (asyncio.TimeoutError, OSError, BrokenPipeError) as e:
                    logger.warning(
                        f"Server {server_id} graceful stop failed ({type(e).__name__}), forcing termination"
                    )
                    force = True

            if force:
                # Force termination
                try:
                    if (
                        server_process.process.returncode is None
                    ):  # Only terminate if still running
                        server_process.process.terminate()
                        try:
                            await asyncio.wait_for(
                                server_process.process.wait(), timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"Server {server_id} did not respond to SIGTERM, sending SIGKILL"
                            )
                            server_process.process.kill()
                            await server_process.process.wait()
                except (ProcessLookupError, OSError) as e:
                    logger.info(f"Server {server_id} process already terminated: {e}")

            # Clean up
            await self._cleanup_server_process(server_id)

            # Notify database of final stopped status
            self._notify_status_change(server_id, ServerStatus.stopped)

            logger.info(f"Successfully stopped server {server_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop server {server_id}: {e}")
            # Ensure cleanup even if there was an error
            try:
                await self._cleanup_server_process(server_id)
                self._notify_status_change(server_id, ServerStatus.stopped)
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup server {server_id}: {cleanup_error}")
            return False

    async def send_command(self, server_id: int, command: str) -> bool:
        """Send a command to a running server using RCON"""
        try:
            if server_id not in self.processes:
                return False

            server_process = self.processes[server_id]

            # Try RCON first for all servers (daemon and regular)
            if server_process.rcon_port and server_process.rcon_password:
                return await self._send_command_via_rcon(
                    server_id, server_process, command
                )

            # Fallback to stdin for regular processes (backward compatibility)
            if server_process.process and server_process.process.stdin:
                logger.debug(
                    f"Using stdin fallback for server {server_id} (RCON not available)"
                )
                command_bytes = f"{command}\n".encode()
                server_process.process.stdin.write(command_bytes)
                await server_process.process.stdin.drain()
                return True

            # No command mechanism available
            logger.warning(f"No command mechanism available for server {server_id}")
            return False

        except Exception as e:
            logger.error(f"Failed to send command to server {server_id}: {e}")
            return False

    async def _send_command_via_rcon(
        self, server_id: int, server_process: ServerProcess, command: str
    ) -> bool:
        """Send a command to a server using RCON"""
        try:
            # Check if RCON credentials are available
            if not server_process.rcon_port or not server_process.rcon_password:
                logger.warning(
                    f"Cannot send command to server {server_id}: "
                    f"RCON credentials not available (port: {server_process.rcon_port}, "
                    f"password: {'set' if server_process.rcon_password else 'not set'})"
                )
                return False

            # Create RCON client and connect
            rcon_client = MinecraftRCONClient()

            try:
                # Connect to RCON server
                connected = await rcon_client.connect(
                    host="127.0.0.1",
                    port=server_process.rcon_port,
                    password=server_process.rcon_password,
                    timeout=5.0,
                )

                if not connected:
                    logger.error(f"Failed to connect to RCON for server {server_id}")
                    return False

                # Send command
                response = await rcon_client.send_command(command)

                if response is not None:
                    logger.info(
                        f"Command '{command}' sent to server {server_id} via RCON. "
                        f"Response: {response[:100]}{'...' if len(response) > 100 else ''}"
                    )
                    return True
                else:
                    logger.error(
                        f"Failed to send command '{command}' to server {server_id} via RCON"
                    )
                    return False

            finally:
                await rcon_client.disconnect()

        except Exception as e:
            logger.error(f"Failed to send command to server {server_id} via RCON: {e}")
            return False

    def get_server_status(self, server_id: int) -> Optional[ServerStatus]:
        """Get the current status of a server"""
        if server_id in self.processes:
            return self.processes[server_id].status
        return ServerStatus.stopped

    def get_server_info(self, server_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information about a running server"""
        if server_id not in self.processes:
            return None

        server_process = self.processes[server_id]
        return {
            "server_id": server_id,
            "pid": server_process.pid,
            "status": server_process.status.value,
            "started_at": server_process.started_at.isoformat(),
            "uptime_seconds": (
                datetime.now() - server_process.started_at
            ).total_seconds(),
        }

    async def get_server_logs(self, server_id: int, lines: int = 100) -> List[str]:
        """Get recent server logs"""
        if server_id not in self.processes:
            return []

        server_process = self.processes[server_id]
        logs = []

        # Get logs from queue (non-blocking)
        for _ in range(min(lines, server_process.log_queue.qsize())):
            try:
                log_line = server_process.log_queue.get_nowait()
                logs.append(log_line)
            except asyncio.QueueEmpty:
                break

        return logs

    async def stream_server_logs(self, server_id: int) -> AsyncGenerator[str, None]:
        """Stream server logs in real-time"""
        if server_id not in self.processes:
            return

        server_process = self.processes[server_id]

        while server_id in self.processes:
            try:
                log_line = await asyncio.wait_for(
                    server_process.log_queue.get(), timeout=1.0
                )
                yield log_line
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error streaming logs for server {server_id}: {e}")
                break

    async def _read_server_logs(self, server_process: ServerProcess):
        """Read server logs from file and put them in the queue"""
        try:
            server_dir = server_process.server_directory or (
                self.base_directory / str(server_process.server_id)
            )
            log_file_path = server_dir / "server.log"

            # Track last read position to avoid re-reading
            last_position = 0

            while server_process.server_id in self.processes:
                try:
                    # Check if log file exists
                    if not log_file_path.exists():
                        await asyncio.sleep(0.5)
                        continue

                    # Read new content from file
                    with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(last_position)
                        new_content = f.read()
                        last_position = f.tell()

                    if new_content:
                        lines = new_content.strip().split("\n")
                        for line in lines:
                            if line.strip():  # Skip empty lines
                                # Add timestamp
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                formatted_line = f"[{timestamp}] {line.strip()}"

                                # Put in queue (drop old logs if queue is full)
                                try:
                                    server_process.log_queue.put_nowait(formatted_line)
                                except asyncio.QueueFull:
                                    # Remove oldest log and add new one
                                    try:
                                        server_process.log_queue.get_nowait()
                                        server_process.log_queue.put_nowait(
                                            formatted_line
                                        )
                                    except asyncio.QueueEmpty:
                                        pass

                                # Note: Status updates are handled by _monitor_daemon_process
                                # to avoid conflicts and ensure single source of truth

                    # Sleep before next read to avoid excessive CPU usage
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.warning(
                        f"Error reading log file for server {server_process.server_id}: {e}"
                    )
                    await asyncio.sleep(1.0)  # Wait longer on error

        except asyncio.CancelledError:
            logger.debug(
                f"Log reading task cancelled for server {server_process.server_id}"
            )
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(f"Error reading logs for server {server_process.server_id}: {e}")

    async def _monitor_server(self, server_process: ServerProcess):
        """Monitor server process and update status"""
        try:
            if server_process.process is None:
                # This is a restored process - monitor using PID
                await self._monitor_restored_process(server_process)
                return

            # Check if process failed immediately (within 5 seconds)
            try:
                await asyncio.wait_for(server_process.process.wait(), timeout=5.0)

                # Process ended immediately - this is likely an error
                return_code = server_process.process.returncode
                logger.error(
                    f"Server {server_process.server_id} failed to start - exited immediately with code {return_code}"
                )

                server_process.status = ServerStatus.error
                self._notify_status_change(server_process.server_id, ServerStatus.error)

                # Clean up
                await self._cleanup_server_process(server_process.server_id)
                return

            except asyncio.TimeoutError:
                # Process is still running after 5 seconds - this is good
                logger.info(
                    f"Server {server_process.server_id} process is stable after 5 seconds - marking as running"
                )
                server_process.status = ServerStatus.running
                self._notify_status_change(server_process.server_id, ServerStatus.running)

            # For detached processes, we can't reliably wait() so we check periodically
            while server_process.server_id in self.processes:
                try:
                    # Check if process is still running
                    if server_process.pid and await self._is_process_running(
                        server_process.pid
                    ):
                        await asyncio.sleep(5.0)  # Check every 5 seconds
                        continue
                    else:
                        # Process has ended
                        logger.info(
                            f"Server {server_process.server_id} process has ended"
                        )
                        self._notify_status_change(
                            server_process.server_id, ServerStatus.stopped
                        )
                        break
                except Exception as e:
                    logger.warning(
                        f"Error checking process status for server {server_process.server_id}: {e}"
                    )
                    await asyncio.sleep(5.0)

            # Clean up if still in processes dict
            await self._cleanup_server_process(server_process.server_id)

        except asyncio.CancelledError:
            logger.debug(f"Monitor task cancelled for server {server_process.server_id}")
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(f"Error monitoring server {server_process.server_id}: {e}")
            server_process.status = ServerStatus.error
            # Notify database of error status
            self._notify_status_change(server_process.server_id, ServerStatus.error)

            # Clean up
            await self._cleanup_server_process(server_process.server_id)

    async def shutdown_all(self, force_stop: bool = None):
        """Shutdown all running servers based on configuration

        Args:
            force_stop: Override setting to force stop all servers (for testing)
        """
        # Determine if we should stop servers based on configuration
        should_stop_servers = (
            force_stop
            if force_stop is not None
            else not settings.KEEP_SERVERS_ON_SHUTDOWN
        )

        if should_stop_servers:
            logger.info("Shutting down all servers...")

            # Create stop tasks for all servers
            stop_tasks = []
            for server_id in list(self.processes.keys()):
                task = asyncio.create_task(self.stop_server(server_id))
                stop_tasks.append(task)

            # Wait for all servers to stop
            if stop_tasks:
                await asyncio.gather(*stop_tasks, return_exceptions=True)

            logger.info("All servers shut down")
        else:
            logger.info(
                "Keeping servers running on shutdown (KEEP_SERVERS_ON_SHUTDOWN=True)"
            )

            # Cancel background tasks but keep processes running
            # The PID files will remain so servers can be restored on next startup
            server_ids = list(self.processes.keys())
            cleanup_tasks = []

            for server_id in server_ids:
                try:
                    server_process = self.processes[server_id]

                    # Cancel background tasks to allow clean shutdown
                    tasks_to_cancel = []
                    if server_process.log_task and not server_process.log_task.done():
                        tasks_to_cancel.append(server_process.log_task)
                    if (
                        server_process.monitor_task
                        and not server_process.monitor_task.done()
                    ):
                        tasks_to_cancel.append(server_process.monitor_task)

                    if tasks_to_cancel:
                        logger.debug(
                            f"Cancelling background tasks for server {server_id}"
                        )
                        for task in tasks_to_cancel:
                            task.cancel()
                        cleanup_tasks.extend(tasks_to_cancel)

                    # Clear log queue to free memory
                    try:
                        while not server_process.log_queue.empty():
                            server_process.log_queue.get_nowait()
                    except (asyncio.QueueEmpty, AttributeError):
                        pass

                    # Remove from processes dict but keep PID file and don't kill process
                    del self.processes[server_id]
                    logger.info(
                        f"Detached from server {server_id} process (PID: {server_process.pid})"
                    )

                except Exception as e:
                    logger.error(f"Error detaching from server {server_id}: {e}")

            # Wait for all background tasks to be cancelled
            if cleanup_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*cleanup_tasks, return_exceptions=True),
                        timeout=5.0,
                    )
                    logger.info("All background tasks cancelled successfully")
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for background tasks to cancel")

            logger.info(f"Detached from {len(server_ids)} running servers")

    def list_running_servers(self) -> List[int]:
        """Get list of currently running server IDs"""
        return list(self.processes.keys())


class MinecraftRCONClient:
    """RCON client for sending commands to Minecraft servers"""

    def __init__(self):
        self.socket = None
        self.request_id = 0

    async def connect(
        self, host: str, port: int, password: str, timeout: float = 5.0
    ) -> bool:
        """Connect to RCON server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(timeout)
            await asyncio.get_event_loop().run_in_executor(
                None, self.socket.connect, (host, port)
            )

            # Send authentication packet
            auth_success = await self._authenticate(password)
            if not auth_success:
                await self.disconnect()
                return False

            logger.debug(f"RCON connected to {host}:{port}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to RCON {host}:{port}: {e}")
            await self.disconnect()
            return False

    async def _authenticate(self, password: str) -> bool:
        """Authenticate with RCON server"""
        try:
            self.request_id += 1
            packet = self._create_packet(self.request_id, 3, password)  # Type 3 = LOGIN
            await self._send_packet(packet)

            response = await self._receive_packet()

            if response:
                response_id, response_type, response_payload = response

                # Check for authentication failure (response ID -1)
                if response_id == -1:
                    logger.error("RCON authentication failed: Invalid password")
                    return False

                # Check for successful authentication (matching request ID)
                if response_id == self.request_id:
                    logger.debug("RCON authentication successful")
                    return True

                logger.error(
                    f"RCON authentication failed: Unexpected response ID {response_id} (expected {self.request_id})"
                )
                return False
            else:
                logger.error("RCON authentication failed: No response received")
                return False

        except Exception as e:
            logger.error(f"RCON authentication failed: {e}")
            return False

    async def send_command(self, command: str) -> Optional[str]:
        """Send a command and return the response"""
        try:
            if not self.socket:
                return None

            self.request_id += 1
            packet = self._create_packet(self.request_id, 2, command)  # Type 2 = COMMAND
            await self._send_packet(packet)

            response = await self._receive_packet()
            if response and response[0] == self.request_id:
                return response[2]  # Return payload
            return None

        except Exception as e:
            logger.error(f"Failed to send RCON command '{command}': {e}")
            return None

    def _create_packet(self, request_id: int, packet_type: int, payload: str) -> bytes:
        """Create RCON packet"""
        payload_bytes = payload.encode("utf-8") + b"\x00\x00"
        # Size = request_id (4) + packet_type (4) + payload_bytes
        packet_size = 4 + 4 + len(payload_bytes)

        packet = struct.pack("<i", packet_size)  # Size (excluding size field itself)
        packet += struct.pack("<i", request_id)
        packet += struct.pack("<i", packet_type)
        packet += payload_bytes

        logger.debug(
            f"Created RCON packet: size={packet_size}, id={request_id}, type={packet_type}, payload_len={len(payload)}"
        )
        logger.debug(f"Payload bytes length: {len(payload_bytes)}")
        logger.debug(f"Packet bytes: {packet.hex()}")

        return packet

    async def _send_packet(self, packet: bytes):
        """Send packet to RCON server"""
        await asyncio.get_event_loop().run_in_executor(None, self.socket.sendall, packet)

    async def _receive_packet(self) -> Optional[tuple]:
        """Receive packet from RCON server"""
        try:
            # Read packet size
            logger.debug("Attempting to read RCON packet size...")
            size_data = await asyncio.get_event_loop().run_in_executor(
                None, self.socket.recv, 4
            )
            logger.debug(f"Received size data: {size_data} (length: {len(size_data)})")

            if len(size_data) != 4:
                logger.error(f"Invalid size data length: {len(size_data)} (expected 4)")
                return None

            size = struct.unpack("<i", size_data)[0]
            logger.debug(f"Packet size: {size}")

            if size <= 0 or size > 4096:  # Sanity check
                logger.error(f"Invalid packet size: {size}")
                return None

            # Read packet data
            logger.debug(f"Attempting to read {size} bytes of packet data...")
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.socket.recv, size
            )
            logger.debug(f"Received packet data: {data} (length: {len(data)})")

            if len(data) != size:
                logger.error(
                    f"Incomplete packet data: {len(data)} bytes (expected {size})"
                )
                return None

            request_id = struct.unpack("<i", data[0:4])[0]
            packet_type = struct.unpack("<i", data[4:8])[0]
            payload = data[8:-2].decode("utf-8")  # Remove null terminators

            logger.debug(
                f"Parsed packet: id={request_id}, type={packet_type}, payload='{payload}'"
            )

            return (request_id, packet_type, payload)

        except Exception as e:
            logger.error(f"Failed to receive RCON packet: {e}")
            import traceback

            logger.debug(f"Exception traceback: {traceback.format_exc()}")
            return None

    async def disconnect(self):
        """Disconnect from RCON server"""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None


# Global server manager instance
minecraft_server_manager = MinecraftServerManager()
