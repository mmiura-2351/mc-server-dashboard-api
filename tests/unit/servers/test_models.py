"""
Comprehensive test coverage for servers models
Tests all model methods and properties for 100% coverage
"""

import pytest
import json
from datetime import datetime

from app.servers.models import ServerStatus, ServerType, Template


class TestTemplate:
    """Test cases for Template model methods"""

    @pytest.fixture
    def template_instance(self):
        """Create a Template instance for testing"""
        from app.servers.models import ServerType
        template = Template()
        template.id = 1
        template.name = "test-template"
        template.description = "Test template"
        template.minecraft_version = "1.20.1"
        template.server_type = ServerType.vanilla
        template.created_by = 1
        template.configuration = '{"difficulty": "easy", "max-players": 20}'
        template.default_groups = '{"op_groups": [1, 2], "whitelist_groups": [3, 4]}'
        template.created_at = datetime.now()
        template.updated_at = datetime.now()
        return template

    def test_get_configuration_from_string(self, template_instance):
        """Test get_configuration when configuration is a string"""
        # Ensure configuration is stored as string
        template_instance.configuration = '{"difficulty": "hard", "pvp": true}'
        
        result = template_instance.get_configuration()
        
        assert isinstance(result, dict)
        assert result["difficulty"] == "hard"
        assert result["pvp"] is True

    def test_get_configuration_from_dict(self):
        """Test get_configuration when configuration is already a dict"""
        template = Template()
        config_dict = {"mode": "survival", "spawn-protection": 16}
        template.configuration = config_dict
        
        result = template.get_configuration()
        
        assert result == config_dict
        assert result["mode"] == "survival"
        assert result["spawn-protection"] == 16

    def test_get_configuration_none(self):
        """Test get_configuration when configuration is None"""
        template = Template()
        template.configuration = None
        
        result = template.get_configuration()
        
        assert result == {}

    def test_set_configuration(self):
        """Test set_configuration method"""
        template = Template()
        config = {"gamemode": "creative", "allow-flight": True}
        
        template.set_configuration(config)
        
        assert template.configuration == config

    def test_get_default_groups_from_string(self, template_instance):
        """Test get_default_groups when default_groups is a string"""
        # Ensure default_groups is stored as string
        template_instance.default_groups = '{"op_groups": [5, 6], "whitelist_groups": [7]}'
        
        result = template_instance.get_default_groups()
        
        assert isinstance(result, dict)
        assert result["op_groups"] == [5, 6]
        assert result["whitelist_groups"] == [7]

    def test_get_default_groups_from_dict(self):
        """Test get_default_groups when default_groups is already a dict"""
        template = Template()
        groups_dict = {"op_groups": [10, 11], "whitelist_groups": [12, 13]}
        template.default_groups = groups_dict
        
        result = template.get_default_groups()
        
        assert result == groups_dict
        assert result["op_groups"] == [10, 11]
        assert result["whitelist_groups"] == [12, 13]

    def test_get_default_groups_none(self):
        """Test get_default_groups when default_groups is None"""
        template = Template()
        template.default_groups = None
        
        result = template.get_default_groups()
        
        assert result == {"op_groups": [], "whitelist_groups": []}

    def test_set_default_groups(self):
        """Test set_default_groups method"""
        template = Template()
        groups = {"op_groups": [20, 21], "whitelist_groups": [22, 23]}
        
        template.set_default_groups(groups)
        
        assert template.default_groups == groups

    def test_template_initialization(self):
        """Test Template model can be initialized properly"""
        template = Template()
        template.name = "init-test"
        template.description = "Initialization test"
        template.created_by = 99
        
        assert template.name == "init-test"
        assert template.description == "Initialization test"
        assert template.created_by == 99

    def test_template_json_serialization_roundtrip(self):
        """Test JSON serialization and deserialization works correctly"""
        template = Template()
        
        # Test configuration
        original_config = {"complex": {"nested": {"value": 42}}, "list": [1, 2, 3]}
        template.set_configuration(original_config)
        retrieved_config = template.get_configuration()
        assert retrieved_config == original_config
        
        # Test default groups
        original_groups = {"op_groups": [100, 200], "whitelist_groups": [300]}
        template.set_default_groups(original_groups)
        retrieved_groups = template.get_default_groups()
        assert retrieved_groups == original_groups

    def test_template_empty_values(self):
        """Test Template methods with empty values"""
        template = Template()
        
        # Test empty string configuration - should raise JSONDecodeError
        template.configuration = ""
        with pytest.raises(json.JSONDecodeError):
            template.get_configuration()
        
        # Test empty string default_groups - should raise JSONDecodeError
        template.default_groups = ""
        with pytest.raises(json.JSONDecodeError):
            template.get_default_groups()

    def test_template_invalid_json_handling(self):
        """Test Template methods handle invalid JSON gracefully"""
        template = Template()
        
        # Invalid JSON should raise an exception
        template.configuration = '{"invalid": json}'
        with pytest.raises(json.JSONDecodeError):
            template.get_configuration()
            
        template.default_groups = '{"invalid": json}'
        with pytest.raises(json.JSONDecodeError):
            template.get_default_groups()


class TestServerStatus:
    """Test cases for ServerStatus enum"""

    def test_server_status_values(self):
        """Test ServerStatus enum has expected values"""
        assert ServerStatus.stopped.value == "stopped"
        assert ServerStatus.starting.value == "starting"
        assert ServerStatus.running.value == "running"
        assert ServerStatus.stopping.value == "stopping"
        assert ServerStatus.error.value == "error"

    def test_server_status_enum_membership(self):
        """Test ServerStatus enum membership"""
        all_statuses = list(ServerStatus)
        assert len(all_statuses) == 5
        assert ServerStatus.stopped in all_statuses
        assert ServerStatus.running in all_statuses


class TestServerType:
    """Test cases for ServerType enum"""

    def test_server_type_values(self):
        """Test ServerType enum has expected values"""
        from app.servers.models import ServerType
        
        # Verify enum exists and has values
        assert hasattr(ServerType, 'vanilla')
        
        # Test common server types
        server_types = list(ServerType)
        assert len(server_types) > 0