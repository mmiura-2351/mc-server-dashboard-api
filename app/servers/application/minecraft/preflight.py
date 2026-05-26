"""Pre-start checks: Java, EULA, RCON config, sync, port validation."""

import os
import secrets
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from app.servers.application.minecraft._compat import (
    java_compatibility_service,
    logger,
)
from app.servers.domain.entities import ServerEntity
from app.servers.domain.ports import ServerRepository
from app.servers.models import ServerStatus


class PreflightMixin:
    """Mixin: server start preflight checks (Java/EULA/RCON/sync/port)."""

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

    def _generate_rcon_password(self) -> str:
        """Generate a secure RCON password"""
        return secrets.token_urlsafe(32)

    def _find_available_rcon_port(self, base_port: int = 25575) -> int:
        """Find an available RCON port starting from base_port"""
        for port in range(base_port, base_port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("localhost", port))
                    return port
            except OSError:
                continue
        raise RuntimeError("No available RCON ports found")

    async def _perform_bidirectional_sync(
        self,
        server: ServerEntity,
        server_dir: Path,
        server_repository: Optional[ServerRepository] = None,
    ) -> Tuple[bool, ServerEntity]:
        """
        Perform simplified sync between database and server.properties.

        Key Logic (Simplified):
        - API updates always modify both DB and file simultaneously
        - Manual file edits only modify the file
        - Therefore: if DB and file differ, file was manually edited and should sync to DB
        - This eliminates complex timestamp comparisons

        Returns ``(success, post_sync_entity)``. The returned entity is
        the updated frozen ``ServerEntity`` when a file→DB sync ran, or
        the input entity otherwise. Callers should use the returned
        entity for all subsequent reads of ``port`` so they observe the
        post-sync value (the input entity stays unchanged because
        ``ServerEntity`` is frozen).
        """
        try:
            from app.servers.application.simplified_sync import simplified_sync_service

            properties_path = server_dir / "server.properties"

            # DEBUG: Log sync parameters
            logger.info(f"DEBUG: Starting sync for server {server.id}")
            logger.info(
                f"DEBUG: server_repository provided: "
                f"{'YES' if server_repository else 'NO'}"
            )
            logger.info(f"DEBUG: Properties file exists: {properties_path.exists()}")

            if properties_path.exists():
                file_port = simplified_sync_service.get_properties_file_port(
                    properties_path
                )
                logger.info(f"DEBUG: File port: {file_port}, DB port: {server.port}")

            if server_repository is not None:
                (
                    success,
                    description,
                    updated,
                ) = await simplified_sync_service.perform_simplified_sync(
                    server, properties_path, server_repository
                )
                logger.info(
                    f"Simplified sync for server {server.id}: success={success}, {description}"
                )

                # Surface the post-sync entity (frozen + repo-managed)
                # to the caller so subsequent reads of ``port`` see the
                # value just flushed to the DB. No ``db.refresh(server)``
                # needed any more — the repository returns the canonical
                # post-update entity directly (#272).
                resulting_entity = updated if updated is not None else server

                if success and updated is not None:
                    file_port_after = simplified_sync_service.get_properties_file_port(
                        properties_path
                    )
                    logger.info(
                        f"DEBUG: After sync - File port: {file_port_after}, "
                        f"DB port: {resulting_entity.port}"
                    )

                return success, resulting_entity
            else:
                # Fallback to database-to-file sync if no repository
                logger.warning(
                    f"No server repository provided for server {server.id}, falling back to database-to-file sync"
                )
                ok = await self._sync_server_properties_from_database(server, server_dir)
                return ok, server

        except Exception as e:
            logger.error(f"Failed to perform simplified sync for server {server.id}: {e}")
            return False, server

    async def _sync_server_properties_from_database(
        self, server: ServerEntity, server_dir: Path
    ) -> bool:
        """Sync server.properties with database values to ensure consistency"""
        try:
            properties_path = server_dir / "server.properties"

            # Read existing properties
            properties = {}
            if properties_path.exists():
                with open(properties_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            properties[key] = value

            # Update critical properties from database
            properties["server-port"] = str(server.port)
            properties["max-players"] = str(server.max_players)

            # Write updated properties back
            with open(properties_path, "w", encoding="utf-8") as f:
                f.write("#Minecraft server properties\n")
                f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
                for key, value in sorted(properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(
                f"Synced server.properties for server {server.id}: "
                f"port={server.port}, max-players={server.max_players}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to sync server.properties for server {server.id}: {e}")
            return False

    async def _ensure_rcon_configured(
        self, server_dir: Path, server_id: int
    ) -> tuple[bool, int, str]:
        """Ensure RCON is configured in server.properties"""
        try:
            properties_path = server_dir / "server.properties"
            rcon_port = self._find_available_rcon_port()
            rcon_password = self._generate_rcon_password()

            # Read existing properties if file exists
            properties = {}
            if properties_path.exists():
                with open(properties_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            properties[key] = value

            # Update RCON settings
            properties.update(
                {
                    "enable-rcon": "true",
                    "rcon.port": str(rcon_port),
                    "rcon.password": rcon_password,
                    "broadcast-rcon-to-ops": "true",
                }
            )

            # Write updated properties back
            with open(properties_path, "w", encoding="utf-8") as f:
                f.write("#Minecraft server properties\n")
                f.write(f"#{datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}\n")
                for key, value in sorted(properties.items()):
                    f.write(f"{key}={value}\n")

            logger.info(f"Configured RCON for server {server_id}: port={rcon_port}")
            return True, rcon_port, rcon_password

        except Exception as e:
            logger.error(f"Failed to configure RCON for server {server_id}: {e}")
            return False, 0, ""

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
        self,
        server: ServerEntity,
        server_repository: Optional[ServerRepository] = None,
        *,
        _for_test_default: bool = False,
    ) -> tuple[bool, str]:
        """Validate that the server's port is not already in use by another running server

        This method checks both:
        1. Database for servers using the same port and currently running/starting
        2. System-level port availability for external processes

        Production callers MUST pass an explicit ``ServerRepository`` so the
        database conflict check actually runs. Silently skipping the DB
        check when production forgets to wire the repository would let a
        port conflict slip past pre-flight validation (#281); we therefore
        fail loud with ``RuntimeError`` in that case.

        ``_for_test_default`` is a test-only escape hatch: it acknowledges
        that the caller intentionally wants the socket-only probe (no DB
        check) and suppresses the ``RuntimeError`` guard. Production code
        MUST NOT set this flag.
        """
        if server_repository is None and not _for_test_default:
            raise RuntimeError(
                "_validate_port_availability requires an explicit ServerRepository "
                "in production code paths to perform the database port-conflict "
                "check. Pass `server_repository=...`, or set "
                "`_for_test_default=True` in test-only contexts that intentionally "
                "exercise the socket-only probe."
            )
        try:
            # First check database for servers using the same port through
            # the injected ``ServerRepository``. Callers pass the
            # already-built repository in alongside the entity (#272,
            # #285), mirroring the rest of the application layer.
            if server_repository is not None:
                conflicts = await server_repository.list_by_port(
                    server.port,
                    statuses=[ServerStatus.running, ServerStatus.starting],
                    exclude_id=server.id,
                )
                conflicting_server = conflicts[0] if conflicts else None

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
