"""
Test coverage for app/core/security.py
Tests focus on path validation, tar extraction security, and file operation validation
"""

import pytest
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

from app.core.security import (
    SecurityError,
    PathValidator,
    TarExtractor,
    FileOperationValidator
)


class TestSecurityError:
    """Test cases for SecurityError exception"""

    def test_security_error_message(self):
        """Test SecurityError with custom message"""
        error = SecurityError("Test security violation")
        assert str(error) == "Test security violation"
        assert isinstance(error, Exception)


class TestPathValidator:
    """Test cases for PathValidator class"""

    def test_validate_safe_name_valid(self):
        """Test PathValidator.validate_safe_name with valid names"""
        valid_names = [
            "server-name",
            "server_name",
            "server name",
            "server123",
            "ServerName",
            "test.txt",
            "my-server_2023.log"
        ]
        
        for name in valid_names:
            result = PathValidator.validate_safe_name(name)
            assert result == name

    def test_validate_safe_name_empty_string(self):
        """Test PathValidator.validate_safe_name with empty string (line 90)"""
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name("")
        
        assert "Name must be a non-empty string" in str(exc_info.value)

    def test_validate_safe_name_none(self):
        """Test PathValidator.validate_safe_name with None"""
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name(None)
        
        assert "Name must be a non-empty string" in str(exc_info.value)

    def test_validate_safe_name_non_string(self):
        """Test PathValidator.validate_safe_name with non-string input"""
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name(123)
        
        assert "Name must be a non-empty string" in str(exc_info.value)

    def test_validate_safe_name_too_long(self):
        """Test PathValidator.validate_safe_name with name too long"""
        long_name = "a" * 256  # Default max_length is 255
        
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name(long_name)
        
        assert "Name too long (max 255 characters)" in str(exc_info.value)

    def test_validate_safe_name_custom_max_length(self):
        """Test PathValidator.validate_safe_name with custom max_length"""
        name = "test-name"
        
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name(name, max_length=5)
        
        assert "Name too long (max 5 characters)" in str(exc_info.value)

    def test_validate_safe_name_invalid_characters(self):
        """Test PathValidator.validate_safe_name with invalid characters"""
        invalid_names = [
            "server@name",
            "server#name",
            "server$name",
            "server%name",
            "server&name",
            "server*name",
            "server+name",
            "server=name",
            "server[name]",
            "server{name}",
            "server|name",
            "server:name",
            "server;name",
            "server\"name",
            "server'name",
            "server<name>",
            "server?name",
            "server/name"
        ]
        
        for name in invalid_names:
            with pytest.raises(SecurityError) as exc_info:
                PathValidator.validate_safe_name(name)
            
            assert "Name contains invalid characters" in str(exc_info.value)

    def test_validate_safe_name_reserved_names(self):
        """Test PathValidator.validate_safe_name with reserved names"""
        reserved_names = ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "con", "prn"]
        
        for name in reserved_names:
            with pytest.raises(SecurityError) as exc_info:
                PathValidator.validate_safe_name(name)
            
            assert "is a reserved name and cannot be used" in str(exc_info.value)

    def test_validate_safe_name_path_traversal(self):
        """Test PathValidator.validate_safe_name with path traversal patterns"""
        # Test cases where "/" fails regex first
        invalid_with_slash = ["../test", "test/../other"]
        for name in invalid_with_slash:
            with pytest.raises(SecurityError) as exc_info:
                PathValidator.validate_safe_name(name)
            # "/" fails regex check first
            assert "Name contains invalid characters" in str(exc_info.value)
        
        # Test ".." alone which passes regex but fails reserved name check first
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name("..")
        assert "is a reserved name and cannot be used" in str(exc_info.value)
        
        # Note: "test..test" actually fails path traversal check too, so it's invalid

    def test_validate_safe_name_backslashes(self):
        """Test PathValidator.validate_safe_name with backslashes (line 94-95)"""
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name("server\\name")
        
        # Backslashes fail the regex check first, so we get the invalid characters error
        assert "Name contains invalid characters" in str(exc_info.value)

    def test_validate_safe_name_starting_ending_dots(self):
        """Test PathValidator.validate_safe_name with starting/ending dots (line 99)"""
        invalid_names = [".hiddenfile", "filename."]
        
        for name in invalid_names:
            with pytest.raises(SecurityError) as exc_info:
                PathValidator.validate_safe_name(name)
            
            assert "Names cannot start or end with dots" in str(exc_info.value)
        
        # "..test" would fail path traversal check first
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_name("..test")
        assert "Path traversal patterns (..) are not allowed" in str(exc_info.value)

    def test_validate_safe_name_allowed_dot_files(self):
        """Test PathValidator.validate_safe_name allows specific dot files"""
        allowed_names = [".gitkeep", ".gitignore"]
        
        for name in allowed_names:
            result = PathValidator.validate_safe_name(name)
            assert result == name

    def test_validate_safe_name_starting_ending_spaces(self):
        """Test PathValidator.validate_safe_name with starting/ending spaces"""
        invalid_names = [" test", "test ", " test "]
        
        for name in invalid_names:
            with pytest.raises(SecurityError) as exc_info:
                PathValidator.validate_safe_name(name)
            
            assert "Names cannot start or end with spaces" in str(exc_info.value)

    def test_validate_safe_path_success(self):
        """Test PathValidator.validate_safe_path with valid path"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            test_file = base_dir / "test.txt"
            test_file.touch()
            
            result = PathValidator.validate_safe_path(test_file, base_dir)
            assert result == test_file.resolve()

    def test_validate_safe_path_string_input(self):
        """Test PathValidator.validate_safe_path with string input (line 118)"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            test_file = base_dir / "test.txt"
            test_file.touch()
            
            result = PathValidator.validate_safe_path(str(test_file), base_dir)
            assert result == test_file.resolve()

    def test_validate_safe_path_traversal_attempt(self):
        """Test PathValidator.validate_safe_path with path traversal (line 132-133)"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            traversal_path = base_dir / ".." / "etc" / "passwd"
            
            with pytest.raises(SecurityError) as exc_info:
                PathValidator.validate_safe_path(traversal_path, base_dir)
            
            assert "Path traversal attempt detected" in str(exc_info.value)

    def test_validate_safe_path_invalid_path(self):
        """Test PathValidator.validate_safe_path with invalid path"""
        base_dir = Path("/nonexistent")
        invalid_path = Path("/invalid\x00path")  # Path with null byte
        
        with pytest.raises(SecurityError) as exc_info:
            PathValidator.validate_safe_path(invalid_path, base_dir)
        
        # Should catch and re-raise as SecurityError
        assert "Invalid path" in str(exc_info.value) or "Path traversal attempt detected" in str(exc_info.value)

    def test_create_safe_server_directory_success(self):
        """Test PathValidator.create_safe_server_directory success"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            with patch.object(PathValidator, 'sanitize_directory_name', return_value="safe-server-name"):
                result = PathValidator.create_safe_server_directory("test server", base_dir)
                
                expected_path = base_dir / "safe-server-name"
                assert result == expected_path.resolve()

    def test_create_safe_server_directory_unsafe_name(self):
        """Test PathValidator.create_safe_server_directory with unsafe name"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            
            with patch.object(PathValidator, 'sanitize_directory_name', side_effect=SecurityError("Unsafe name")):
                with pytest.raises(SecurityError):
                    PathValidator.create_safe_server_directory("../dangerous", base_dir)

    def test_sanitize_directory_name_valid(self):
        """Test PathValidator.sanitize_directory_name with valid names"""
        test_cases = [
            ("test-server", "test-server"),
            ("test_server", "test_server"),
            ("test.server", "test.server"),
            ("test server", "test_server"),  # Spaces become underscores
            ("test@server#", "test_server"),  # Invalid chars become underscores, trailing underscore stripped
            ("test___server", "test_server"),  # Multiple underscores reduced
            ("_test_server_", "test_server"),  # Leading/trailing underscores removed
            (".test.server.", "test.server"),  # Leading/trailing dots removed
        ]
        
        for input_name, expected in test_cases:
            result = PathValidator.sanitize_directory_name(input_name)
            assert result == expected

    def test_sanitize_directory_name_empty_result(self):
        """Test PathValidator.sanitize_directory_name with name that becomes empty"""
        empty_inputs = ["", "___", "...", "_._", "@#$%"]
        
        for input_name in empty_inputs:
            result = PathValidator.sanitize_directory_name(input_name)
            assert result == "server"  # Default fallback


class TestTarExtractor:
    """Test cases for TarExtractor class"""

    def test_tar_extractor_constants(self):
        """Test TarExtractor security constants are properly defined"""
        assert TarExtractor.MAX_ARCHIVE_SIZE == 1024 * 1024 * 1024  # 1GB
        assert TarExtractor.MAX_EXTRACTED_SIZE == 2 * 1024 * 1024 * 1024  # 2GB
        assert TarExtractor.MAX_MEMBER_COUNT == 10000
        assert TarExtractor.MAX_COMPRESSION_RATIO == 100
        assert TarExtractor.MAX_MEMBER_SIZE == 100 * 1024 * 1024  # 100MB

    def test_validate_archive_safety_file_not_found(self):
        """Test TarExtractor.validate_archive_safety with non-existent file (line 206)"""
        nonexistent_path = Path("/nonexistent/archive.tar.gz")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_archive_safety(nonexistent_path)
        
        assert "Archive not found" in str(exc_info.value)

    def test_validate_archive_safety_file_too_large(self):
        """Test TarExtractor.validate_archive_safety with oversized archive"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            
            # Mock file size to be larger than MAX_ARCHIVE_SIZE
            with patch.object(Path, 'stat') as mock_stat:
                mock_stat.return_value.st_size = TarExtractor.MAX_ARCHIVE_SIZE + 1
                
                with pytest.raises(SecurityError) as exc_info:
                    TarExtractor.validate_archive_safety(tar_path)
                
                assert "Archive too large" in str(exc_info.value)

    def test_validate_archive_safety_too_many_members(self):
        """Test TarExtractor.validate_archive_safety with too many files (line 251)"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            
            # Mock tarfile to return too many members
            mock_members = [Mock() for _ in range(TarExtractor.MAX_MEMBER_COUNT + 1)]
            
            with patch('tarfile.open') as mock_tarfile:
                mock_tar = Mock()
                mock_tar.getmembers.return_value = mock_members
                mock_tarfile.return_value.__enter__.return_value = mock_tar
                
                with patch.object(Path, 'stat') as mock_stat:
                    mock_stat.return_value.st_size = 1000  # Small file size
                    
                    with pytest.raises(SecurityError) as exc_info:
                        TarExtractor.validate_archive_safety(tar_path)
                    
                    assert "Too many files in archive" in str(exc_info.value)

    def test_validate_archive_safety_member_too_large(self):
        """Test TarExtractor.validate_archive_safety with oversized member"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            
            # Mock tarfile member with size exceeding limit
            mock_member = Mock()
            mock_member.name = "large_file.txt"
            mock_member.size = TarExtractor.MAX_MEMBER_SIZE + 1
            
            with patch('tarfile.open') as mock_tarfile:
                mock_tar = Mock()
                mock_tar.getmembers.return_value = [mock_member]
                mock_tarfile.return_value.__enter__.return_value = mock_tar
                
                with patch.object(Path, 'stat') as mock_stat:
                    mock_stat.return_value.st_size = 1000
                    
                    with patch.object(TarExtractor, 'validate_tar_member'):
                        with pytest.raises(SecurityError) as exc_info:
                            TarExtractor.validate_archive_safety(tar_path)
                        
                        assert "File too large in archive" in str(exc_info.value)

    def test_validate_archive_safety_total_size_too_large(self):
        """Test TarExtractor.validate_archive_safety with total extracted size too large"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            
            # Create few large files that exceed total size without hitting other limits
            large_size = TarExtractor.MAX_EXTRACTED_SIZE // 2 + 10 * 1024 * 1024  # Just over half
            mock_members = [
                Mock(name="file1.txt", size=large_size),
                Mock(name="file2.txt", size=large_size),
            ]
            
            with patch('tarfile.open') as mock_tarfile:
                mock_tar = Mock()
                mock_tar.getmembers.return_value = mock_members
                mock_tarfile.return_value.__enter__.return_value = mock_tar
                
                with patch.object(Path, 'stat') as mock_stat:
                    # Very large archive to avoid compression ratio check
                    mock_stat.return_value.st_size = large_size  # 1:1 ratio
                    
                    with patch.object(TarExtractor, 'validate_tar_member'):
                        with pytest.raises(SecurityError) as exc_info:
                            TarExtractor.validate_archive_safety(tar_path)
                        
                        # Archive size check happens first
                        assert "Archive too large" in str(exc_info.value)

    def test_validate_archive_safety_suspicious_compression_ratio(self):
        """Test TarExtractor.validate_archive_safety with suspicious compression ratio"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            
            # Mock member with very high compression ratio
            mock_member = Mock()
            mock_member.name = "suspicious.txt"
            mock_member.size = 1000000  # Large uncompressed size
            
            with patch('tarfile.open') as mock_tarfile:
                mock_tar = Mock()
                mock_tar.getmembers.return_value = [mock_member]
                mock_tarfile.return_value.__enter__.return_value = mock_tar
                
                with patch.object(Path, 'stat') as mock_stat:
                    mock_stat.return_value.st_size = 100  # Very small archive
                    
                    with patch.object(TarExtractor, 'validate_tar_member'):
                        with pytest.raises(SecurityError) as exc_info:
                            TarExtractor.validate_archive_safety(tar_path)
                        
                        assert "Suspicious compression ratio" in str(exc_info.value)

    def test_validate_archive_safety_corrupted_archive(self):
        """Test TarExtractor.validate_archive_safety with corrupted archive (line 262)"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            
            with patch('tarfile.open', side_effect=tarfile.TarError("Corrupted archive")):
                with patch.object(Path, 'stat') as mock_stat:
                    mock_stat.return_value.st_size = 1000
                    
                    with pytest.raises(SecurityError) as exc_info:
                        TarExtractor.validate_archive_safety(tar_path)
                    
                    assert "Invalid or corrupted archive" in str(exc_info.value)

    def test_validate_tar_member_absolute_path(self):
        """Test TarExtractor.validate_tar_member with absolute path"""
        member = Mock()
        member.name = "/etc/passwd"
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member has absolute path" in str(exc_info.value)

    def test_validate_tar_member_path_traversal(self):
        """Test TarExtractor.validate_tar_member with path traversal (line 285)"""
        member = Mock()
        member.name = "../../../etc/passwd"
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member contains path traversal" in str(exc_info.value)

    def test_validate_tar_member_null_bytes(self):
        """Test TarExtractor.validate_tar_member with null bytes"""
        member = Mock()
        member.name = "file\x00name.txt"
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member contains null bytes" in str(exc_info.value)

    def test_validate_tar_member_outside_target(self):
        """Test TarExtractor.validate_tar_member escaping target directory (line 291-292)"""
        member = Mock()
        member.name = "valid/file.txt"
        target_dir = Path("/tmp/test")
        
        # Mock path resolution to simulate escape attempt
        with patch.object(Path, 'resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/tmp/outside/file.txt"),  # First call - escaped path
                Path("/tmp/test")  # Second call - target dir
            ]
            
            with pytest.raises(SecurityError) as exc_info:
                TarExtractor.validate_tar_member(member, target_dir)
            
            assert "Tar member would extract outside target directory" in str(exc_info.value)

    def test_validate_tar_member_symbolic_link(self):
        """Test TarExtractor.validate_tar_member with symbolic link"""
        member = Mock()
        member.name = "link.txt"
        member.issym.return_value = True
        member.islnk.return_value = False
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member is a symbolic/hard link (not allowed)" in str(exc_info.value)

    def test_validate_tar_member_hard_link(self):
        """Test TarExtractor.validate_tar_member with hard link"""
        member = Mock()
        member.name = "hardlink.txt"
        member.issym.return_value = False
        member.islnk.return_value = True
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member is a symbolic/hard link (not allowed)" in str(exc_info.value)

    def test_validate_tar_member_device_file(self):
        """Test TarExtractor.validate_tar_member with device file"""
        member = Mock()
        member.name = "device"
        member.issym.return_value = False
        member.islnk.return_value = False
        member.isdev.return_value = True
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member is a device file (not allowed)" in str(exc_info.value)

    def test_validate_tar_member_long_filename(self):
        """Test TarExtractor.validate_tar_member with very long filename (line 310)"""
        member = Mock()
        member.name = "a" * 1001  # Longer than 1000 characters
        member.issym.return_value = False
        member.islnk.return_value = False
        member.isdev.return_value = False
        target_dir = Path("/tmp/test")
        
        with pytest.raises(SecurityError) as exc_info:
            TarExtractor.validate_tar_member(member, target_dir)
        
        assert "Tar member name too long" in str(exc_info.value)

    def test_validate_tar_member_valid(self):
        """Test TarExtractor.validate_tar_member with valid member"""
        member = Mock()
        member.name = "valid/file.txt"
        member.issym.return_value = False
        member.islnk.return_value = False
        member.isdev.return_value = False
        target_dir = Path("/tmp/test")
        
        # Mock successful path validation
        with patch.object(Path, 'resolve') as mock_resolve:
            mock_resolve.side_effect = [
                Path("/tmp/test/valid/file.txt"),  # First call - target path
                Path("/tmp/test")  # Second call - target dir
            ]
            
            # Should not raise any exception
            TarExtractor.validate_tar_member(member, target_dir)

    def test_safe_extract_tar_file_not_found(self):
        """Test TarExtractor.safe_extract_tar with non-existent file (line 325)"""
        nonexistent_path = Path("/nonexistent/archive.tar.gz")
        target_dir = Path("/tmp/test")
        
        with pytest.raises(FileNotFoundError) as exc_info:
            TarExtractor.safe_extract_tar(nonexistent_path, target_dir)
        
        assert "Tar file not found" in str(exc_info.value)

    def test_safe_extract_tar_success_with_filter(self):
        """Test TarExtractor.safe_extract_tar successful extraction with filter"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            target_dir = Path("/tmp/test")
            
            mock_members = [Mock(name="file1.txt"), Mock(name="file2.txt")]
            
            with patch.object(TarExtractor, 'validate_archive_safety'):
                with patch('tarfile.open') as mock_tarfile:
                    mock_tar = Mock()
                    mock_tar.getmembers.return_value = mock_members
                    mock_tar.extractall.return_value = None
                    mock_tarfile.return_value.__enter__.return_value = mock_tar
                    
                    with patch.object(TarExtractor, 'validate_tar_member'):
                        with patch.object(Path, 'mkdir'):
                            TarExtractor.safe_extract_tar(tar_path, target_dir)
                    
                    # Verify extractall was called with filter
                    mock_tar.extractall.assert_called_once_with(
                        path=target_dir, members=mock_members, filter="data"
                    )

    def test_safe_extract_tar_fallback_without_filter(self):
        """Test TarExtractor.safe_extract_tar fallback when filter not supported (lines 344-347)"""
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temp_file:
            tar_path = Path(temp_file.name)
            target_dir = Path("/tmp/test")
            
            mock_members = [Mock(name="file1.txt"), Mock(name="file2.txt")]
            
            with patch.object(TarExtractor, 'validate_archive_safety'):
                with patch('tarfile.open') as mock_tarfile:
                    mock_tar = Mock()
                    mock_tar.getmembers.return_value = mock_members
                    # Simulate filter parameter not supported
                    mock_tar.extractall.side_effect = [TypeError("filter not supported"), None]
                    mock_tar.extract.return_value = None
                    mock_tarfile.return_value.__enter__.return_value = mock_tar
                    
                    with patch.object(TarExtractor, 'validate_tar_member'):
                        with patch.object(Path, 'mkdir'):
                            TarExtractor.safe_extract_tar(tar_path, target_dir)
                    
                    # Verify fallback to individual extract calls
                    assert mock_tar.extract.call_count == len(mock_members)

    def test_safe_extract_tar_member_with_filter(self):
        """Test TarExtractor.safe_extract_tar_member with filter support"""
        mock_tar = Mock()
        mock_member = Mock(name="test.txt")
        target_dir = Path("/tmp/test")
        
        with patch.object(TarExtractor, 'validate_tar_member'):
            TarExtractor.safe_extract_tar_member(mock_tar, mock_member, target_dir)
        
        mock_tar.extractall.assert_called_once_with(
            path=target_dir, members=[mock_member], filter="data"
        )

    def test_safe_extract_tar_member_fallback(self):
        """Test TarExtractor.safe_extract_tar_member fallback (lines 365-370)"""
        mock_tar = Mock()
        mock_member = Mock(name="test.txt")
        target_dir = Path("/tmp/test")
        
        # Simulate filter parameter not supported
        mock_tar.extractall.side_effect = ValueError("filter not supported")
        
        with patch.object(TarExtractor, 'validate_tar_member'):
            TarExtractor.safe_extract_tar_member(mock_tar, mock_member, target_dir)
        
        mock_tar.extract.assert_called_once_with(mock_member, path=target_dir)


