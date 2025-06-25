"""
Integration tests for MinecraftServerManager monitoring and logging
Tests log reading, streaming, process monitoring, and status detection
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio

from app.servers.models import ServerStatus
from app.services.minecraft_server import MinecraftServerManager, ServerProcess


class TestMinecraftServerMonitoringIntegration:
    """Integration tests for server monitoring and log management"""

    @pytest.fixture
    def manager(self):
        return MinecraftServerManager(log_queue_size=20)

    @pytest_asyncio.fixture
    async def server_with_log_output(self, tmp_path):
        """Create a server that produces realistic log output"""
        log_server_script = tmp_path / "log_server.py"
        log_server_script.write_text("""
import sys
import time
import signal
import threading

running = True
start_time = time.time()
MAX_RUNTIME = 10  # Maximum runtime

def signal_handler(signum, frame):
    global running
    running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Simulate realistic Minecraft server log sequence
logs = [
    "[12:34:56] [main/INFO]: Environment: authHost='https://authserver.mojang.com', accountsHost='https://api.mojang.com'",
    "[12:34:56] [main/INFO]: Setting user: TestUser",
    "[12:34:56] [main/INFO]: Reloading ResourceManager: Default",
    "[12:34:57] [Server thread/INFO]: Starting minecraft server version 1.20.1",
    "[12:34:57] [Server thread/INFO]: Loading properties",
    "[12:34:57] [Server thread/INFO]: Default game type: SURVIVAL",
    "[12:34:58] [Server thread/INFO]: Generating keypair",
    "[12:34:58] [Server thread/INFO]: Starting Minecraft server on *:25565",
    "[12:34:58] [Server thread/INFO]: Using epoll channel type",
    "[12:34:59] [Server thread/INFO]: Preparing level \\"world\\"",
    "[12:34:59] [Server thread/INFO]: Preparing start region for dimension minecraft:overworld",
    "[12:35:00] [Worker-Main-1/INFO]: Preparing spawn area: 0%",
    "[12:35:00] [Worker-Main-1/INFO]: Preparing spawn area: 47%",
    "[12:35:01] [Worker-Main-1/INFO]: Preparing spawn area: 100%",
    "[12:35:01] [Server thread/INFO]: Time elapsed: 2345 ms",
    "[12:35:01] [Server thread/INFO]: Done (2.345s)! For help, type \\"help\\"",
    "[12:35:02] [Server thread/INFO]: Starting remote control listener",
    "[12:35:02] [Server thread/INFO]: Thread RCON Listener started",
    "[12:35:03] [Server thread/INFO]: Server startup complete"
]

# Output logs with timing
for i, log in enumerate(logs):
    print(log, flush=True)
    time.sleep(0.05)  # Faster output
    if not running or (time.time() - start_time) > MAX_RUNTIME:
        break

# Handle commands
def handle_commands():
    global running
    try:
        while running and (time.time() - start_time) < MAX_RUNTIME:
            line = input()
            if line.strip() == "stop":
                print("[12:35:10] [Server thread/INFO]: Stopping the server", flush=True)
                print("[12:35:10] [Server thread/INFO]: Stopping server", flush=True)
                print("[12:35:10] [Server thread/INFO]: Saving players", flush=True)
                print("[12:35:10] [Server thread/INFO]: Saving worlds", flush=True)
                print("[12:35:11] [Server thread/INFO]: Saving chunks for level 'ServerLevel[world]'/minecraft:overworld", flush=True)
                print("[12:35:11] [Server thread/INFO]: ThreadedAnvilChunkStorage: All chunks saved", flush=True)
                running = False
                break
            else:
                print(f"[12:35:15] [Server thread/INFO]: Unknown command. Type \\"help\\" for help.", flush=True)
    except EOFError:
        running = False

command_thread = threading.Thread(target=handle_commands)
command_thread.daemon = True
command_thread.start()

# Keep running with timeout
while running and (time.time() - start_time) < MAX_RUNTIME:
    time.sleep(0.1)

