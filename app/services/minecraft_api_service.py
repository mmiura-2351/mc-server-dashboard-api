import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class MinecraftAPIService:
    """Service for interacting with Minecraft APIs"""

    MOJANG_API_BASE = "https://api.mojang.com"
    MOJANG_SESSION_API = "https://sessionserver.mojang.com"

    @staticmethod
    async def get_uuid_from_username(username: str) -> Optional[str]:
        """
        Get player UUID from username using Mojang API

        Args:
            username: Minecraft username

        Returns:
            Player UUID if found, None otherwise
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{MinecraftAPIService.MOJANG_API_BASE}/users/profiles/minecraft/{username}"

                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        uuid = data.get("id")
                        if uuid:
                            # Format UUID with dashes
                            formatted_uuid = f"{uuid[:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]}"
                            return formatted_uuid
                    elif response.status == 404:
                        logger.warning(f"Player {username} not found in Mojang API")
                        return None
                    else:
                        logger.error(
                            f"Mojang API returned status {response.status} for username {username}"
                        )
                        return None

        except asyncio.TimeoutError:
            logger.error(f"Timeout when fetching UUID for username {username}")
            return None
        except Exception as e:
            logger.error(f"Error fetching UUID for username {username}: {str(e)}")
            return None

    @staticmethod
    async def get_username_from_uuid(uuid: str) -> Optional[str]:
        """
        Get current username from UUID using Mojang API

        Args:
            uuid: Player UUID (with or without dashes)

        Returns:
            Current username if found, None otherwise
        """
        try:
            # Remove dashes from UUID for API call
            clean_uuid = uuid.replace("-", "")

            async with aiohttp.ClientSession() as session:
                url = f"{MinecraftAPIService.MOJANG_SESSION_API}/session/minecraft/profile/{clean_uuid}"

                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("name")
                    elif response.status == 404:
                        logger.warning(f"UUID {uuid} not found in Mojang API")
                        return None
                    else:
                        logger.error(
                            f"Mojang API returned status {response.status} for UUID {uuid}"
                        )
                        return None

        except asyncio.TimeoutError:
            logger.error(f"Timeout when fetching username for UUID {uuid}")
            return None
        except Exception as e:
            logger.error(f"Error fetching username for UUID {uuid}: {str(e)}")
            return None

    @staticmethod
    def generate_offline_uuid(username: str) -> str:
        """
        Generate offline mode UUID for a username
        This is used when Mojang API is unavailable or for offline servers

        Args:
            username: Minecraft username

        Returns:
            Generated UUID based on username
        """
        import uuid
        import hashlib

        # Create a UUID based on the username using MD5 hash
        # This matches Minecraft's offline UUID generation
        # Use namespace for offline players as defined by Minecraft
        offline_string = f"OfflinePlayer:{username}"
        
        # Generate MD5 hash
        md5_hash = hashlib.md5(offline_string.encode('utf-8')).hexdigest()
        
        # Convert to UUID format (version 3, MD5 based)
        uuid_hex = md5_hash[:8] + '-' + md5_hash[8:12] + '-' + '3' + md5_hash[13:16] + '-' + md5_hash[16:20] + '-' + md5_hash[20:32]
        
        return uuid_hex