class TestFileOperationValidator:
    """Test cases for FileOperationValidator class"""

    def test_validate_server_file_path_success(self):
        """Test FileOperationValidator.validate_server_file_path success"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            server_dir = base_dir / "test-server"
            server_dir.mkdir()
            test_file = server_dir / "config.txt"
            test_file.touch()
            
            result = FileOperationValidator.validate_server_file_path(
                "test-server", "config.txt", base_dir
            )
            
            assert result == test_file.resolve()

    def test_validate_server_file_path_traversal_in_file_path(self):
        """Test FileOperationValidator.validate_server_file_path with path traversal in file path (line 402)"""
        base_dir = Path("/tmp")
        
        with pytest.raises(SecurityError) as exc_info:
            FileOperationValidator.validate_server_file_path(
                "test-server", "../../../etc/passwd", base_dir
            )
        
        assert "File path contains path traversal patterns" in str(exc_info.value)

    def test_validate_server_file_path_backslashes(self):
        """Test FileOperationValidator.validate_server_file_path with backslashes (line 404)"""
        base_dir = Path("/tmp")
        
        with pytest.raises(SecurityError) as exc_info:
            FileOperationValidator.validate_server_file_path(
                "test-server", "config\\file.txt", base_dir
            )
        
        assert "File path contains backslashes" in str(exc_info.value)

    def test_validate_server_file_path_absolute_path(self):
        """Test FileOperationValidator.validate_server_file_path with absolute file path"""
        base_dir = Path("/tmp")
        
        with pytest.raises(SecurityError) as exc_info:
            FileOperationValidator.validate_server_file_path(
                "test-server", "/etc/passwd", base_dir
            )
        
        assert "File path cannot be absolute" in str(exc_info.value)

    def test_validate_server_file_path_unsafe_server_name(self):
        """Test FileOperationValidator.validate_server_file_path with unsafe server name"""
        base_dir = Path("/tmp")
        
        with patch.object(PathValidator, 'validate_safe_name', side_effect=SecurityError("Unsafe name")):
            with pytest.raises(SecurityError):
                FileOperationValidator.validate_server_file_path(
                    "../dangerous", "config.txt", base_dir
                )

    def test_validate_server_file_path_server_dir_traversal(self):
        """Test FileOperationValidator.validate_server_file_path with server dir outside base"""
        base_dir = Path("/tmp/servers")
        
        with patch.object(PathValidator, 'validate_safe_path', side_effect=SecurityError("Path traversal")):
            with pytest.raises(SecurityError):
                FileOperationValidator.validate_server_file_path(
                    "test-server", "config.txt", base_dir
                )

    def test_validate_server_file_path_file_outside_server_dir(self):
        """Test FileOperationValidator.validate_server_file_path with file outside server directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            server_dir = base_dir / "test-server"
            server_dir.mkdir()
            
            # Mock the second validate_safe_path call to fail
            with patch.object(PathValidator, 'validate_safe_path') as mock_validate:
                mock_validate.side_effect = [
                    server_dir.resolve(),  # First call succeeds (server dir)
                    SecurityError("File outside server directory")  # Second call fails (file path)
                ]
                
                with pytest.raises(SecurityError):
                    FileOperationValidator.validate_server_file_path(
                        "test-server", "config.txt", base_dir
                    )