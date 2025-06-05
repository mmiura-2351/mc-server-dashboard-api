import asyncio
import os
import signal
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime

from app.servers.models import Server, ServerStatus


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
    
    def __init__(self):
        self.processes: Dict[int, ServerProcess] = {}
        self.base_directory = Path("servers")
        self.base_directory.mkdir(exist_ok=True)
    
    async def start_server(self, server: Server) -> bool:
        """Start a Minecraft server"""
        try:
            if server.id in self.processes:
                logger.warning(f"Server {server.id} is already running")
                return False
            
            server_dir = self.base_directory / str(server.id)
            server_dir.mkdir(exist_ok=True)
            
            # Prepare command
            jar_path = server_dir / f"server-{server.minecraft_version}.jar"
            if not jar_path.exists():
                logger.error(f"Server JAR not found: {jar_path}")
                return False
            
            cmd = [
                "java",
                f"-Xmx{server.max_memory}M",
                f"-Xms{min(server.max_memory, 512)}M",
                "-jar",
                str(jar_path),
                "nogui"
            ]
            
            # Create process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(server_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE
            )
            
            # Create server process tracking
            log_queue = asyncio.Queue(maxsize=1000)
            server_process = ServerProcess(
                server_id=server.id,
                process=process,
                log_queue=log_queue,
                status=ServerStatus.starting,
                started_at=datetime.now(),
                pid=process.pid
            )
            
            self.processes[server.id] = server_process
            
            # Start log reading task
            asyncio.create_task(self._read_server_logs(server_process))
            
            # Start status monitoring task
            asyncio.create_task(self._monitor_server(server_process))
            
            logger.info(f"Started server {server.id} with PID {process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start server {server.id}: {e}")
            return False
    
    async def stop_server(self, server_id: int, force: bool = False) -> bool:
        """Stop a Minecraft server"""
        try:
            if server_id not in self.processes:
                logger.warning(f"Server {server_id} is not running")
                return False
            
            server_process = self.processes[server_id]
            server_process.status = ServerStatus.stopping
            
            if not force:
                # Send graceful stop command
                try:
                    server_process.process.stdin.write(b"stop\n")
                    await server_process.process.stdin.drain()
                    
                    # Wait for graceful shutdown
                    await asyncio.wait_for(
                        server_process.process.wait(), 
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Server {server_id} did not stop gracefully, forcing termination")
                    force = True
            
            if force:
                # Force termination
                server_process.process.terminate()
                try:
                    await asyncio.wait_for(
                        server_process.process.wait(), 
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    server_process.process.kill()
                    await server_process.process.wait()
            
            # Clean up
            del self.processes[server_id]
            logger.info(f"Stopped server {server_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop server {server_id}: {e}")
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
            "uptime_seconds": (datetime.now() - server_process.started_at).total_seconds()
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
                    server_process.log_queue.get(),
                    timeout=1.0
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
                    logger.info(f"Server {server_process.server_id} is now running")
                
        except Exception as e:
            logger.error(f"Error reading logs for server {server_process.server_id}: {e}")
    
    async def _monitor_server(self, server_process: ServerProcess):
        """Monitor server process and update status"""
        try:
            # Wait for process to finish
            await server_process.process.wait()
            
            # Process has ended
            return_code = server_process.process.returncode
            
            if return_code == 0:
                logger.info(f"Server {server_process.server_id} stopped normally")
            else:
                logger.warning(f"Server {server_process.server_id} crashed with code {return_code}")
                server_process.status = ServerStatus.error
            
            # Clean up if still in processes dict
            if server_process.server_id in self.processes:
                del self.processes[server_process.server_id]
                
        except Exception as e:
            logger.error(f"Error monitoring server {server_process.server_id}: {e}")
            server_process.status = ServerStatus.error
    
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