"""Daemon process creation & termination.

Verbatim move of the subprocess/fork/signal handling that builds the
Minecraft server daemon (double-fork technique, alternative Popen path,
and SIGTERM/SIGKILL teardown). Methods rely on ``self._is_process_running``,
``self._cleanup_server_process``, ``self._notify_status_change`` from
sibling mixins.
"""

import asyncio
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

from app.servers.application.minecraft._compat import logger
from app.servers.application.minecraft.server_process import ServerProcess
from app.servers.models import ServerStatus


class DaemonProcessMixin:
    """Mixin: daemon subprocess creation and shutdown."""

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

            # Create the process with proper detachment. Open the log files
            # in a with-block so the parent's file handles are released even
            # when Popen raises — the child inherits via FD duplication.
            import subprocess

            with (
                open(log_file_path, "w") as stdout_f,
                open(error_file_path, "w") as stderr_f,
            ):
                process = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    stdout=stdout_f,
                    stderr=stderr_f,
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
                await self._notify_status_change(server_id, ServerStatus.stopped)
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
                        await self._notify_status_change(server_id, ServerStatus.stopped)
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
                        await self._notify_status_change(server_id, ServerStatus.stopped)
                        return True

                logger.error(
                    f"Failed to stop daemon server {server_id} even with SIGKILL"
                )
                return False

            except ProcessLookupError:
                # Process already dead
                logger.info(f"Daemon server {server_id} process already terminated")
                await self._cleanup_server_process(server_id)
                await self._notify_status_change(server_id, ServerStatus.stopped)
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
