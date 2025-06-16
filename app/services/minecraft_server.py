import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

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

            # Create process with detailed error handling
            # Note: Using stdin=None can help with some processes that don't expect stdin interaction
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(abs_server_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.PIPE,
                    env=dict(os.environ, TERM="xterm"),  # Set terminal environment
                )
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

            # Start background tasks
            asyncio.create_task(self._read_server_logs(server_process))
            asyncio.create_task(self._monitor_server(server_process))

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
        """Read server logs and put them in the queue"""
        try:
            async for line in server_process.process.stdout:
                log_line = line.decode().strip()

                # Add timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                formatted_line = f"[{timestamp}] {log_line}"

                # Put in queue (drop old logs if queue is full)
                try:
                    server_process.log_queue.put_nowait(formatted_line)
                except asyncio.QueueFull:
                    # Remove oldest log and add new one
                    try:
                        server_process.log_queue.get_nowait()
                        server_process.log_queue.put_nowait(formatted_line)
                    except asyncio.QueueEmpty:
                        pass

                # Check for server ready status
                if "Done" in log_line and "For help" in log_line:
                    server_process.status = ServerStatus.running
                    # Notify database of running status
                    self._notify_status_change(
                        server_process.server_id, ServerStatus.running
                    )
                    logger.info(f"Server {server_process.server_id} is now running")

        except Exception as e:
            logger.error(f"Error reading logs for server {server_process.server_id}: {e}")

    async def _monitor_server(self, server_process: ServerProcess):
        """Monitor server process and update status"""
        try:
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

            # Continue monitoring for normal process termination
            await server_process.process.wait()

            # Process has ended normally
            return_code = server_process.process.returncode

            if return_code == 0:
                logger.info(f"Server {server_process.server_id} stopped normally")
                # Notify database of stopped status
                self._notify_status_change(server_process.server_id, ServerStatus.stopped)
            else:
                logger.warning(
                    f"Server {server_process.server_id} crashed with code {return_code}"
                )
                server_process.status = ServerStatus.error
                # Notify database of error status
                self._notify_status_change(server_process.server_id, ServerStatus.error)

            # Clean up if still in processes dict
            await self._cleanup_server_process(server_process.server_id)

        except Exception as e:
            logger.error(f"Error monitoring server {server_process.server_id}: {e}")
            server_process.status = ServerStatus.error
            # Notify database of error status
            self._notify_status_change(server_process.server_id, ServerStatus.error)

            # Clean up
            await self._cleanup_server_process(server_process.server_id)

    async def shutdown_all(self):
        """Shutdown all running servers"""
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

    def list_running_servers(self) -> List[int]:
        """Get list of currently running server IDs"""
        return list(self.processes.keys())


# Global server manager instance
minecraft_server_manager = MinecraftServerManager()
