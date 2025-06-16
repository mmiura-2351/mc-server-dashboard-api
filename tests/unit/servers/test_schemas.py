"""
Comprehensive test coverage for servers schemas
Tests validation logic and edge cases for 100% coverage
"""

import pytest
from pydantic import ValidationError

from app.servers.schemas import (
    ServerCreateRequest,
    ServerUpdateRequest,
    ServerResponse,
    ServerImportRequest,
    SupportedVersionsResponse,
    MinecraftVersionInfo
)
from app.servers.models import ServerType, ServerStatus


class TestServerCreateRequest:
    """Test cases for ServerCreateRequest validation"""

    def test_valid_server_create_request(self):
        """Test valid server creation request"""
        request = ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20
        )
        
        assert request.name == "test-server"
        assert request.minecraft_version == "1.20.1"
        assert request.server_type == ServerType.vanilla

    def test_server_name_empty_validation(self):
        """Test server name cannot be empty (line 42)"""
        with pytest.raises(ValidationError) as exc_info:
            ServerCreateRequest(
                name="   ",  # Empty name with spaces
                description="Test server",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                port=25565,
                max_memory=1024,
                max_players=20
            )
        
        assert "Server name cannot be empty" in str(exc_info.value)

    def test_server_name_invalid_characters(self):
        """Test server name with invalid characters (line 47)"""
        invalid_names = [
            "server@name",  # Contains @
            "server#name",  # Contains #
            "server$name",  # Contains $
            "server%name",  # Contains %
            "server&name",  # Contains &
            "server*name",  # Contains *
        ]
        
        for invalid_name in invalid_names:
            with pytest.raises(ValidationError) as exc_info:
                ServerCreateRequest(
                    name=invalid_name,
                    description="Test server",
                    minecraft_version="1.20.1",
                    server_type=ServerType.vanilla,
                    port=25565,
                    max_memory=1024,
                    max_players=20
                )
            
            assert "Server name contains invalid characters" in str(exc_info.value)

    def test_server_name_valid_characters(self):
        """Test server name with valid characters"""
        valid_names = [
            "server-name",    # Contains hyphen
            "server_name",    # Contains underscore
            "server name",    # Contains space
            "server123",      # Contains numbers
            "ServerName",     # Contains uppercase
        ]
        
        for valid_name in valid_names:
            request = ServerCreateRequest(
                name=valid_name,
                description="Test server",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                port=25565,
                max_memory=1024,
                max_players=20
            )
            assert request.name == valid_name.strip()

    def test_minecraft_version_invalid_format(self):
        """Test invalid Minecraft version format (line 59)"""
        invalid_versions = [
            "1",           # Too short
            "1.20.1.1",    # Too long
            "v1.20.1",     # Has prefix
            "1.20.1-pre",  # Has suffix
            "abc.def.ghi", # Non-numeric
        ]
        
        for invalid_version in invalid_versions:
            with pytest.raises(ValidationError) as exc_info:
                ServerCreateRequest(
                    name="test-server",
                    description="Test server",
                    minecraft_version=invalid_version,
                    server_type=ServerType.vanilla,
                    port=25565,
                    max_memory=1024,
                    max_players=20
                )
            
            assert "Invalid Minecraft version format" in str(exc_info.value)

    def test_minecraft_version_below_minimum(self):
        """Test Minecraft version below minimum (line 66)"""
        below_minimum_versions = [
            "1.7",
            "1.7.10",
            "1.6.4",
            "1.5.2",
        ]
        
        for version in below_minimum_versions:
            with pytest.raises(ValidationError) as exc_info:
                ServerCreateRequest(
                    name="test-server",
                    description="Test server",
                    minecraft_version=version,
                    server_type=ServerType.vanilla,
                    port=25565,
                    max_memory=1024,
                    max_players=20
                )
            
            assert "Minimum supported Minecraft version is 1.8" in str(exc_info.value)

    def test_minecraft_version_parsing_exception(self):
        """Test Minecraft version parsing exception (line 68)"""
        # This is a bit tricky to test since packaging.version is quite robust
        # But we can try with some edge cases
        with pytest.raises(ValidationError) as exc_info:
            ServerCreateRequest(
                name="test-server",
                description="Test server",
                minecraft_version="1.8.invalid",  # Invalid patch version
                server_type=ServerType.vanilla,
                port=25565,
                max_memory=1024,
                max_players=20
            )
        
        # Either format validation or parsing should catch this
        error_msg = str(exc_info.value)
        assert ("Invalid Minecraft version format" in error_msg or 
                "Invalid version format" in error_msg)

    def test_valid_minecraft_versions(self):
        """Test valid Minecraft versions"""
        valid_versions = [
            "1.8",
            "1.8.9",
            "1.12.2",
            "1.16.5",
            "1.18.2",
            "1.19.4",
            "1.20.1",
            "1.21",
        ]
        
        for version in valid_versions:
            request = ServerCreateRequest(
                name="test-server",
                description="Test server",
                minecraft_version=version,
                server_type=ServerType.vanilla,
                port=25565,
                max_memory=1024,
                max_players=20
            )
            assert request.minecraft_version == version


