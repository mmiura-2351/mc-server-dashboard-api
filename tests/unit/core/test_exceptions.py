"""
Test coverage for app/core/exceptions.py
Tests focus on exception classes, utility functions, and edge cases
"""

import pytest
import logging
from unittest.mock import Mock, patch
from fastapi import status

from app.core.exceptions import (
    APIException,
    ResourceNotFoundException,
    ServerNotFoundException,
    UserNotFoundException,
    GroupNotFoundException,
    BackupNotFoundException,
    TemplateNotFoundException,
    AccessDeniedException,
    ServerAccessDeniedException,
    InvalidRequestException,
    ConflictException,
    ServerStateException,
    FileOperationException,
    DatabaseOperationException,
    AuthenticationException,
    UserNotApprovedException,
    MinecraftServerException,
    handle_database_error,
    handle_file_error,
    validate_server_access,
    validate_user_approved
)


class TestAPIException:
    """Test cases for base APIException class"""

    @patch('app.core.exceptions.logger')
    def test_api_exception_default_log_level(self, mock_logger):
        """Test APIException with default warning log level"""
        mock_logger.warning = Mock()
        
        exception = APIException(
            status_code=400,
            detail="Test error message"
        )
        
        assert exception.status_code == 400
        assert exception.detail == "Test error message"
        mock_logger.warning.assert_called_once_with("APIException: Test error message")

    @patch('app.core.exceptions.logger')
    def test_api_exception_custom_log_level(self, mock_logger):
        """Test APIException with custom log level"""
        mock_logger.error = Mock()
        
        exception = APIException(
            status_code=500,
            detail="Critical error",
            log_level="error"
        )
        
        assert exception.status_code == 500
        mock_logger.error.assert_called_once_with("APIException: Critical error")

    def test_api_exception_valid_log_levels(self):
        """Test APIException with various valid log levels"""
        valid_levels = ["debug", "info", "warning", "error", "critical"]
        
        for level in valid_levels:
            with patch('app.core.exceptions.logger') as mock_logger:
                exception = APIException(
                    status_code=400,
                    detail="Test message",
                    log_level=level
                )
                
                # Should call the appropriate log method
                log_method = getattr(mock_logger, level)
                log_method.assert_called_once_with("APIException: Test message")

    def test_api_exception_with_headers(self):
        """Test APIException with custom headers"""
        headers = {"X-Custom-Header": "test-value"}
        
        exception = APIException(
            status_code=400,
            detail="Test with headers",
            headers=headers
        )
        
        assert exception.headers == headers


class TestResourceNotFoundExceptions:
    """Test cases for resource not found exception classes"""

    def test_server_not_found_exception(self):
        """Test ServerNotFoundException (line 47)"""
        exception = ServerNotFoundException("123")
        
        assert exception.status_code == status.HTTP_404_NOT_FOUND
        assert "Server with ID 123 not found" in exception.detail

    def test_user_not_found_exception(self):
        """Test UserNotFoundException (line 54)"""
        exception = UserNotFoundException("456")
        
        assert exception.status_code == status.HTTP_404_NOT_FOUND
        assert "User with ID 456 not found" in exception.detail

    def test_group_not_found_exception(self):
        """Test GroupNotFoundException (line 68)"""
        exception = GroupNotFoundException("789")
        
        assert exception.status_code == status.HTTP_404_NOT_FOUND
        assert "Group with ID 789 not found" in exception.detail

    def test_backup_not_found_exception(self):
        """Test BackupNotFoundException"""
        exception = BackupNotFoundException("backup-123")
        
        assert exception.status_code == status.HTTP_404_NOT_FOUND
        assert "Backup with ID backup-123 not found" in exception.detail

    def test_template_not_found_exception(self):
        """Test TemplateNotFoundException"""
        exception = TemplateNotFoundException("template-456")
        
        assert exception.status_code == status.HTTP_404_NOT_FOUND
        assert "Template with ID template-456 not found" in exception.detail


