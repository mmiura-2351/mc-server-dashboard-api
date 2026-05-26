"""``ServerProcess`` dataclass: in-memory record for a managed server."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.servers.models import ServerStatus


@dataclass
class ServerProcess:
    """Represents a running Minecraft server process"""

    server_id: int
    process: asyncio.subprocess.Process
    log_queue: asyncio.Queue[str]
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
