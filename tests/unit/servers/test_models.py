"""
Comprehensive test coverage for servers models
Tests all model methods and properties for 100% coverage
"""

from app.servers.models import ServerStatus, ServerType


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

        # Verify enum exists and has values
        assert hasattr(ServerType, "vanilla")

        # Test common server types
        server_types = list(ServerType)
        assert len(server_types) > 0
