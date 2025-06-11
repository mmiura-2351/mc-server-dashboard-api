import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.servers.models import Server
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import User

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self.user_connections: Dict[WebSocket, User] = {}
        self.server_log_tasks: Dict[int, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, server_id: int, user: User):
        await websocket.accept()

        if server_id not in self.active_connections:
            self.active_connections[server_id] = set()

        self.active_connections[server_id].add(websocket)
        self.user_connections[websocket] = user

        # Start log streaming for this server if not already started
        if server_id not in self.server_log_tasks:
            self.server_log_tasks[server_id] = asyncio.create_task(
                self._stream_server_logs(server_id)
            )

        logger.info(f"WebSocket connected for server {server_id} by user {user.username}")

    def disconnect(self, websocket: WebSocket, server_id: int):
        if server_id in self.active_connections:
            self.active_connections[server_id].discard(websocket)

            # Stop log streaming if no more connections for this server
            if not self.active_connections[server_id]:
                if server_id in self.server_log_tasks:
                    self.server_log_tasks[server_id].cancel()
                    del self.server_log_tasks[server_id]
                del self.active_connections[server_id]

        if websocket in self.user_connections:
            user = self.user_connections[websocket]
            del self.user_connections[websocket]
            logger.info(
                f"WebSocket disconnected for server {server_id} by user {user.username}"
            )

    async def send_to_server_connections(self, server_id: int, message: dict):
        if server_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[server_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"Error sending message to WebSocket: {e}")
                    disconnected.add(connection)

            # Remove disconnected connections
            for connection in disconnected:
                self.disconnect(connection, server_id)

    async def send_personal_message(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def broadcast_server_status(self, server_id: int, status: dict):
        message = {
            "type": "server_status",
            "server_id": server_id,
            "timestamp": datetime.now().isoformat(),
            "data": status,
        }
        await self.send_to_server_connections(server_id, message)

    async def broadcast_server_notification(self, server_id: int, notification: dict):
        message = {
            "type": "notification",
            "server_id": server_id,
            "timestamp": datetime.now().isoformat(),
            "data": notification,
        }
        await self.send_to_server_connections(server_id, message)

    async def _stream_server_logs(self, server_id: int):
        """Stream server logs to all connected clients for a specific server"""
        try:
            server_manager = minecraft_server_manager.get_server(str(server_id))
            if not server_manager:
                logger.warning(f"Server manager not found for server {server_id}")
                return

            # Validate server_manager has required attributes
            if not hasattr(server_manager, 'server_dir') or not server_manager.server_dir:
                logger.error(f"Invalid server manager for server {server_id}: missing server_dir")
                return

            # Get the log file path with proper validation
            try:
                log_file = server_manager.server_dir / "logs" / "latest.log"
            except Exception as e:
                logger.error(f"Failed to construct log file path for server {server_id}: {e}")
                return

            if not log_file.exists():
                logger.debug(f"Log file does not exist for server {server_id}: {log_file}")
                return

            if not log_file.is_file():
                logger.error(f"Log path is not a file for server {server_id}: {log_file}")
                return

            # Follow the log file like 'tail -f'
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                # Start from the end of the file
                f.seek(0, 2)

                while server_id in self.active_connections:
                    line = f.readline()
                    if line:
                        # Send log line to all connected clients
                        message = {
                            "type": "server_log",
                            "server_id": server_id,
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "log_line": line.strip(),
                                "log_type": self._determine_log_type(line),
                            },
                        }
                        await self.send_to_server_connections(server_id, message)
                    else:
                        # No new lines, wait a bit
                        await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info(f"Log streaming cancelled for server {server_id}")
        except FileNotFoundError as e:
            logger.warning(f"Log file not found for server {server_id}: {e}")
        except PermissionError as e:
            logger.error(f"Permission denied accessing log file for server {server_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error streaming logs for server {server_id}: {e}")

    def _determine_log_type(self, log_line: str) -> str:
        """Determine the type of log message"""
        log_line_lower = log_line.lower()

        if "error" in log_line_lower or "exception" in log_line_lower:
            return "error"
        elif "warn" in log_line_lower:
            return "warning"
        elif "info" in log_line_lower:
            return "info"
        elif "debug" in log_line_lower:
            return "debug"
        elif "joined the game" in log_line_lower:
            return "player_join"
        elif "left the game" in log_line_lower:
            return "player_leave"
        elif "chat" in log_line_lower or "<" in log_line and ">" in log_line:
            return "chat"
        else:
            return "other"