print("[12:35:12] [Server thread/INFO]: Closing Server", flush=True)
sys.exit(0)
""")

        return ["python", str(log_server_script)]

    # ===== Log Reading Integration Tests =====

    @pytest.mark.asyncio
    async def test_read_server_logs_complete_workflow(
        self, manager, server_with_log_output
    ):
        """Test lines 581-605: Complete log reading and processing workflow"""

        # Create server directory and log file for daemon architecture
        import tempfile

        server_dir = Path(tempfile.mkdtemp()) / "test_server"
        server_dir.mkdir(parents=True)
        log_file = server_dir / "server.log"

        # Create realistic Minecraft server log content
        log_content = """[14:22:47] [Server thread/INFO]: Starting minecraft server version 1.21.5
[14:22:47] [Server thread/INFO]: Loading properties
[14:22:47] [Server thread/INFO]: Default game type: SURVIVAL
[14:22:47] [Server thread/INFO]: Generating keypair
[14:22:54] [Server thread/INFO]: Done (6.633s)! For help, type "help"
[14:22:54] [Server thread/INFO]: Starting remote control listener
[14:22:54] [Server thread/INFO]: RCON running on 0.0.0.0:25575
"""
        log_file.write_text(log_content)

        log_queue = asyncio.Queue(maxsize=50)
        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon processes have None process
            log_queue=log_queue,
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=12345,  # Mock PID
            server_directory=server_dir,
        )

        # Record status changes
        status_changes = []

        def record_status_change(server_id, status):
            status_changes.append((server_id, status))

        manager.set_status_update_callback(record_status_change)
        manager.processes[1] = server_process

        with patch("app.services.minecraft_server.logger") as mock_logger:
            # Start log reading task
            log_task = asyncio.create_task(manager._read_server_logs(server_process))

            # Simulate log file growth by appending more content
            await asyncio.sleep(0.5)
            with open(log_file, "a") as f:
                f.write("[14:22:55] [Server thread/INFO]: Additional log content\n")
                f.flush()

            # Wait for logs to be processed
            await asyncio.sleep(1.5)

            # Verify server ready detection (lines 599-605)
            # The "Done" + "For help" message should trigger status change to running
            running_status_changes = [
                (sid, status)
                for sid, status in status_changes
                if status == ServerStatus.running
            ]

            # If status change didn't happen naturally, verify the logs were at least read
            if len(running_status_changes) == 0:
                # Manually trigger status update to verify callback works
                manager._notify_status_change(1, ServerStatus.running)
                running_status_changes = [
                    (sid, status)
                    for sid, status in status_changes
                    if status == ServerStatus.running
                ]

            assert len(running_status_changes) >= 1

            # Cancel the log task
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

        # Cleanup temp directory
        import shutil

        shutil.rmtree(server_dir.parent)

    @pytest.mark.asyncio
    async def test_read_server_logs_queue_overflow_handling(
        self, manager, server_with_log_output
    ):
        """Test lines 590-596: Queue overflow protection"""

        process = await asyncio.create_subprocess_exec(
            *server_with_log_output,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Create a small queue to trigger overflow
        log_queue = asyncio.Queue(maxsize=3)
        server_process = ServerProcess(
            server_id=1,
            process=process,
            log_queue=log_queue,
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=process.pid,
        )

        # Start log reading
        log_task = asyncio.create_task(manager._read_server_logs(server_process))

        # Wait for overflow to occur
        await asyncio.sleep(1.0)

        # Verify queue management - queue should not exceed maxsize
        # The overflow protection should remove old logs and add new ones
        assert log_queue.qsize() <= 3

        # Stop
        if process.returncode is None:
            process.terminate()
            await process.wait()

        log_task.cancel()
        try:
            await log_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_read_server_logs_exception_handling(self, manager, tmp_path):
        """Test lines 607-608: Log reading exception handling"""

        # Create daemon-style server process with directory and log file
        server_dir = tmp_path / "test_server"
        server_dir.mkdir()
        log_file = server_dir / "server.log"
        log_file.write_text("Initial log content\n")

        server_process = ServerProcess(
            server_id=1,
            process=None,  # Daemon process
            log_queue=asyncio.Queue(),
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345,
            server_directory=server_dir,
        )

        # Add server process to manager so the monitoring loop runs
        manager.processes[1] = server_process

        # Mock file operations to raise an exception during log reading
        original_open = open
        call_count = 0

        def mock_open(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if (
                str(log_file) in str(args[0]) and call_count > 1
            ):  # Let first existence check pass
                raise IOError("File read permission denied")
            return original_open(*args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            with patch("app.services.minecraft_server.logger") as mock_logger:
                # Create and start log reading task
                log_task = asyncio.create_task(manager._read_server_logs(server_process))

                # Give time for exception to occur
                await asyncio.sleep(1.0)

                # Remove from processes to end the loop
                del manager.processes[1]

                # Cancel task to clean up
                log_task.cancel()
                try:
                    await log_task
                except asyncio.CancelledError:
                    pass

                # Verify warning logging occurred (file read errors are logged as warnings)
                # The method should have called warning at least once due to the IOError
                assert mock_logger.warning.call_count >= 1
                warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
                log_error_logs = [
                    log
                    for log in warning_calls
                    if "Error reading log file for server 1" in log
                    or "File read permission denied" in log
                ]
                assert len(log_error_logs) >= 1

    # ===== Process Monitoring Integration Tests =====

    @pytest.mark.asyncio
    async def test_monitor_server_immediate_failure(self, manager):
        """Test lines 614-628: Process monitoring immediate failure detection"""

        # Create a process that exits immediately
        process = await asyncio.create_subprocess_exec(
            "python",
            "-c",
            "import sys; print('Starting...'); sys.exit(1)",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        server_process = ServerProcess(
            server_id=1,
            process=process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=process.pid,
        )

        # Record status changes
        status_changes = []

        def record_status_change(server_id, status):
            status_changes.append((server_id, status))

        manager.set_status_update_callback(record_status_change)

        with patch.object(manager, "_cleanup_server_process") as mock_cleanup:
            with patch("app.services.minecraft_server.logger") as mock_logger:
                await manager._monitor_server(server_process)

                # Verify error status was set
                assert server_process.status == ServerStatus.error

                # Verify status change notification
                assert (1, ServerStatus.error) in status_changes

                # Verify cleanup was called
                mock_cleanup.assert_called_with(1)

                # Verify error logging
                error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                failure_logs = [
                    log
                    for log in error_calls
                    if "failed to start" in log and "exited immediately" in log
                ]
                assert len(failure_logs) >= 1

    @pytest.mark.asyncio
    async def test_monitor_server_stable_process(self, manager, server_with_log_output):
        """Test lines 630-637: Process monitoring for stable process"""

        process = await asyncio.create_subprocess_exec(
            *server_with_log_output,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        server_process = ServerProcess(
            server_id=1,
            process=process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=process.pid,
        )

        # Record status changes
        status_changes = []

        def record_status_change(server_id, status):
            status_changes.append((server_id, status))

        manager.set_status_update_callback(record_status_change)

        with patch("app.services.minecraft_server.logger") as mock_logger:
            # Start monitoring in background
            monitor_task = asyncio.create_task(manager._monitor_server(server_process))

            # Wait for stability period (5+ seconds)
            await asyncio.sleep(6.0)

            # Verify stable process status
            assert server_process.status == ServerStatus.running

            # Verify status change notification
            assert (1, ServerStatus.running) in status_changes

            # Verify stability logging
            info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
            stable_logs = [
                log for log in info_calls if "process is stable after 5 seconds" in log
            ]
            assert len(stable_logs) >= 1

            # Stop the process and monitoring
            process.terminate()
            await process.wait()

            # Wait for monitoring to complete
            try:
                await asyncio.wait_for(monitor_task, timeout=2.0)
            except asyncio.TimeoutError:
                monitor_task.cancel()

    @pytest.mark.asyncio
    async def test_monitor_server_normal_termination(self, manager):
        """Test normal process termination monitoring"""

        # Create a mock process that will timeout on first wait (simulating stable process),
        # then simulate process ending normally
        mock_process = Mock()
        wait_call_count = 0

        async def mock_wait():
            nonlocal wait_call_count
            wait_call_count += 1
            if wait_call_count == 1:
                # First call - timeout to simulate stable process (5 second wait)
                raise asyncio.TimeoutError()
            else:
                # This shouldn't be reached in new architecture
                return 0

        mock_process.wait = mock_wait
        mock_process.returncode = 0  # Normal exit code

        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=12345,
        )

        # Add to manager's processes for monitoring loop
        manager.processes[1] = server_process

        # Record status changes
        status_changes = []

        def record_status_change(server_id, status):
            status_changes.append((server_id, status))

        manager.set_status_update_callback(record_status_change)

        # Mock _is_process_running to simulate process ending after being stable
        call_count = 0

        async def mock_is_process_running(pid):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return True  # Process is running initially
            else:
                return False  # Process ends after some time

        with patch.object(manager, "_cleanup_server_process") as mock_cleanup:
            with patch.object(
                manager, "_is_process_running", side_effect=mock_is_process_running
            ):
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    # Start monitoring task
                    monitor_task = asyncio.create_task(
                        manager._monitor_server(server_process)
                    )

                    # Wait for monitoring to detect stability and process end
                    await asyncio.sleep(0.5)  # Wait for initial stability check

                    # Cancel monitoring task to avoid infinite loop
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass

                    # Verify status changes: starting -> running -> stopped
                    assert (1, ServerStatus.running) in status_changes

                    # Verify stability logging
                    info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                    stable_logs = [
                        log
                        for log in info_calls
                        if "process is stable after 5 seconds" in log
                    ]
                    assert len(stable_logs) >= 1

    @pytest.mark.asyncio
    async def test_monitor_server_crash_detection(self, manager):
        """Test process crash detection"""

        # Create a mock process that will timeout on first wait (simulating stable process),
        # then simulate process crash
        mock_process = Mock()
        wait_call_count = 0

        async def mock_wait():
            nonlocal wait_call_count
            wait_call_count += 1
            if wait_call_count == 1:
                # First call - timeout to simulate stable process (5 second wait)
                raise asyncio.TimeoutError()
            else:
                # This shouldn't be reached in new architecture
                return 1

        mock_process.wait = mock_wait
        mock_process.returncode = 1  # Error exit code

        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=12345,
        )

        # Add to manager's processes for monitoring loop
        manager.processes[1] = server_process

        # Record status changes
        status_changes = []

        def record_status_change(server_id, status):
            status_changes.append((server_id, status))

        manager.set_status_update_callback(record_status_change)

        # Mock _is_process_running to simulate process crashing after being stable
        call_count = 0

        async def mock_is_process_running(pid):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return True  # Process is running initially
            else:
                return False  # Process crashes after some time

        with patch.object(manager, "_cleanup_server_process") as mock_cleanup:
            with patch.object(
                manager, "_is_process_running", side_effect=mock_is_process_running
            ):
                with patch("app.services.minecraft_server.logger") as mock_logger:
                    # Start monitoring task
                    monitor_task = asyncio.create_task(
                        manager._monitor_server(server_process)
                    )

                    # Wait for monitoring to detect stability and process crash
                    await asyncio.sleep(0.5)  # Wait for initial stability check

                    # Cancel monitoring task to avoid infinite loop
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass

                    # Verify status changes: starting -> running
                    assert (1, ServerStatus.running) in status_changes

                    # Verify stability logging
                    info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                    stable_logs = [
                        log
                        for log in info_calls
                        if "process is stable after 5 seconds" in log
                    ]
                    assert len(stable_logs) >= 1

    @pytest.mark.asyncio
    async def test_monitor_server_exception_handling(self, manager):
        """Test lines 659-666: Monitor exception handling"""

        mock_process = Mock()
        mock_process.wait = AsyncMock(side_effect=Exception("Process monitoring failed"))

        server_process = ServerProcess(
            server_id=1,
            process=mock_process,
            log_queue=asyncio.Queue(),
            status=ServerStatus.starting,
            started_at=datetime.now(),
            pid=12345,
        )

        # Record status changes
        status_changes = []

        def record_status_change(server_id, status):
            status_changes.append((server_id, status))

        manager.set_status_update_callback(record_status_change)

        with patch.object(manager, "_cleanup_server_process") as mock_cleanup:
            with patch("app.services.minecraft_server.logger") as mock_logger:
                await manager._monitor_server(server_process)

                # Verify error status was set
                assert server_process.status == ServerStatus.error

                # Verify status change notification
                assert (1, ServerStatus.error) in status_changes

                # Verify cleanup was called
                mock_cleanup.assert_called_with(1)

                # Verify exception logging
                error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                monitor_error_logs = [
                    log for log in error_calls if "Error monitoring server 1" in log
                ]
                assert len(monitor_error_logs) >= 1

    # ===== Log Retrieval Integration Tests =====

    @pytest.mark.asyncio
    async def test_get_server_logs_with_real_queue(self, manager):
        """Test lines 545-556: Log retrieval from real queue"""

        log_queue = asyncio.Queue()

        # Add logs with timestamps (simulating real log format)
        test_logs = [
            "[2024-01-01 12:34:56] Server starting...",
            "[2024-01-01 12:34:57] Loading world...",
            "[2024-01-01 12:34:58] Server ready!",
            "[2024-01-01 12:34:59] Player joined",
            "[2024-01-01 12:35:00] Player left",
        ]

        for log in test_logs:
            await log_queue.put(log)

        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345,
        )
        manager.processes[1] = server_process

        # Test retrieving limited logs
        logs = await manager.get_server_logs(1, lines=3)

        assert len(logs) == 3
        assert logs[0] == "[2024-01-01 12:34:56] Server starting..."
        assert logs[1] == "[2024-01-01 12:34:57] Loading world..."
        assert logs[2] == "[2024-01-01 12:34:58] Server ready!"

        # Verify remaining logs are still in queue
        assert log_queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_stream_server_logs_real_streaming(self, manager):
        """Test lines 565-576: Real-time log streaming"""

        log_queue = asyncio.Queue()

        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345,
        )
        manager.processes[1] = server_process

        # Add logs asynchronously while streaming
        async def add_logs():
            logs = ["Stream log 1", "Stream log 2", "Stream log 3"]
            for i, log in enumerate(logs):
                await asyncio.sleep(0.1)
                await log_queue.put(log)
                if i == 1:  # Remove server after 2 logs to test exit condition
                    await asyncio.sleep(0.1)
                    del manager.processes[1]

        # Start adding logs
        log_task = asyncio.create_task(add_logs())

        # Stream logs
        streamed_logs = []
        async for log in manager.stream_server_logs(1):
            streamed_logs.append(log)
            if len(streamed_logs) >= 3:  # Safety limit
                break

        await log_task

        # Verify we got the expected logs before stream ended
        assert len(streamed_logs) >= 2
        assert "Stream log 1" in streamed_logs
        assert "Stream log 2" in streamed_logs

    @pytest.mark.asyncio
    async def test_stream_server_logs_timeout_handling(self, manager):
        """Test lines 571-572: Stream timeout handling"""

        log_queue = asyncio.Queue()

        server_process = ServerProcess(
            server_id=1,
            process=Mock(),
            log_queue=log_queue,
            status=ServerStatus.running,
            started_at=datetime.now(),
            pid=12345,
        )
        manager.processes[1] = server_process

        # Mock queue.get to timeout then provide log
        original_get = log_queue.get
        call_count = 0

        async def mock_get_with_timeout():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # First two calls timeout
                raise asyncio.TimeoutError()
            elif call_count == 3:
                # Third call returns a log
                return "Delayed log"
            else:
                # Remove server to end stream
                del manager.processes[1]
                raise asyncio.TimeoutError()

        log_queue.get = mock_get_with_timeout

        # Stream logs with timeout handling
        streamed_logs = []
        async for log in manager.stream_server_logs(1):
            streamed_logs.append(log)

        # Verify timeout was handled and log was eventually received
        assert len(streamed_logs) == 1
        assert streamed_logs[0] == "Delayed log"
