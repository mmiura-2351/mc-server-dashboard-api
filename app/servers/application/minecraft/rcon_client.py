"""Minecraft RCON client used for runtime command delivery."""

import asyncio
import logging
import socket
import struct
from typing import Optional

logger = logging.getLogger(__name__)


class MinecraftRCONClient:
    """RCON client for sending commands to Minecraft servers"""

    def __init__(self):
        self.socket = None
        self.request_id = 0

    async def connect(
        self, host: str, port: int, password: str, timeout: float = 5.0
    ) -> bool:
        """Connect to RCON server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(timeout)
            await asyncio.get_event_loop().run_in_executor(
                None, self.socket.connect, (host, port)
            )

            # Send authentication packet
            auth_success = await self._authenticate(password)
            if not auth_success:
                await self.disconnect()
                return False

            logger.debug(f"RCON connected to {host}:{port}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to RCON {host}:{port}: {e}")
            await self.disconnect()
            return False

    async def _authenticate(self, password: str) -> bool:
        """Authenticate with RCON server"""
        try:
            self.request_id += 1
            packet = self._create_packet(self.request_id, 3, password)  # Type 3 = LOGIN
            await self._send_packet(packet)

            response = await self._receive_packet()

            if response:
                response_id, response_type, response_payload = response

                # Check for authentication failure (response ID -1)
                if response_id == -1:
                    logger.error("RCON authentication failed: Invalid password")
                    return False

                # Check for successful authentication (matching request ID)
                if response_id == self.request_id:
                    logger.debug("RCON authentication successful")
                    return True

                logger.error(
                    f"RCON authentication failed: Unexpected response ID {response_id} (expected {self.request_id})"
                )
                return False
            else:
                logger.error("RCON authentication failed: No response received")
                return False

        except Exception as e:
            logger.error(f"RCON authentication failed: {e}")
            return False

    async def send_command(self, command: str) -> Optional[str]:
        """Send a command and return the response"""
        try:
            if not self.socket:
                return None

            self.request_id += 1
            packet = self._create_packet(self.request_id, 2, command)  # Type 2 = COMMAND
            await self._send_packet(packet)

            response = await self._receive_packet()
            if response and response[0] == self.request_id:
                return response[2]  # Return payload
            return None

        except Exception as e:
            logger.error(f"Failed to send RCON command '{command}': {e}")
            return None

    def _create_packet(self, request_id: int, packet_type: int, payload: str) -> bytes:
        """Create RCON packet"""
        payload_bytes = payload.encode("utf-8") + b"\x00\x00"
        # Size = request_id (4) + packet_type (4) + payload_bytes
        packet_size = 4 + 4 + len(payload_bytes)

        packet = struct.pack("<i", packet_size)  # Size (excluding size field itself)
        packet += struct.pack("<i", request_id)
        packet += struct.pack("<i", packet_type)
        packet += payload_bytes

        logger.debug(
            f"Created RCON packet: size={packet_size}, id={request_id}, type={packet_type}, payload_len={len(payload)}"
        )
        logger.debug(f"Payload bytes length: {len(payload_bytes)}")
        logger.debug(f"Packet bytes: {packet.hex()}")

        return packet

    async def _send_packet(self, packet: bytes):
        """Send packet to RCON server"""
        await asyncio.get_event_loop().run_in_executor(None, self.socket.sendall, packet)

    async def _receive_packet(self) -> Optional[tuple]:
        """Receive packet from RCON server"""
        try:
            # Read packet size
            logger.debug("Attempting to read RCON packet size...")
            size_data = await asyncio.get_event_loop().run_in_executor(
                None, self.socket.recv, 4
            )
            logger.debug(f"Received size data: {size_data} (length: {len(size_data)})")

            if len(size_data) != 4:
                logger.error(f"Invalid size data length: {len(size_data)} (expected 4)")
                return None

            size = struct.unpack("<i", size_data)[0]
            logger.debug(f"Packet size: {size}")

            if size <= 0 or size > 4096:  # Sanity check
                logger.error(f"Invalid packet size: {size}")
                return None

            # Read packet data
            logger.debug(f"Attempting to read {size} bytes of packet data...")
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.socket.recv, size
            )
            logger.debug(f"Received packet data: {data} (length: {len(data)})")

            if len(data) != size:
                logger.error(
                    f"Incomplete packet data: {len(data)} bytes (expected {size})"
                )
                return None

            request_id = struct.unpack("<i", data[0:4])[0]
            packet_type = struct.unpack("<i", data[4:8])[0]
            payload = data[8:-2].decode("utf-8")  # Remove null terminators

            logger.debug(
                f"Parsed packet: id={request_id}, type={packet_type}, payload='{payload}'"
            )

            return (request_id, packet_type, payload)

        except Exception as e:
            logger.error(f"Failed to receive RCON packet: {e}")
            import traceback

            logger.debug(f"Exception traceback: {traceback.format_exc()}")
            return None

    async def disconnect(self):
        """Disconnect from RCON server"""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