class TestAccessDeniedExceptions:
    """Test cases for access denied exception classes"""

    def test_access_denied_exception_default(self):
        """Test AccessDeniedException with default parameters"""
        exception = AccessDeniedException()
        
        assert exception.status_code == status.HTTP_403_FORBIDDEN
        assert "Access denied: insufficient permissions to access resource" in exception.detail

    def test_access_denied_exception_custom(self):
        """Test AccessDeniedException with custom parameters"""
        exception = AccessDeniedException(resource_type="server", action="modify")
        
        assert exception.status_code == status.HTTP_403_FORBIDDEN
        assert "Access denied: insufficient permissions to modify server" in exception.detail

    def test_server_access_denied_exception(self):
        """Test ServerAccessDeniedException (lines 83-84)"""
        exception = ServerAccessDeniedException("server-123")
        
        assert exception.status_code == status.HTTP_403_FORBIDDEN
        assert "Access denied: insufficient permissions to access server server-123" in exception.detail


class TestValidationExceptions:
    """Test cases for validation and conflict exception classes"""

    def test_invalid_request_exception(self):
        """Test InvalidRequestException"""
        exception = InvalidRequestException("Invalid input data")
        
        assert exception.status_code == status.HTTP_400_BAD_REQUEST
        assert exception.detail == "Invalid input data"

    def test_conflict_exception(self):
        """Test ConflictException"""
        exception = ConflictException("Resource already exists")
        
        assert exception.status_code == status.HTTP_409_CONFLICT
        assert exception.detail == "Resource already exists"

    def test_server_state_exception(self):
        """Test ServerStateException"""
        exception = ServerStateException("server-123", "running", "stopped")
        
        assert exception.status_code == status.HTTP_400_BAD_REQUEST
        assert "Server server-123 is running, but stopped is required" in exception.detail


class TestOperationExceptions:
    """Test cases for operation exception classes"""

    @patch('app.core.exceptions.logger')
    def test_file_operation_exception_with_reason(self, mock_logger):
        """Test FileOperationException with reason (lines 114-116)"""
        mock_logger.error = Mock()
        
        exception = FileOperationException("delete", "/path/to/file", "Permission denied")
        
        assert exception.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to delete file /path/to/file: Permission denied" in exception.detail
        mock_logger.error.assert_called_once()

    @patch('app.core.exceptions.logger')
    def test_file_operation_exception_without_reason(self, mock_logger):
        """Test FileOperationException without reason"""
        mock_logger.error = Mock()
        
        exception = FileOperationException("read", "/path/to/file")
        
        assert exception.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exception.detail == "Failed to read file /path/to/file"

    @patch('app.core.exceptions.logger')
    def test_database_operation_exception_with_reason(self, mock_logger):
        """Test DatabaseOperationException with reason (lines 124-126)"""
        mock_logger.error = Mock()
        
        exception = DatabaseOperationException("insert", "users", "Constraint violation")
        
        assert exception.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Database insert failed for users: Constraint violation" in exception.detail
        mock_logger.error.assert_called_once()

    @patch('app.core.exceptions.logger')
    def test_database_operation_exception_without_reason(self, mock_logger):
        """Test DatabaseOperationException without reason"""
        mock_logger.error = Mock()
        
        exception = DatabaseOperationException("update", "servers")
        
        assert exception.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exception.detail == "Database update failed for servers"


class TestAuthenticationExceptions:
    """Test cases for authentication exception classes"""

    def test_authentication_exception_default(self):
        """Test AuthenticationException with default message (line 133)"""
        exception = AuthenticationException()
        
        assert exception.status_code == status.HTTP_401_UNAUTHORIZED
        assert exception.detail == "Invalid authentication credentials"

    def test_authentication_exception_custom(self):
        """Test AuthenticationException with custom message"""
        exception = AuthenticationException("Token expired")
        
        assert exception.status_code == status.HTTP_401_UNAUTHORIZED
        assert exception.detail == "Token expired"

    def test_user_not_approved_exception(self):
        """Test UserNotApprovedException (lines 140-141)"""
        exception = UserNotApprovedException()
        
        assert exception.status_code == status.HTTP_403_FORBIDDEN
        assert exception.detail == "User account is not approved yet"


