"""Server process & log monitoring, plus per-server resource cleanup."""

import asyncio
import os
from datetime import datetime
from pathlib import Path

from app.servers.application.minecraft._compat import logger
from app.servers.application.minecraft.server_process import ServerProcess
from app.servers.models import ServerStatus


class MonitoringMixin:
    """Mixin: log readers, status monitors, and resource cleanup."""

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
                    await self._notify_status_change(server_id, ServerStatus.error)
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
                                    f"Server {server_id} pattern check at {(i + 1) * 0.5:.1f}s: {pattern_results[:2]}"
                                )

                            if startup_detected_local:
                                elapsed_seconds = (i + 1) * 0.5
                                logger.info(
                                    f"Daemon server {server_id} startup completed (detected pattern '{detected_pattern}' after {elapsed_seconds:.1f}s)"
                                )
                                server_process.status = ServerStatus.running
                                await self._notify_status_change(
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
                    await self._notify_status_change(server_id, ServerStatus.running)
                else:
                    logger.error(
                        f"Daemon server {server_id} process {pid} died during startup (timeout)"
                    )
                    server_process.status = ServerStatus.error
                    await self._notify_status_change(server_id, ServerStatus.error)
                    # Schedule cleanup without awaiting to avoid self-await issue
                    asyncio.create_task(self._cleanup_server_process(server_id))
                    return

            # Continue monitoring for process termination
            while server_id in self.processes:
                if not await self._is_process_running(pid):
                    logger.info(f"Daemon server {server_id} process {pid} has stopped")
                    server_process.status = ServerStatus.stopped
                    await self._notify_status_change(server_id, ServerStatus.stopped)
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
            await self._notify_status_change(server_id, ServerStatus.error)
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

                server_process.log_buffer.clear()

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

                                server_process.log_buffer.append(formatted_line)

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
                await self._notify_status_change(
                    server_process.server_id, ServerStatus.error
                )

                # Clean up
                await self._cleanup_server_process(server_process.server_id)
                return

            except asyncio.TimeoutError:
                # Process is still running after 5 seconds - this is good
                logger.info(
                    f"Server {server_process.server_id} process is stable after 5 seconds - marking as running"
                )
                server_process.status = ServerStatus.running
                await self._notify_status_change(
                    server_process.server_id, ServerStatus.running
                )

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
                        await self._notify_status_change(
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
            await self._notify_status_change(server_process.server_id, ServerStatus.error)

            # Clean up
            await self._cleanup_server_process(server_process.server_id)
