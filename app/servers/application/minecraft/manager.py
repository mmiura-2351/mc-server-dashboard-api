"""Composed :class:`MinecraftServerManager` and module-level singleton.

Combines the focused mixins (PID files, daemon process lifecycle,
preflight, monitoring) and adds the public manager surface
(``start_server``, ``stop_server``, ``send_command``, log/info accessors,
``shutdown_all``).
"""

import asyncio
import inspect
import os
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

from app.core.config import settings
from app.servers.application.minecraft._compat import logger
from app.servers.application.minecraft.daemon_process import DaemonProcessMixin
from app.servers.application.minecraft.monitoring import MonitoringMixin
from app.servers.application.minecraft.pid_file import PidFileMixin
from app.servers.application.minecraft.preflight import PreflightMixin
from app.servers.application.minecraft.rcon_client import MinecraftRCONClient
from app.servers.application.minecraft.server_process import ServerProcess
from app.servers.domain.entities import ServerEntity
from app.servers.domain.ports import ServerRepository
from app.servers.models import ServerStatus


class MinecraftServerManager(
    DaemonProcessMixin, PidFileMixin, PreflightMixin, MonitoringMixin
):
    """Manages Minecraft server processes using asyncio"""

    def __init__(
        self,
        log_queue_size: Optional[int] = None,
    ):
        self.processes: Dict[int, ServerProcess] = {}
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)
        # Callback for database status updates. The callback may be either a
        # plain sync function (legacy / test fixtures) or an async function
        # returning ``bool``; `_notify_status_change` awaits the awaitable
        # form so callers see the bool result and ordering is preserved
        # across consecutive status changes (Issue #280).
        self._status_update_callback: Optional[
            Callable[
                [int, ServerStatus],
                Union[Awaitable[Optional[bool]], Optional[bool]],
            ]
        ] = None
        # Configurable log queue size to prevent memory leaks
        self.log_queue_size = log_queue_size or settings.SERVER_LOG_QUEUE_SIZE
        self.java_check_timeout = settings.JAVA_CHECK_TIMEOUT
        # The port-conflict check inside ``_validate_port_availability``
        # consumes a ``ServerRepository`` passed explicitly by the caller
        # (#272, #285) — no framework-typed factories remain on this class.

    def set_status_update_callback(
        self,
        callback: Callable[
            [int, ServerStatus],
            Union[Awaitable[Optional[bool]], Optional[bool]],
        ],
    ) -> None:
        """Set callback function to update database when server status changes.

        The callback may be sync or async. Sync callbacks are invoked
        directly; async (coroutine) callbacks are awaited inside
        `_notify_status_change`, so consecutive status changes from the same
        async caller are ordered (Issue #280).
        """
        self._status_update_callback = callback

    async def _notify_status_change(self, server_id: int, status: ServerStatus) -> bool:
        """Notify about status changes to update the database.

        Returns ``True`` if the registered callback reported success (or
        returned ``None``/no value, treated as success for backward
        compatibility with sync recorders that don't return anything).
        Returns ``False`` if no callback is registered, the callback raised
        an exception, or the callback explicitly returned ``False``.

        Issue #280: this used to be a sync method that swallowed the bool
        result, leaving daemons unable to react to DB update failures and
        racing consecutive status changes. It is now awaited at every
        callsite (each of which already runs inside an ``async def``), so
        the bool propagates to callers and ordering is preserved within
        each task.
        """
        callback = self._status_update_callback
        if callback is None:
            return False
        try:
            result = callback(server_id, status)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            logger.error(f"Failed to update database status for server {server_id}: {e}")
            return False
        # Sync recorders / test fixtures often return ``None``; treat that
        # as success so we don't regress legacy test expectations. Only an
        # explicit ``False`` is treated as failure.
        if result is None:
            return True
        return bool(result)

    async def start_server(
        self,
        server: ServerEntity,
        server_repository: Optional[ServerRepository] = None,
    ) -> bool:
        """Start a Minecraft server with comprehensive pre-checks.

        ``server`` is the frozen ``ServerEntity`` returned by the
        servers ``ServerRepository`` (or an authorization check, which
        in turn calls the repository). ``server_repository`` is the
        same Port handle — passed in so the pre-flight sync can flush a
        manually-edited ``server.properties`` port back to the database
        without touching SQLAlchemy directly (#272). When omitted (e.g.
        ad-hoc test instantiation) the sync falls back to writing the
        in-memory entity's port out to ``server.properties``.
        """
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

            # FIRST: Perform bidirectional sync between database and server.properties
            # This must happen BEFORE port validation so manual file edits are detected.
            # The sync may flush a manually-edited port back to the DB and return a
            # fresh ``ServerEntity`` carrying that new port — we rebind ``server`` to
            # it so all downstream checks (port validation, command line construction,
            # PID file write) observe the post-sync value.
            logger.info(f"Performing sync check for server {server.id}")
            sync_ok, server = await self._perform_bidirectional_sync(
                server, server_dir, server_repository
            )
            if not sync_ok:
                logger.error(
                    f"Failed to perform bidirectional sync for server {server.id}"
                )
                return False

            # Check port availability (after sync, so port changes are reflected)
            port_available, port_message = await self._validate_port_availability(
                server, server_repository
            )
            if not port_available:
                logger.error(
                    f"Port validation failed for server {server.id}: {port_message}"
                )
                return False
            logger.info(f"Port validation passed for server {server.id}: {port_message}")

            # Check Java compatibility with Minecraft version
            (
                java_compatible,
                java_message,
                java_executable,
            ) = await self._check_java_compatibility(server.minecraft_version)
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
                        f"Daemon process {daemon_pid} died within {(i + 1) * 100}ms for server {server.id}"
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
            log_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.log_queue_size)
            log_buffer: deque[str] = deque(maxlen=self.log_queue_size)
            server_process = ServerProcess(
                server_id=server.id,
                process=None,  # No process object for daemon processes
                log_queue=log_queue,
                status=ServerStatus.starting,
                started_at=datetime.now(),
                log_buffer=log_buffer,
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
            await self._notify_status_change(server.id, ServerStatus.starting)

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
            await self._notify_status_change(server_id, ServerStatus.stopping)

            # Handle daemon processes (no process object)
            if server_process.process is None:
                return await self._stop_daemon_process(server_id, server_process, force)

            # Handle regular processes (with process object)
            # Check if process is already terminated
            if server_process.process.returncode is not None:
                logger.info(f"Server {server_id} process already terminated")
                # Clean up immediately if process is already dead
                await self._cleanup_server_process(server_id)
                await self._notify_status_change(server_id, ServerStatus.stopped)
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
            await self._notify_status_change(server_id, ServerStatus.stopped)

            logger.info(f"Successfully stopped server {server_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop server {server_id}: {e}")
            # Ensure cleanup even if there was an error
            try:
                await self._cleanup_server_process(server_id)
                await self._notify_status_change(server_id, ServerStatus.stopped)
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
        """Get recent server logs (most-recent *lines* entries)."""
        if server_id not in self.processes or lines <= 0:
            return []

        server_process = self.processes[server_id]
        buf = server_process.log_buffer
        if len(buf) <= lines:
            return list(buf)
        return list(buf)[-lines:]

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

                    # Clear log queue and buffer to free memory
                    try:
                        while not server_process.log_queue.empty():
                            server_process.log_queue.get_nowait()
                    except (asyncio.QueueEmpty, AttributeError):
                        pass
                    server_process.log_buffer.clear()

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
