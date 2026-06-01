"""PID-file management & cold-start process restoration.

Methods in this mixin are moved verbatim from the original
``MinecraftServerManager``. They reference state owned by the composed
manager (``self.processes``, ``self.base_directory``,
``self.log_queue_size``) but do not own it.
"""

import asyncio
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import psutil

from app.core.config import settings
from app.servers.application.minecraft._compat import logger
from app.servers.application.minecraft.server_process import ServerProcess
from app.servers.models import ServerStatus


class PidFileMixin:
    """Mixin: PID file read/write + process restoration."""

    def _get_pid_file_path(self, server_id: int, server_dir: Path) -> Path:
        """Get path to PID file for server"""
        return server_dir / "server.pid"

    async def _write_pid_file(
        self,
        server_id: int,
        server_dir: Path,
        process: asyncio.subprocess.Process,
        port: int,
        command,
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

            log_buffer: deque[str] = deque(maxlen=self.log_queue_size)

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
                process=None,
                status=ServerStatus.running,
                started_at=started_at,
                log_buffer=log_buffer,
                pid=pid,
                server_directory=server_dir,
                rcon_port=rcon_port,
                rcon_password=rcon_password,
            )

            self.processes[server_id] = server_process

            # Start the log reader so the restored server keeps populating its
            # log buffer (issue #427); track it for cleanup like start_server().
            server_process.log_task = asyncio.create_task(
                self._read_server_logs(server_process)
            )

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
                    await self._notify_status_change(server_id, ServerStatus.stopped)

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
            await self._notify_status_change(server_id, ServerStatus.error)
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
            # Sort directories to ensure deterministic processing order for tests
            for server_dir in sorted(self.base_directory.iterdir()):
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
                        await self._notify_status_change(server_id, ServerStatus.running)
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