class TestServerUpdateRequest:
    """Test cases for ServerUpdateRequest validation"""

    def test_valid_server_update_request(self):
        """Test valid server update request"""
        request = ServerUpdateRequest(
            name="updated-server",
            description="Updated description"
        )
        
        assert request.name == "updated-server"
        assert request.description == "Updated description"

    def test_server_update_name_validation(self):
        """Test server update name validation"""
        # Test empty name (lines 168-170)
        with pytest.raises(ValidationError) as exc_info:
            ServerUpdateRequest(name="   ")
        assert "Server name cannot be empty" in str(exc_info.value)
        
        # Test None name should be allowed for updates
        request = ServerUpdateRequest(name=None)
        assert request.name is None

    def test_server_update_partial_fields(self):
        """Test server update with partial fields"""
        # Only name
        request1 = ServerUpdateRequest(name="new-name")
        assert request1.name == "new-name"
        assert request1.description is None
        
        # Only description
        request2 = ServerUpdateRequest(description="new description")
        assert request2.name is None
        assert request2.description == "new description"


class TestServerImportRequest:
    """Test cases for ServerImportRequest validation"""

    def test_valid_server_import_request(self):
        """Test valid server import request"""
        request = ServerImportRequest(
            name="imported-server",
            description="Imported from backup"
        )
        
        assert request.name == "imported-server"
        assert request.description == "Imported from backup"

    def test_server_import_name_validation(self):
        """Test server import name validation"""
        # Test empty name
        with pytest.raises(ValidationError):
            ServerImportRequest(name="")
        
        # Test invalid characters
        with pytest.raises(ValidationError):
            ServerImportRequest(name="server$name")


class TestServerResponse:
    """Test cases for ServerResponse schema"""

    def test_server_response_creation(self):
        """Test server response creation"""
        from datetime import datetime
        
        response = ServerResponse(
            id=1,
            name="test-server",
            description="Test description",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            status=ServerStatus.stopped,
            port=25565,
            max_memory=1024,
            max_players=20,
            owner_id=1,
            template_id=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            directory_path="/servers/test-server"
        )
        
        assert response.id == 1
        assert response.name == "test-server"
        assert response.server_type == ServerType.vanilla
        assert response.status == ServerStatus.stopped


class TestMinecraftVersionInfo:
    """Test cases for MinecraftVersionInfo schema"""

    def test_minecraft_version_info_creation(self):
        """Test MinecraftVersionInfo creation"""
        version_info = MinecraftVersionInfo(
            version="1.20.1",
            server_type=ServerType.vanilla,
            download_url="https://example.com/server.jar",
            is_supported=True,
            release_date="2023-06-07",
            is_stable=True,
            build_number=None
        )
        
        assert version_info.version == "1.20.1"
        assert version_info.server_type == ServerType.vanilla
        assert version_info.is_supported is True
        assert version_info.is_stable is True
        assert version_info.build_number is None

    def test_minecraft_version_info_with_build_number(self):
        """Test MinecraftVersionInfo with build number"""
        version_info = MinecraftVersionInfo(
            version="1.20.1",
            server_type=ServerType.paper,
            download_url="https://example.com/paper.jar",
            is_supported=True,
            release_date="2023-06-07",
            is_stable=False,
            build_number=123
        )
        
        assert version_info.build_number == 123
        assert version_info.server_type == ServerType.paper
        assert version_info.is_stable is False


class TestSupportedVersionsResponse:
    """Test cases for SupportedVersionsResponse schema"""

    def test_supported_versions_response_creation(self):
        """Test SupportedVersionsResponse creation"""
        version_info = MinecraftVersionInfo(
            version="1.20.1",
            server_type=ServerType.vanilla,
            download_url="https://example.com/server.jar",
            is_supported=True,
            release_date="2023-06-07",
            is_stable=True,
            build_number=None
        )
        
        response = SupportedVersionsResponse(versions=[version_info])
        
        assert len(response.versions) == 1
        assert response.versions[0].version == "1.20.1"

    def test_supported_versions_response_empty(self):
        """Test SupportedVersionsResponse with empty versions"""
        response = SupportedVersionsResponse(versions=[])
        
        assert len(response.versions) == 0


class TestSchemaEdgeCases:
    """Test edge cases for schema validation"""

    def test_name_with_leading_trailing_spaces(self):
        """Test name trimming functionality"""
        request = ServerCreateRequest(
            name="  test-server  ",  # Spaces around name
            description="Test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20
        )
        
        assert request.name == "test-server"  # Should be trimmed

    def test_valid_port_ranges(self):
        """Test valid port range validation"""
        # Test minimum valid port
        request1 = ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=1024,  # Minimum non-privileged port
            max_memory=1024,
            max_players=20
        )
        assert request1.port == 1024
        
        # Test maximum valid port
        request2 = ServerCreateRequest(
            name="test-server",
            description="Test server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=65535,  # Maximum port
            max_memory=1024,
            max_players=20
        )
        assert request2.port == 65535