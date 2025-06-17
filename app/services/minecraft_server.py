import asyncio
import json
import logging
import os
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

    async def _write_pid_file(
        self,
        server_id: int,
        server_dir: Path,
        process: asyncio.subprocess.Process,
        port: int,
        command: List[str],
    ) -> bool:
        """Write PID file with process metadata"""
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

            server_process = ServerProcess(
                server_id=server_id,
                process=None,  # We'll set this to None since we can't recreate subprocess
                log_queue=log_queue,
                status=ServerStatus.running,  # Assume running since process exists
                started_at=started_at,
                pid=pid,
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

    async def _cleanup_server_process(self, server_id: int):
        """Clean up server process and associated resources"""
        try:
            if server_id in self.processes:
                server_process = self.processes[server_id]

                # Cancel background tasks first
                tasks_to_cancel = []
                if server_process.log_task and not server_process.log_task.done():
                    tasks_to_cancel.append(server_process.log_task)
                if server_process.monitor_task and not server_process.monitor_task.done():
                    tasks_to_cancel.append(server_process.monitor_task)

                if tasks_to_cancel:
                    logger.debug(
                        f"Cancelling {len(tasks_to_cancel)} background tasks for server {server_id}"
                    )
                    for task in tasks_to_cancel:
                        task.cancel()

                    # Wait for tasks to be cancelled (with timeout)
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                            timeout=2.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Timeout waiting for tasks to cancel for server {server_id}"
                        )

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
                    server_dir = self.base_directory / str(server_id)
                    await self._remove_pid_file(server_id, server_dir)
                except Exception as pid_error:
                    logger.warning(
                        f"Failed to remove PID file for server {server_id}: {pid_error}"
                    )

                # Remove from processes dict
                del self.processes[server_id]
                logger.debug(f"Cleaned up resources for server {server_id}")

        except Exception as e:
            logger.error(
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

            # Create process with detailed error handling and proper detachment
            try:
                # Prepare environment for detached process
                env = dict(os.environ)
                env.update(
                    {
                        "TERM": "dumb",  # Prevent issues with terminal-specific features
                        "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true",  # Ensure headless mode
                    }
                )

                # Create truly detached process by redirecting to files
                # This removes pipe dependencies that prevent true detachment
                log_file_path = abs_server_dir / "server.log"
                error_file_path = abs_server_dir / "server_error.log"

                # Ensure log files exist with proper permissions
                log_file_path.touch(exist_ok=True)
                error_file_path.touch(exist_ok=True)

                # Open files for subprocess output redirection
                log_file = open(log_file_path, "a", encoding="utf-8", buffering=1)
                error_file = open(error_file_path, "a", encoding="utf-8", buffering=1)

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(abs_server_dir),
                    stdout=log_file,
                    stderr=error_file,
                    stdin=None,  # No stdin connection
                    env=env,
                    start_new_session=True,  # Create new process group and session
                )

                # Close file handles after process creation
                log_file.close()
                error_file.close()
            except OSError as e:
                logger.error(f"Failed to create subprocess for server {server.id}: {e}")
                return False
            except Exception as e:
                logger.error(
                    f"Unexpected error creating subprocess for server {server.id}: {e}"
                )
                return False

            # Verify process was created successfully
            if process is None:
                logger.error(f"Process creation returned None for server {server.id}")
                return False

            # Check if process exited immediately
            if process.returncode is not None:
                logger.error(
                    f"Process exited immediately with code {process.returncode} for server {server.id}"
                )
                return False

            # Additional verification - wait and check multiple times
            for i in range(3):  # Check 3 times over 300ms
                await asyncio.sleep(0.1)
                if process.returncode is not None:
                    logger.error(
                        f"Process exited within {(i+1)*100}ms with code {process.returncode} for server {server.id}"
                    )
                    # Try to read any immediate error output
                    try:
                        if process.stdout:
                            error_data = await asyncio.wait_for(
                                process.stdout.read(1024), timeout=0.1
                            )
                            if error_data:
                                logger.error(
                                    f"Server {server.id} immediate error: {error_data.decode()[:500]}"
                                )
                    except Exception:
                        pass
                    return False

            logger.info(
                f"Process verification successful for server {server.id} - PID: {process.pid}"
            )

            # Write PID file for process persistence
            pid_file_success = await self._write_pid_file(
                server.id, server_dir, process, server.port, cmd
            )
            if not pid_file_success:
                logger.warning(
                    f"Failed to create PID file for server {server.id}, continuing anyway"
                )

            # Create server process tracking
            log_queue = asyncio.Queue(maxsize=self.log_queue_size)
            server_process = ServerProcess(
                server_id=server.id,
                process=process,
                log_queue=log_queue,
                status=ServerStatus.starting,
                started_at=datetime.now(),
                pid=process.pid,
            )

            self.processes[server.id] = server_process

            # Start background tasks and track them for proper cleanup
            server_process.log_task = asyncio.create_task(
                self._read_server_logs(server_process)
            )
            server_process.monitor_task = asyncio.create_task(
                self._monitor_server(server_process)
            )

            # Notify database of status change
            self._notify_status_change(server.id, ServerStatus.starting)

            logger.info(f"Successfully started server {server.id} with PID {process.pid}")
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
        """Stop a Minecraft server"""
        try:
            if server_id not in self.processes:
                logger.warning(f"Server {server_id} is not running")
                return False

            server_process = self.processes[server_id]
            server_process.status = ServerStatus.stopping

            # Notify database of status change
            self._notify_status_change(server_id, ServerStatus.stopping)

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
        """Send a command to a running server"""
        try:
            if server_id not in self.processes:
                return False

            server_process = self.processes[server_id]
            if server_process.process.stdin:
                command_bytes = f"{command}\n".encode()
                server_process.process.stdin.write(command_bytes)
                await server_process.process.stdin.drain()
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to send command to server {server_id}: {e}")
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
            server_dir = self.base_directory / str(server_process.server_id)
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

                                # Check for server ready status
                                if "Done" in line and "For help" in line:
                                    server_process.status = ServerStatus.running
                                    # Notify database of running status
                                    self._notify_status_change(
                                        server_process.server_id, ServerStatus.running
                                    )
                                    logger.info(
                                        f"Server {server_process.server_id} is now running"
                                    )

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


# Global server manager instance
minecraft_server_manager = MinecraftServerManager()