class WebSocketService:
    def __init__(self):
        self.connection_manager = ConnectionManager()
        self._status_monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self):
        """Start the background status monitoring task"""
        if self._status_monitor_task is None or self._status_monitor_task.done():
            self._status_monitor_task = asyncio.create_task(self._monitor_server_status())

    async def stop_monitoring(self):
        """Stop the background status monitoring task"""
        if self._status_monitor_task and not self._status_monitor_task.done():
            self._status_monitor_task.cancel()
            try:
                await self._status_monitor_task
            except asyncio.CancelledError:
                pass

    async def handle_connection(
        self, websocket: WebSocket, server_id: int, user: User, db: Session
    ):
        # Verify server exists and user has access
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            await websocket.close(code=1008, reason="Server not found")
            return

        await self.connection_manager.connect(websocket, server_id, user)

        try:
            # Send initial server status
            await self._send_initial_status(websocket, server_id)

            # Handle incoming messages
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                await self._handle_message(websocket, server_id, message, user, db)

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self.connection_manager.disconnect(websocket, server_id)

    async def _send_initial_status(self, websocket: WebSocket, server_id: int):
        """Send initial server status when client connects"""
        try:
            server_manager = minecraft_server_manager.get_server(str(server_id))
            if not server_manager:
                logger.warning(f"Server manager not found for initial status: {server_id}")
                return

            # Validate server manager has required methods
            if not hasattr(server_manager, 'get_status') or not callable(getattr(server_manager, 'get_status')):
                logger.error(f"Invalid server manager for server {server_id}: missing get_status method")
                return

            status = await server_manager.get_status()
            message = {
                "type": "initial_status",
                "server_id": server_id,
                "timestamp": datetime.now().isoformat(),
                "data": status,
            }
            await self.connection_manager.send_personal_message(websocket, message)
        except Exception as e:
            logger.error(f"Error sending initial status for server {server_id}: {e}")

    async def _handle_message(
        self, websocket: WebSocket, server_id: int, message: dict, user: User, db: Session
    ):
        """Handle incoming WebSocket messages from clients"""
        message_type = message.get("type")

        if message_type == "ping":
            await self.connection_manager.send_personal_message(
                websocket, {"type": "pong", "timestamp": datetime.now().isoformat()}
            )

        elif message_type == "send_command":
            if user.role.value in ["admin", "operator"]:
                command = message.get("command", "").strip()
                if command:
                    await self._send_server_command(server_id, command, user)

        elif message_type == "request_status":
            await self._send_initial_status(websocket, server_id)

    async def _send_server_command(self, server_id: int, command: str, user: User):
        """Send a command to the server and broadcast the result"""
        try:
            server_manager = minecraft_server_manager.get_server(str(server_id))
            if not server_manager:
                logger.warning(f"Server manager not found for command execution: {server_id}")
                return

            # Validate server manager has required methods
            if not hasattr(server_manager, 'is_running') or not callable(getattr(server_manager, 'is_running')):
                logger.error(f"Invalid server manager for server {server_id}: missing is_running method")
                return

            if not hasattr(server_manager, 'send_command') or not callable(getattr(server_manager, 'send_command')):
                logger.error(f"Invalid server manager for server {server_id}: missing send_command method")
                return

            if server_manager.is_running():
                await server_manager.send_command(command)

                # Broadcast command execution notification
                notification = {
                    "type": "command_executed",
                    "command": command,
                    "executed_by": user.username,
                    "message": f"Command '{command}' executed by {user.username}",
                }
                await self.connection_manager.broadcast_server_notification(
                    server_id, notification
                )
            else:
                logger.warning(f"Cannot send command to server {server_id}: server is not running")
        except Exception as e:
            logger.error(f"Error sending server command '{command}' to server {server_id}: {e}")

    async def _monitor_server_status(self):
        """Background task to monitor server status changes"""
        try:
            while True:
                for server_id in list(self.connection_manager.active_connections.keys()):
                    try:
                        server_manager = minecraft_server_manager.get_server(
                            str(server_id)
                        )
                        if not server_manager:
                            logger.debug(f"Server manager not found for monitoring: {server_id}")
                            continue

                        # Validate server manager has required methods
                        if not hasattr(server_manager, 'get_status') or not callable(getattr(server_manager, 'get_status')):
                            logger.error(f"Invalid server manager for monitoring server {server_id}: missing get_status method")
                            continue

                        status = await server_manager.get_status()
                        await self.connection_manager.broadcast_server_status(
                            server_id, status
                        )
                    except Exception as e:
                        logger.error(f"Error monitoring server {server_id}: {e}")

                await asyncio.sleep(5)  # Check every 5 seconds

        except asyncio.CancelledError:
            logger.info("Server status monitoring cancelled")
        except Exception as e:
            logger.error(f"Error in status monitoring: {e}")


# Global WebSocket service instance
websocket_service = WebSocketService()
