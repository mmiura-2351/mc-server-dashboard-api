import logging
from typing import Any, Dict

from packaging import version

from app.servers.models import Server, ServerType
from app.servers.schemas import ServerCreateRequest

logger = logging.getLogger(__name__)


class ServerPropertiesGenerator:
    """Dynamic server.properties generation based on version and server type"""

    def __init__(self):
        # Version groups for property compatibility
        self.version_groups = {
            "1.8-1.12": {"min": "1.8.0", "max": "1.12.99"},
            "1.13-1.15": {"min": "1.13.0", "max": "1.15.99"},
            "1.16-1.18": {"min": "1.16.0", "max": "1.18.99"},
            "1.19-1.20": {"min": "1.19.0", "max": "1.20.99"},
            "1.21+": {"min": "1.21.0", "max": "9.99.99"},
        }

    def generate_properties(
        self, server: Server, minecraft_version: str, request: ServerCreateRequest
    ) -> Dict[str, str]:
        """Generate version-specific server.properties"""

        # Priority order: Base → Version-specific → Server type-specific → User overrides
        properties = {}

        # 1. Base properties (common to all versions)
        properties.update(self._get_base_properties(server, request))

        # 2. Version-specific properties
        properties.update(self._get_version_specific_properties(minecraft_version))

        # 3. Server type-specific properties
        properties.update(
            self._get_server_type_properties(server.server_type, minecraft_version)
        )

        # 4. User overrides (highest priority)
        if request.server_properties:
            properties.update(self._normalize_user_properties(request.server_properties))

        logger.info(
            f"Generated {len(properties)} properties for {server.name} "
            f"({server.server_type.value} {minecraft_version})"
        )

        return properties

    def _get_base_properties(
        self, server: Server, request: ServerCreateRequest
    ) -> Dict[str, str]:
        """Get base properties common to all versions"""
        return {
            # Server identification
            "server-port": str(server.port),
            "motd": request.description or f"A Minecraft Server - {server.name}",
            "max-players": str(server.max_players),
            # Basic world settings
            "level-name": "world",
            "level-type": "minecraft:normal",
            "difficulty": "normal",
            "gamemode": "survival",
            "hardcore": "false",
            # Network settings
            "online-mode": "true",
            "enable-status": "true",
            "enable-query": "false",
            "query.port": str(server.port),
            # Performance settings
            "view-distance": "10",
            "spawn-protection": "16",
            # Basic gameplay
            "allow-nether": "true",
            "allow-flight": "false",
            "pvp": "true",
            "spawn-monsters": "true",
            "spawn-animals": "true",
            "spawn-npcs": "true",
            "generate-structures": "true",
            # Security
            "white-list": "false",
            "enforce-whitelist": "false",
            "enable-command-block": "false",
            "op-permission-level": "4",
            # Resource packs
            "resource-pack": "",
            "resource-pack-sha1": "",
            "require-resource-pack": "false",
        }

    def _get_version_specific_properties(self, minecraft_version: str) -> Dict[str, str]:
        """Get properties specific to version groups"""
        version_group = self._get_version_group(minecraft_version)
        properties = {}

        if version_group == "1.8-1.12":
            properties.update(
                {
                    "announce-player-achievements": "true",
                    "enable-rcon": "false",
                    "rcon.port": "25575",
                    "rcon.password": "",
                }
            )

        elif version_group == "1.13-1.15":
            properties.update(
                {
                    # 1.13 introduced new world generation
                    "level-type": "default",
                    "generator-settings": "",
                    "enable-rcon": "false",
                    "rcon.port": "25575",
                    "rcon.password": "",
                    # 1.13+ function permissions
                    "function-permission-level": "2",
                }
            )

        elif version_group == "1.16-1.18":
            properties.update(
                {
                    # 1.16+ settings
                    "level-type": "minecraft:normal",
                    "enable-rcon": "false",
                    "rcon.port": "25575",
                    "rcon.password": "",
                    "function-permission-level": "2",
                    # 1.16 simulation distance
                    "simulation-distance": "10",
                    # 1.17+ new cave generation
                    "level-seed": "",
                }
            )

        elif version_group == "1.19-1.20":
            properties.update(
                {
                    # 1.19+ properties
                    "level-type": "minecraft:normal",
                    "enable-rcon": "false",
                    "rcon.port": "25575",
                    "rcon.password": "",
                    "function-permission-level": "2",
                    "simulation-distance": "10",
                    "level-seed": "",
                    # 1.19 chat reporting
                    "enforce-secure-profile": "true",
                    # 1.20 specific
                    "hide-online-players": "false",
                }
            )

        elif version_group == "1.21+":
            properties.update(
                {
                    # Future version properties
                    "level-type": "minecraft:normal",
                    "enable-rcon": "false",
                    "rcon.port": "25575",
                    "rcon.password": "",
                    "function-permission-level": "2",
                    "simulation-distance": "10",
                    "level-seed": "",
                    "enforce-secure-profile": "true",
                    "hide-online-players": "false",
                    # Potential new properties for 1.21+
                    "log-ips": "true",
                }
            )

        return properties

    def _get_server_type_properties(
        self, server_type: ServerType, minecraft_version: str
    ) -> Dict[str, str]:
        """Get server type-specific properties"""
        properties = {}

        if server_type == ServerType.paper:
            # Paper-specific optimizations
            properties.update(
                {
                    # Paper performance settings
                    "use-native-transport": "true",
                    # Paper async chunk loading (1.14+)
                }
            )

            # Version-specific Paper settings
            version_group = self._get_version_group(minecraft_version)
            if version_group in ["1.16-1.18", "1.19-1.20", "1.21+"]:
                properties.update(
                    {
                        "sync-chunk-writes": "true",
                    }
                )

        elif server_type == ServerType.forge:
            # Forge-specific settings
            properties.update(
                {
                    # Forge typically doesn't need special server.properties
                    # Most configuration is in forge-specific config files
                }
            )

        # Vanilla doesn't need additional properties

        return properties

    def _get_version_group(self, minecraft_version: str) -> str:
        """Determine which version group a version belongs to"""
        try:
            parsed_version = version.Version(minecraft_version)

            for group_name, group_range in self.version_groups.items():
                min_version = version.Version(group_range["min"])
                max_version = version.Version(group_range["max"])

                if min_version <= parsed_version <= max_version:
                    return group_name

        except Exception as e:
            logger.warning(f"Failed to parse version {minecraft_version}: {e}")

        # Default to latest group if parsing fails
        return "1.19-1.20"

    def _normalize_user_properties(
        self, user_properties: Dict[str, Any]
    ) -> Dict[str, str]:
        """Normalize user-provided properties to string values"""
        normalized = {}

        for key, value in user_properties.items():
            # Convert key format (underscore to hyphen)
            normalized_key = key.replace("_", "-")

            # Convert value to string
            if isinstance(value, bool):
                normalized_value = str(value).lower()
            elif isinstance(value, (int, float)):
                normalized_value = str(value)
            else:
                normalized_value = str(value)

            normalized[normalized_key] = normalized_value

        return normalized

    def get_available_properties_for_version(
        self, minecraft_version: str, server_type: ServerType
    ) -> Dict[str, Any]:
        """Get all available properties for a specific version and type with metadata"""
        version_group = self._get_version_group(minecraft_version)

        # Create dummy objects for property generation
        from app.users.models import User

        dummy_user = User(id=1, username="dummy")
        dummy_server = Server(
            id=1,
            name="dummy",
            port=25565,
            max_players=20,
            server_type=server_type,
            minecraft_version=minecraft_version,
            owner=dummy_user,
        )
        dummy_request = ServerCreateRequest(
            name="dummy", minecraft_version=minecraft_version, server_type=server_type
        )

        properties = self.generate_properties(
            dummy_server, minecraft_version, dummy_request
        )

        # Add metadata about each property
        property_metadata = {}
        for prop_key, prop_value in properties.items():
            property_metadata[prop_key] = {
                "default_value": prop_value,
                "type": self._infer_property_type(prop_key, prop_value),
                "description": self._get_property_description(prop_key),
                "version_group": version_group,
            }

        return property_metadata

    def _infer_property_type(self, key: str, value: str) -> str:
        """Infer the type of a property"""
        if value.lower() in ["true", "false"]:
            return "boolean"
        elif value.isdigit():
            return "integer"
        elif key in ["level-seed"] and value == "":
            return "long"
        else:
            return "string"

    def _get_property_description(self, key: str) -> str:
        """Get human-readable description for a property"""
        descriptions = {
            "server-port": "The port the server listens on",
            "motd": "Message of the day displayed in server list",
            "max-players": "Maximum number of concurrent players",
            "difficulty": "Game difficulty (peaceful, easy, normal, hard)",
            "gamemode": "Default game mode (survival, creative, adventure, spectator)",
            "level-name": "Name of the world folder",
            "level-type": "Type of world generation",
            "pvp": "Enable player vs player combat",
            "view-distance": "Maximum chunk view distance",
            "simulation-distance": "Maximum chunk simulation distance",
            "online-mode": "Verify players against Minecraft account database",
            "white-list": "Enable whitelist for player access control",
            "enforce-whitelist": "Kick non-whitelisted players immediately",
            "spawn-protection": "Blocks radius around spawn protected from non-ops",
            "enable-command-block": "Allow command blocks to function",
            "op-permission-level": "Default op permission level (1-4)",
        }

        return descriptions.get(key, f"Minecraft server property: {key}")


# Global instance
server_properties_generator = ServerPropertiesGenerator()
