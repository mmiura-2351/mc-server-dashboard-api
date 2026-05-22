"""Security tests for `TarExtractor`.

Split from `tests/test_security.py` (Issue #170) — covers safe tar member
validation and the archive-safety limits enforced by
`app.core.security.TarExtractor`.
"""

import io
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.security import SecurityError, TarExtractor


class TestTarExtractor:
    """Test secure tar extraction utilities."""

    def create_malicious_tar(self, temp_dir: Path) -> Path:
        """Create a tar file with malicious paths for testing."""
        tar_path = temp_dir / "malicious.tar.gz"

        with tarfile.open(tar_path, "w:gz") as tar:
            # Add a safe file
            safe_info = tarfile.TarInfo("safe_file.txt")
            safe_info.size = 5
            tar.addfile(safe_info, io.BytesIO(b"safe\n"))

            # Add a malicious file with path traversal
            malicious_info = tarfile.TarInfo("../../../etc/passwd")
            malicious_info.size = 7
            tar.addfile(malicious_info, io.BytesIO(b"hacked\n"))

        return tar_path

    def test_validate_tar_member_safe_file(self):
        """Test that safe tar members pass validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)

            # Create a safe tar member
            member = tarfile.TarInfo("safe_file.txt")
            member.size = 5

            # Should not raise an exception
            TarExtractor.validate_tar_member(member, target_dir)

    def test_validate_tar_member_path_traversal(self):
        """Test that tar members with path traversal are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)

            # Test various path traversal patterns
            malicious_names = [
                "../../../etc/passwd",
                "/etc/passwd",
                "..\\..\\..\\windows\\system32",
                "normal/../../../etc/hosts",
            ]

            for name in malicious_names:
                member = tarfile.TarInfo(name)
                member.size = 5

                with pytest.raises(SecurityError):
                    TarExtractor.validate_tar_member(member, target_dir)

    def test_validate_tar_member_symlinks(self):
        """Test that symbolic links are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)

            # Create a symbolic link tar member
            member = tarfile.TarInfo("symlink")
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"

            with pytest.raises(SecurityError, match="symbolic"):
                TarExtractor.validate_tar_member(member, target_dir)

    def test_validate_tar_member_device_files(self):
        """Test that device files are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)

            # Create a device file tar member
            member = tarfile.TarInfo("device")
            member.type = tarfile.CHRTYPE

            with pytest.raises(SecurityError, match="device file"):
                TarExtractor.validate_tar_member(member, target_dir)

    def test_safe_extract_tar_malicious_archive(self):
        """Test that malicious tar archives are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            target_dir = temp_path / "extract"
            target_dir.mkdir()

            # Create malicious tar
            malicious_tar = self.create_malicious_tar(temp_path)

            # Should raise SecurityError due to path traversal
            with pytest.raises(SecurityError):
                TarExtractor.safe_extract_tar(malicious_tar, target_dir)

    def test_safe_extract_tar_safe_archive(self):
        """Test that safe tar archives extract correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            target_dir = temp_path / "extract"
            target_dir.mkdir()

            # Create safe tar
            safe_tar = temp_path / "safe.tar.gz"
            with tarfile.open(safe_tar, "w:gz") as tar:
                safe_info = tarfile.TarInfo("safe_file.txt")
                safe_info.size = 12
                tar.addfile(safe_info, io.BytesIO(b"safe content"))

            # Should extract without issues
            TarExtractor.safe_extract_tar(safe_tar, target_dir)

            # Verify file was extracted
            extracted_file = target_dir / "safe_file.txt"
            assert extracted_file.exists()
            assert extracted_file.read_text() == "safe content"

    def test_validate_archive_safety_oversized_archive(self):
        """Test that oversized archives are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a mock large archive by creating a file and checking if validation would catch it
            large_archive = temp_path / "large.tar.gz"

            # Create a file larger than the limit (simulate by patching the size check)
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = TarExtractor.MAX_ARCHIVE_SIZE + 1

                with pytest.raises(SecurityError, match="Archive too large"):
                    TarExtractor.validate_archive_safety(large_archive)

    def test_validate_archive_safety_too_many_members(self):
        """Test that archives with too many members are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            many_members_tar = temp_path / "many_members.tar.gz"

            # Create archive with many members (use a smaller number for testing)
            test_limit = 5  # Use smaller limit for testing
            with patch.object(TarExtractor, "MAX_MEMBER_COUNT", test_limit):
                with tarfile.open(many_members_tar, "w:gz") as tar:
                    # Add more members than the limit
                    for i in range(test_limit + 1):
                        member = tarfile.TarInfo(f"file_{i}.txt")
                        member.size = 5
                        tar.addfile(member, io.BytesIO(b"test\n"))

                with pytest.raises(SecurityError, match="Too many files"):
                    TarExtractor.validate_archive_safety(many_members_tar)

    def test_validate_archive_safety_oversized_member(self):
        """Test that archives with oversized individual members are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            large_member_tar = temp_path / "large_member.tar.gz"

            # Create archive with a large member
            test_limit = 1000  # Use smaller limit for testing
            with patch.object(TarExtractor, "MAX_MEMBER_SIZE", test_limit):
                with tarfile.open(large_member_tar, "w:gz") as tar:
                    member = tarfile.TarInfo("large_file.txt")
                    member.size = test_limit + 1
                    tar.addfile(member, io.BytesIO(b"x" * (test_limit + 1)))

                with pytest.raises(SecurityError, match="File too large"):
                    TarExtractor.validate_archive_safety(large_member_tar)

    def test_validate_archive_safety_total_size_too_large(self):
        """Test that archives with total extracted size too large are rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            large_total_tar = temp_path / "large_total.tar.gz"

            # Create archive where total extracted size exceeds limit
            test_limit = 2000  # Use smaller limit for testing
            with patch.object(TarExtractor, "MAX_EXTRACTED_SIZE", test_limit):
                with tarfile.open(large_total_tar, "w:gz") as tar:
                    # Add multiple files that together exceed the limit
                    for i in range(3):
                        member = tarfile.TarInfo(f"file_{i}.txt")
                        member.size = 800  # 3 * 800 = 2400 > 2000
                        tar.addfile(member, io.BytesIO(b"x" * 800))

                with pytest.raises(SecurityError, match="Total extracted size too large"):
                    TarExtractor.validate_archive_safety(large_total_tar)
