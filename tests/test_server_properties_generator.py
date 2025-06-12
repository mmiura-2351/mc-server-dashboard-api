import pytest
from unittest.mock import Mock, patch

from app.services.server_properties_generator import ServerPropertiesGenerator
from app.servers.models import Server, ServerType
from app.servers.schemas import ServerCreateRequest
from app.users.models import User


class TestServerPropertiesGenerator:
    """Test cases for ServerPropertiesGenerator"""

    def test_init(self):
        """Test generator initialization"""
        generator = ServerPropertiesGenerator()
        assert "1.8-1.12" in generator.version_groups
        assert "1.13-1.15" in generator.version_groups
        assert "1.16-1.18" in generator.version_groups
        assert "1.19-1.20" in generator.version_groups
        assert "1.21+" in generator.version_groups

    def test_get_version_group_1_8(self):
        """Test version group detection for 1.8-1.12"""
        generator = ServerPropertiesGenerator()
        
        assert generator._get_version_group("1.8.0") == "1.8-1.12"
        assert generator._get_version_group("1.10.2") == "1.8-1.12"
        assert generator._get_version_group("1.12.2") == "1.8-1.12"

    def test_get_version_group_1_13(self):
        """Test version group detection for 1.13-1.15"""
        generator = ServerPropertiesGenerator()
        
        assert generator._get_version_group("1.13.0") == "1.13-1.15"
        assert generator._get_version_group("1.14.4") == "1.13-1.15"
        assert generator._get_version_group("1.15.2") == "1.13-1.15"

    def test_get_version_group_1_16(self):
        """Test version group detection for 1.16-1.18"""
        generator = ServerPropertiesGenerator()
        
        assert generator._get_version_group("1.16.0") == "1.16-1.18"
        assert generator._get_version_group("1.17.1") == "1.16-1.18"
        assert generator._get_version_group("1.18.2") == "1.16-1.18"

    def test_get_version_group_1_19(self):
        """Test version group detection for 1.19-1.20"""
        generator = ServerPropertiesGenerator()
        
        assert generator._get_version_group("1.19.0") == "1.19-1.20"
        assert generator._get_version_group("1.19.4") == "1.19-1.20"
        assert generator._get_version_group("1.20.1") == "1.19-1.20"

    def test_get_version_group_1_21(self):
        """Test version group detection for 1.21+"""
        generator = ServerPropertiesGenerator()
        
        assert generator._get_version_group("1.21.0") == "1.21+"
        assert generator._get_version_group("1.22.0") == "1.21+"
        assert generator._get_version_group("2.0.0") == "1.21+"

    def test_get_version_group_invalid(self):
        """Test version group detection for invalid versions"""
        generator = ServerPropertiesGenerator()
        
        # Should default to 1.19-1.20 for invalid versions
        assert generator._get_version_group("invalid") == "1.19-1.20"
        assert generator._get_version_group("1.x.y") == "1.19-1.20"

    def test_get_base_properties(self, admin_user):
        """Test base properties generation"""
        generator = ServerPropertiesGenerator()
        
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            port=25565,
            max_players=20,
        )
        
        request = ServerCreateRequest(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            description="Test server"
        )
        
        properties = generator._get_base_properties(server, request)
        
        assert properties["server-port"] == "25565"
        assert properties["motd"] == "Test server"
        assert properties["max-players"] == "20"
        assert properties["difficulty"] == "normal"
        assert properties["gamemode"] == "survival"
        assert properties["level-name"] == "world"
        assert properties["online-mode"] == "true"
        assert properties["pvp"] == "true"

    def test_get_version_specific_properties_1_8(self):
        """Test version-specific properties for 1.8-1.12"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_version_specific_properties("1.10.2")
        
        assert "announce-player-achievements" in properties
        assert properties["announce-player-achievements"] == "true"
        assert "enable-rcon" in properties
        assert "rcon.port" in properties

    def test_get_version_specific_properties_1_13(self):
        """Test version-specific properties for 1.13-1.15"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_version_specific_properties("1.14.4")
        
        assert "level-type" in properties
        assert properties["level-type"] == "default"
        assert "function-permission-level" in properties
        assert properties["function-permission-level"] == "2"
        # Should not have old properties
        assert "announce-player-achievements" not in properties

    def test_get_version_specific_properties_1_16(self):
        """Test version-specific properties for 1.16-1.18"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_version_specific_properties("1.17.1")
        
        assert properties["level-type"] == "minecraft:normal"
        assert "simulation-distance" in properties
        assert properties["simulation-distance"] == "10"
        assert "level-seed" in properties

    def test_get_version_specific_properties_1_19(self):
        """Test version-specific properties for 1.19-1.20"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_version_specific_properties("1.20.1")
        
        assert "enforce-secure-profile" in properties
        assert properties["enforce-secure-profile"] == "true"
        assert "hide-online-players" in properties
        assert properties["hide-online-players"] == "false"

    def test_get_version_specific_properties_1_21(self):
        """Test version-specific properties for 1.21+"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_version_specific_properties("1.21.0")
        
        assert "log-ips" in properties
        assert properties["log-ips"] == "true"
        assert "enforce-secure-profile" in properties

    def test_get_server_type_properties_vanilla(self):
        """Test server type properties for vanilla"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_server_type_properties(ServerType.vanilla, "1.20.1")
        
        # Vanilla should have minimal type-specific properties
        assert len(properties) == 0

    def test_get_server_type_properties_paper(self):
        """Test server type properties for Paper"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_server_type_properties(ServerType.paper, "1.20.1")
        
        assert "use-native-transport" in properties
        assert properties["use-native-transport"] == "true"

    def test_get_server_type_properties_paper_modern(self):
        """Test server type properties for Paper on modern versions"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_server_type_properties(ServerType.paper, "1.18.2")
        
        assert "sync-chunk-writes" in properties
        assert properties["sync-chunk-writes"] == "true"

    def test_get_server_type_properties_forge(self):
        """Test server type properties for Forge"""
        generator = ServerPropertiesGenerator()
        
        properties = generator._get_server_type_properties(ServerType.forge, "1.20.1")
        
        # Forge should have minimal server.properties changes
        assert len(properties) == 0

    def test_normalize_user_properties(self):
        """Test user properties normalization"""
        generator = ServerPropertiesGenerator()
        
        user_props = {
            "server_port": 25566,
            "max_players": 30,
            "pvp": True,
            "difficulty": "hard",
            "custom_prop": "value"
        }
        
        normalized = generator._normalize_user_properties(user_props)
        
        assert normalized["server-port"] == "25566"
        assert normalized["max-players"] == "30"
        assert normalized["pvp"] == "true"
        assert normalized["difficulty"] == "hard"
        assert normalized["custom-prop"] == "value"

    def test_generate_properties_integration(self, admin_user):
        """Test complete properties generation integration"""
        generator = ServerPropertiesGenerator()
        
        server = Server(
            name="integration-server",
            minecraft_version="1.20.1",
            server_type=ServerType.paper,
            owner_id=admin_user.id,
            port=25565,
            max_players=30,
        )
        
        request = ServerCreateRequest(
            name="integration-server",
            minecraft_version="1.20.1",
            server_type=ServerType.paper,
            description="Integration test server",
            server_properties={
                "difficulty": "hard",
                "pvp": False,
                "level_name": "custom_world"
            }
        )
        
        properties = generator.generate_properties(server, "1.20.1", request)
        
        # Check base properties
        assert properties["server-port"] == "25565"
        assert properties["motd"] == "Integration test server"
        assert properties["max-players"] == "30"
        
        # Check version-specific properties (1.19-1.20 group)
        assert "enforce-secure-profile" in properties
        
        # Check server type properties (Paper)
        assert "use-native-transport" in properties
        
        # Check user overrides (highest priority)
        assert properties["difficulty"] == "hard"
        assert properties["pvp"] == "false"
        assert properties["level-name"] == "custom_world"

    def test_get_available_properties_for_version(self, admin_user):
        """Test getting available properties metadata for a version"""
        generator = ServerPropertiesGenerator()
        
        metadata = generator.get_available_properties_for_version("1.20.1", ServerType.vanilla)
        
        assert isinstance(metadata, dict)
        assert "server-port" in metadata
        assert "type" in metadata["server-port"]
        assert "description" in metadata["server-port"]
        assert "version_group" in metadata["server-port"]

    def test_infer_property_type(self):
        """Test property type inference"""
        generator = ServerPropertiesGenerator()
        
        assert generator._infer_property_type("pvp", "true") == "boolean"
        assert generator._infer_property_type("pvp", "false") == "boolean"
        assert generator._infer_property_type("max-players", "20") == "integer"
        assert generator._infer_property_type("motd", "Hello World") == "string"
        assert generator._infer_property_type("level-seed", "") == "long"

    def test_get_property_description(self):
        """Test property description retrieval"""
        generator = ServerPropertiesGenerator()
        
        desc = generator._get_property_description("server-port")
        assert "port" in desc.lower()
        
        desc = generator._get_property_description("max-players")
        assert "maximum" in desc.lower() and "players" in desc.lower()
        
        desc = generator._get_property_description("unknown-property")
        assert "Minecraft server property" in desc

    def test_properties_priority_order(self, admin_user):
        """Test that properties follow correct priority order"""
        generator = ServerPropertiesGenerator()
        
        server = Server(
            name="priority-test",
            minecraft_version="1.20.1",
            server_type=ServerType.paper,
            owner_id=admin_user.id,
            port=25565,
            max_players=20,
        )
        
        # Base properties set difficulty to "normal"
        # Version properties don't override difficulty
        # Server type properties don't override difficulty
        # User properties set difficulty to "hard" (should win)
        request = ServerCreateRequest(
            name="priority-test",
            minecraft_version="1.20.1",
            server_type=ServerType.paper,
            server_properties={
                "difficulty": "hard"  # User override
            }
        )
        
        properties = generator.generate_properties(server, "1.20.1", request)
        
        # User property should have highest priority
        assert properties["difficulty"] == "hard"
        
        # Base properties should still be present
        assert properties["server-port"] == "25565"
        
        # Version-specific properties should be present
        assert "enforce-secure-profile" in properties
        
        # Server type properties should be present
        assert "use-native-transport" in properties