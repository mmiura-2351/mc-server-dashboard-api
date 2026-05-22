"""Group → server file synchronization helper.

Materialises ops.json / whitelist.json from the groups attached to a
server, optionally followed by a best-effort real-time command broadcast
(reload-whitelist, sync-op). Lifted out of the legacy `GroupFileService`
so the application service stays focused on use-case orchestration.

Per `docs/ARCHITECTURE.md` §4.2, this module is part of the application
layer and may **not** touch SQLAlchemy. All persistence access goes
through `ServerReadPort` (for the directory path) and
`ServerGroupRepository` (for the attached-group set / attached-server
list).
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.exceptions import FileOperationException
from app.core.security import PathValidator, SecurityError
from app.groups.domain.entities import GroupEntity
from app.groups.domain.ports import ServerGroupRepository
from app.groups.models import GroupType
from app.servers.domain.ports import ServerReadPort

logger = logging.getLogger(__name__)


def _build_ops_and_whitelist(
    groups: List[GroupEntity],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build the ops.json / whitelist.json payloads from attached groups.

    Pure function; isolated so unit tests can assert on file content
    correctness (legacy coverage gap addressed by #226's test plan).
    """
    ops_data: List[Dict[str, Any]] = []
    whitelist_data: List[Dict[str, Any]] = []
    for group in groups:
        for player in group.players:
            uuid = player["uuid"]
            name = player["username"]
            if group.type == GroupType.op:
                if not any(op["uuid"] == uuid for op in ops_data):
                    ops_data.append(
                        {
                            "uuid": uuid,
                            "name": name,
                            "level": 4,
                            "bypassesPlayerLimit": True,
                        }
                    )
            if group.type == GroupType.whitelist:
                if not any(wl["uuid"] == uuid for wl in whitelist_data):
                    whitelist_data.append({"uuid": uuid, "name": name})
    return ops_data, whitelist_data


class GroupFileSyncer:
    """Synchronises per-server ops.json / whitelist.json from group state.

    Constructor-injects its dependencies. The default value of
    `real_time_commands` is the production singleton so existing
    callsites do not have to thread the dependency through; tests
    inject a fake.
    """

    def __init__(
        self,
        server_groups: ServerGroupRepository,
        server_read: ServerReadPort,
        real_time_commands: Any = None,
    ):
        self._server_groups = server_groups
        self._server_read = server_read
        # Import the production singleton lazily so importing this
        # module does not pull in the websocket service chain.
        if real_time_commands is None:
            from app.servers.application.real_time_server_commands import (
                real_time_server_commands,
            )

            real_time_commands = real_time_server_commands
        self._real_time_commands = real_time_commands

    async def update_server_files(self, server_id: int) -> None:
        """Regenerate ops.json + whitelist.json for one server.

        Raises `FileOperationException` if the server directory fails
        the `PathValidator` security check or if I/O fails.
        """
        server = await self._server_read.get(server_id)
        if server is None:
            logger.warning(f"Server {server_id} not found during file sync")
            return

        logger.info(
            f"Starting file sync for server {server_id} "
            f"(name: {server.name}, path: {server.directory_path})"
        )

        groups = await self._server_groups.list_groups_for_server(server_id)
        logger.info(
            f"Found {len(groups)} groups attached to server {server_id}: "
            f"{[g.name for g in groups]}"
        )

        # Validate server directory path for security
        try:
            server_path = Path(server.directory_path)
            base_directory = Path("servers")
            PathValidator.validate_safe_path(server_path, base_directory)
        except SecurityError as e:
            logger.error(f"Invalid server directory path for server {server.id}: {e}")
            raise FileOperationException(
                "validate_path",
                str(server.directory_path),
                f"Security validation failed: {e}",
            ) from e

        if not server_path.exists():
            logger.error(
                f"Server directory {server_path} does not exist - "
                f"cannot sync files for server {server_id}"
            )
            return

        try:
            ops_data, whitelist_data = _build_ops_and_whitelist(groups)

            ops_file = server_path / "ops.json"
            with open(ops_file, "w", encoding="utf-8") as f:
                json.dump(ops_data, f, indent=2)
            logger.info(f"Updated ops.json at {ops_file} with {len(ops_data)} entries")

            whitelist_file = server_path / "whitelist.json"
            with open(whitelist_file, "w", encoding="utf-8") as f:
                json.dump(whitelist_data, f, indent=2)
            logger.info(
                f"Updated whitelist.json at {whitelist_file} with "
                f"{len(whitelist_data)} entries"
            )

            logger.info(f"Successfully synchronized server files for server {server_id}")
        except Exception as e:
            logger.error(f"Failed to update server files for server {server_id}: {e}")
            raise FileOperationException(
                "update", f"server {server_id} files", str(e)
            ) from e

        # Best-effort real-time commands: failures here must not fail
        # the file sync (matches legacy semantics).
        try:
            has_whitelist = any(g.type == GroupType.whitelist for g in groups)
            if has_whitelist:
                await self._real_time_commands.reload_whitelist_if_running(server_id)
            has_op = any(g.type == GroupType.op for g in groups)
            if has_op:
                await self._real_time_commands.sync_op_changes_if_running(
                    server_id, server_path
                )
        except Exception as cmd_error:
            logger.warning(
                f"Failed to send real-time commands to server {server_id}: {cmd_error}"
            )

    async def batch_update_server_files(self, server_ids: List[int]) -> None:
        """Update files for many servers; collect per-server failures.

        Raises `FileOperationException` once at the end if **any**
        server failed (matches legacy behaviour where the caller's
        retry wrapper interprets the aggregate failure).
        """
        if not server_ids:
            return

        failed_updates: List[tuple[int, str]] = []
        for server_id in server_ids:
            try:
                await self.update_server_files(server_id)
            except Exception as e:
                logger.error(f"Failed to update server files for server {server_id}: {e}")
                failed_updates.append((server_id, str(e)))

        if failed_updates:
            error_details = "; ".join(
                f"Server {sid}: {err}" for sid, err in failed_updates
            )
            raise FileOperationException("update", "multiple server files", error_details)

    async def update_all_affected_servers(self, group_id: int) -> None:
        """Update files for every server the group is attached to."""
        server_ids = await self._server_groups.list_server_ids_for_group(group_id)
        if server_ids:
            await self.batch_update_server_files(server_ids)

    async def update_all_affected_servers_with_retry(
        self,
        group_id: int,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Update files for every attached server, with bounded retry.

        Three attempts × exponential backoff. Raises
        `FileOperationException` if all attempts fail.
        """
        last_exception: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                await self.update_all_affected_servers(group_id)
                if attempt > 0:
                    logger.info(
                        f"Server file sync succeeded on attempt {attempt + 1} "
                        f"for group {group_id}"
                    )
                return
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Server file sync attempt {attempt + 1} failed for "
                    f"group {group_id}: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))

        logger.error(
            f"All {max_retries} attempts to sync server files failed for group {group_id}"
        )
        raise FileOperationException(
            "sync",
            f"server files (after {max_retries} attempts)",
            str(last_exception),
        ) from last_exception

    async def update_single_server_with_retry(
        self,
        server_id: int,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Single-server variant used by attach: same retry semantics."""
        for attempt in range(max_retries):
            try:
                await self.update_server_files(server_id)
                if attempt > 0:
                    logger.info(
                        f"Server file sync succeeded on attempt {attempt + 1} "
                        f"for server {server_id}"
                    )
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Server file sync attempt {attempt + 1} failed for "
                        f"server {server_id}: {e}"
                    )
                    await asyncio.sleep(retry_delay * (attempt + 1))
                else:
                    raise