class TestMinecraftServerException:
    """Test cases for MinecraftServerException"""

    @patch('app.core.exceptions.logger')
    def test_minecraft_server_exception_with_reason(self, mock_logger):
        """Test MinecraftServerException with reason (lines 148-151)"""
        mock_logger.error = Mock()
        
        exception = MinecraftServerException("server-123", "start", "Java not found")
        
        assert exception.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to start Minecraft server server-123: Java not found" in exception.detail
        mock_logger.error.assert_called_once()

    @patch('app.core.exceptions.logger')
    def test_minecraft_server_exception_without_reason(self, mock_logger):
        """Test MinecraftServerException without reason"""
        mock_logger.error = Mock()
        
        exception = MinecraftServerException("server-456", "stop")
        
        assert exception.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exception.detail == "Failed to stop Minecraft server server-456"


class TestUtilityFunctions:
    """Test cases for utility functions"""

    @patch('app.core.exceptions.logger')
    def test_handle_database_error(self, mock_logger):
        """Test handle_database_error utility function"""
        test_error = Exception("Connection failed")
        
        with pytest.raises(DatabaseOperationException) as exc_info:
            handle_database_error("insert", "users", test_error)
        
        # Should be called twice - once by utility function, once by exception constructor
        assert mock_logger.error.call_count == 2
        assert "Database insert failed for users: Connection failed" in str(exc_info.value)

    @patch('app.core.exceptions.logger')
    def test_handle_file_error(self, mock_logger):
        """Test handle_file_error utility function"""
        test_error = Exception("File not found")
        
        with pytest.raises(FileOperationException) as exc_info:
            handle_file_error("read", "/path/to/file", test_error)
        
        # Should be called twice - once by utility function, once by exception constructor
        assert mock_logger.error.call_count == 2
        assert "Failed to read file /path/to/file: File not found" in str(exc_info.value)

    def test_validate_server_access_success(self):
        """Test validate_server_access with matching owner"""
        server = Mock()
        server.owner_id = "user-123"
        server.id = "server-456"
        
        # Should not raise exception
        validate_server_access(server, "user-123")

    def test_validate_server_access_denied(self):
        """Test validate_server_access with non-matching owner (lines 168-169)"""
        server = Mock()
        server.owner_id = "user-123"
        server.id = "server-456"
        
        with pytest.raises(ServerAccessDeniedException) as exc_info:
            validate_server_access(server, "user-789")
        
        assert "Access denied: insufficient permissions to access server server-456" in str(exc_info.value)

    def test_validate_user_approved_success(self):
        """Test validate_user_approved with approved user"""
        user = Mock()
        user.is_approved = True
        
        # Should not raise exception
        validate_user_approved(user)

    def test_validate_user_approved_denied(self):
        """Test validate_user_approved with unapproved user (lines 174-175)"""
        user = Mock()
        user.is_approved = False
        
        with pytest.raises(UserNotApprovedException) as exc_info:
            validate_user_approved(user)
        
        assert "User account is not approved yet" in str(exc_info.value)


class TestExceptionInheritance:
    """Test cases for exception inheritance and behavior"""

    def test_all_exceptions_inherit_from_api_exception(self):
        """Test that all custom exceptions inherit from APIException"""
        exception_classes = [
            ServerNotFoundException,
            UserNotFoundException,
            GroupNotFoundException,
            BackupNotFoundException,
            TemplateNotFoundException,
            AccessDeniedException,
            ServerAccessDeniedException,
            InvalidRequestException,
            ConflictException,
            ServerStateException,
            FileOperationException,
            DatabaseOperationException,
            AuthenticationException,
            UserNotApprovedException,
            MinecraftServerException
        ]
        
        for exception_class in exception_classes:
            assert issubclass(exception_class, APIException)

    def test_resource_not_found_exceptions_inherit_correctly(self):
        """Test that resource not found exceptions inherit from ResourceNotFoundException"""
        resource_exception_classes = [
            ServerNotFoundException,
            UserNotFoundException,
            GroupNotFoundException,
            BackupNotFoundException,
            TemplateNotFoundException
        ]
        
        for exception_class in resource_exception_classes:
            assert issubclass(exception_class, ResourceNotFoundException)

    def test_access_denied_exceptions_inherit_correctly(self):
        """Test that access denied exceptions inherit correctly"""
        # ServerAccessDeniedException should inherit from HTTPException due to line 84 override
        exception = ServerAccessDeniedException("server-123")
        assert exception.status_code == status.HTTP_403_FORBIDDEN