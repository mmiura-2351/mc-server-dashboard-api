import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from app.services.java_compatibility import (
    JavaCompatibilityService,
    JavaVersionInfo,
    java_compatibility_service,
)


class TestJavaVersionInfo:
    """Test JavaVersionInfo dataclass"""
    
    def test_version_string_property(self):
        """Test version_string property"""
        java_info = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        assert java_info.version_string == "17.0.1"
    
    def test_java_8_compatibility(self):
        """Test Java 8 compatibility checks"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        
        assert java8.is_compatible_with_java_8 is True
        assert java17.is_compatible_with_java_8 is False
    
    def test_java_16_compatibility(self):
        """Test Java 16+ compatibility checks"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java16 = JavaVersionInfo(major_version=16, minor_version=0, patch_version=1)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        
        assert java8.is_compatible_with_java_16 is False
        assert java16.is_compatible_with_java_16 is True
        assert java17.is_compatible_with_java_16 is True
    
    def test_java_17_compatibility(self):
        """Test Java 17+ compatibility checks"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java16 = JavaVersionInfo(major_version=16, minor_version=0, patch_version=1)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        
        assert java8.is_compatible_with_java_17 is False
        assert java16.is_compatible_with_java_17 is False
        assert java17.is_compatible_with_java_17 is True
    
    def test_java_21_compatibility(self):
        """Test Java 21+ compatibility checks"""
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        java21 = JavaVersionInfo(major_version=21, minor_version=0, patch_version=1)
        
        assert java17.is_compatible_with_java_21 is False
        assert java21.is_compatible_with_java_21 is True


class TestJavaCompatibilityService:
    """Test JavaCompatibilityService"""
    
    @pytest.fixture
    def service(self):
        """Create a test service instance"""
        return JavaCompatibilityService(java_check_timeout=5)
    
    def test_get_required_java_version(self, service):
        """Test getting required Java version for Minecraft versions"""
        # Test Java 8 requirements (Minecraft 1.8 - 1.16.5)
        assert service.get_required_java_version("1.8.0") == 8
        assert service.get_required_java_version("1.12.2") == 8
        assert service.get_required_java_version("1.16.5") == 8
        
        # Test Java 16 requirements (Minecraft 1.17 - 1.17.1)
        assert service.get_required_java_version("1.17.0") == 16
        assert service.get_required_java_version("1.17.1") == 16
        
        # Test Java 17 requirements (Minecraft 1.18 - 1.20)
        assert service.get_required_java_version("1.18.0") == 17
        assert service.get_required_java_version("1.19.4") == 17
        assert service.get_required_java_version("1.20.0") == 17
        
        # Test Java 21 requirements (Minecraft 1.21+)
        assert service.get_required_java_version("1.21.0") == 21
        assert service.get_required_java_version("1.22.0") == 21
    
    def test_get_required_java_version_invalid(self, service):
        """Test getting required Java version for invalid Minecraft versions"""
        # Should default to Java 21 for unknown versions
        assert service.get_required_java_version("invalid") == 21
        assert service.get_required_java_version("2.0.0") == 21
    
    def test_validate_java_compatibility_java_8(self, service):
        """Test Java compatibility validation for Java 8 scenarios"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        
        # Java 8 should be compatible with Minecraft 1.8-1.16.5
        compatible, message = service.validate_java_compatibility("1.8.0", java8)
        assert compatible is True
        assert "compatible" in message.lower()
        
        compatible, message = service.validate_java_compatibility("1.16.5", java8)
        assert compatible is True
        
        # Java 8 should NOT be compatible with Minecraft 1.17+
        compatible, message = service.validate_java_compatibility("1.17.0", java8)
        assert compatible is False
        assert "incompatibility" in message.lower()
        assert "Java 16 or higher" in message
    
    def test_validate_java_compatibility_java_17(self, service):
        """Test Java compatibility validation for Java 17 scenarios"""
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1, vendor="OpenJDK")
        
        # Java 17 should be compatible with Minecraft 1.17+ (not 1.8-1.16.5 due to newer version)
        compatible, message = service.validate_java_compatibility("1.8.0", java17)
        assert compatible is False  # Java 17 is too new for Minecraft 1.8
        
        compatible, message = service.validate_java_compatibility("1.17.0", java17)
        assert compatible is True
        
        compatible, message = service.validate_java_compatibility("1.18.0", java17)
        assert compatible is True
        
        compatible, message = service.validate_java_compatibility("1.20.0", java17)
        assert compatible is True
        
        # Java 17 should NOT be compatible with Minecraft 1.21+ (requires Java 21)
        compatible, message = service.validate_java_compatibility("1.21.0", java17)
        assert compatible is False
        assert "Java 21 or higher" in message
    
    def test_validate_java_compatibility_java_21(self, service):
        """Test Java compatibility validation for Java 21 scenarios"""
        java21 = JavaVersionInfo(major_version=21, minor_version=0, patch_version=1)
        
        # Java 21 should be compatible with Minecraft 1.21+
        compatible, message = service.validate_java_compatibility("1.21.0", java21)
        assert compatible is True
        
        compatible, message = service.validate_java_compatibility("1.22.0", java21)
        assert compatible is True
    
    def test_parse_java_version_modern_format(self, service):
        """Test parsing modern Java version format (Java 9+)"""
        # Test Java 17 format
        version_output = "java 17.0.1 2021-10-19 LTS"
        result = service._parse_java_version(version_output)
        
        assert result is not None
        assert result.major_version == 17
        assert result.minor_version == 0
        assert result.patch_version == 1
    
    def test_parse_java_version_legacy_format(self, service):
        """Test parsing legacy Java version format (Java 8)"""
        # Test Java 8 format
        version_output = 'java version "1.8.0_292"\nJava(TM) SE Runtime Environment'
        result = service._parse_java_version(version_output)
        
        assert result is not None
        assert result.major_version == 8
        assert result.minor_version == 0
        assert result.patch_version == 292
    
    def test_parse_java_version_openjdk_format(self, service):
        """Test parsing OpenJDK version format"""
        version_output = 'openjdk version "17.0.1" 2021-10-19\nOpenJDK Runtime Environment'
        result = service._parse_java_version(version_output)
        
        assert result is not None
        assert result.major_version == 17
        assert result.minor_version == 0
        assert result.patch_version == 1
        assert result.vendor == "OpenJDK"
    
    def test_parse_java_version_invalid(self, service):
        """Test parsing invalid Java version output"""
        result = service._parse_java_version("invalid output")
        assert result is None
        
        result = service._parse_java_version("")
        assert result is None
    
    def test_get_compatibility_matrix(self, service):
        """Test getting compatibility matrix"""
        matrix = service.get_compatibility_matrix()
        
        assert isinstance(matrix, dict)
        assert len(matrix) > 0
        
        # Check for expected Java versions
        java_versions = list(matrix.values())
        assert 8 in java_versions
        assert 16 in java_versions
        assert 17 in java_versions
        assert 21 in java_versions
    
    def test_get_supported_minecraft_versions(self, service):
        """Test getting supported Minecraft versions for Java version"""
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292)
        java17 = JavaVersionInfo(major_version=17, minor_version=0, patch_version=1)
        java21 = JavaVersionInfo(major_version=21, minor_version=0, patch_version=1)
        
        # Java 8 should only support older Minecraft versions
        supported_8 = service.get_supported_minecraft_versions(java8)
        assert len(supported_8) == 1  # Only the 1.8-1.16.5 range
        
        # Java 17 should support more ranges
        supported_17 = service.get_supported_minecraft_versions(java17)
        assert len(supported_17) >= 2  # At least 1.17-1.17.1 and 1.18-1.20 ranges
        
        # Java 21 should support all ranges
        supported_21 = service.get_supported_minecraft_versions(java21)
        assert len(supported_21) >= 4  # All version ranges
    
    @pytest.mark.asyncio
    async def test_detect_java_version_success(self, service):
        """Test successful Java version detection"""
        mock_version_output = b"java 17.0.1 2021-10-19 LTS\n"
        
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            # Mock successful subprocess
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", mock_version_output)
            mock_subprocess.return_value = mock_process
            
            result = await service.detect_java_version()
            
            assert result is not None
            assert result.major_version == 17
            assert result.minor_version == 0
            assert result.patch_version == 1
    
    @pytest.mark.asyncio
    async def test_detect_java_version_not_found(self, service):
        """Test Java version detection when Java is not installed"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            # Mock FileNotFoundError (Java not found)
            mock_subprocess.side_effect = FileNotFoundError("java not found")
            
            result = await service.detect_java_version()
            assert result is None
    
    @pytest.mark.asyncio
    async def test_detect_java_version_timeout(self, service):
        """Test Java version detection timeout"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            # Mock timeout
            mock_process = AsyncMock()
            mock_process.communicate.side_effect = asyncio.TimeoutError()
            mock_subprocess.return_value = mock_process
            
            result = await service.detect_java_version()
            assert result is None
    
    @pytest.mark.asyncio
    async def test_detect_java_version_error_return_code(self, service):
        """Test Java version detection with error return code"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            # Mock subprocess with error return code
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"error output")
            mock_subprocess.return_value = mock_process
            
            result = await service.detect_java_version()
            assert result is None


class TestJavaCompatibilityServiceIntegration:
    """Integration tests for Java compatibility service"""
    
    def test_global_service_instance(self):
        """Test that global service instance is properly initialized"""
        assert java_compatibility_service is not None
        assert isinstance(java_compatibility_service, JavaCompatibilityService)
        assert java_compatibility_service.java_check_timeout > 0
    
    def test_compatibility_matrix_completeness(self):
        """Test that compatibility matrix covers expected version ranges"""
        matrix = java_compatibility_service.get_compatibility_matrix()
        
        # Should have entries for all major Java version requirements
        java_versions = set(matrix.values())
        expected_versions = {8, 16, 17, 21}
        
        assert expected_versions.issubset(java_versions), f"Missing Java versions: {expected_versions - java_versions}"
    
    def test_error_message_generation(self):
        """Test that error messages are user-friendly and informative"""
        service = java_compatibility_service
        java8 = JavaVersionInfo(major_version=8, minor_version=0, patch_version=292, vendor="Oracle")
        
        # Test incompatible scenario
        compatible, message = service.validate_java_compatibility("1.21.0", java8)
        
        assert compatible is False
        assert "Java version incompatibility detected" in message
        assert "Minecraft 1.21.0 requires Java 21" in message
        assert "Currently installed: Java 8" in message
        assert "Oracle" in message  # Vendor should be included
        assert "https://adoptium.net" in message  # Installation link should be included
