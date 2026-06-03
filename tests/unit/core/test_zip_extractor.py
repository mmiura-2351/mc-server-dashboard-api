"""Security tests for `ZipExtractor`.

Companion to `tests/unit/core/test_tar_extractor.py` (Issue #407) — covers safe
zip member validation and the archive-safety limits enforced by
`app.core.security.ZipExtractor`, the ZIP counterpart of `TarExtractor`.
"""

import stat
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.security import SecurityError, ZipExtractor


def _make_zip(zip_path: Path, members: dict[str, bytes]) -> None:
    """Write a ZIP archive with the given ``name -> content`` members."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)


def _make_symlink_zip(zip_path: Path, name: str, target: str) -> None:
    """Write a ZIP archive containing a Unix symlink member."""
    info = zipfile.ZipInfo(name)
    # Encode S_IFLNK | 0o777 in the high 16 bits of external_attr, the way a
    # Unix `zip -y` would record a symlink.
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(info, target)


class TestZipExtractorMemberValidation:
    """Per-member validation via `validate_zip_member`."""

    def test_safe_member_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo("dir/safe_file.txt")
            # Should not raise.
            ZipExtractor.validate_zip_member(info, target_dir)

    @pytest.mark.parametrize(
        "name",
        [
            "../../../etc/passwd",
            "/etc/passwd",
            "normal/../../../etc/hosts",
            "..\\..\\windows\\system32",
        ],
    )
    def test_path_traversal_rejected(self, name):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo(name)
            with pytest.raises(SecurityError):
                ZipExtractor.validate_zip_member(info, target_dir)

    @pytest.mark.parametrize(
        "name",
        [
            "backup..2024.txt",
            "v1..2/notes.md",
            "dir/file..ext",
        ],
    )
    def test_dots_in_filename_accepted(self, name):
        """Names containing ".." as part of a component (not a traversal
        segment) must pass — the check is path-component based, not a bare
        substring (Issue #409)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo(name)
            # Should not raise.
            ZipExtractor.validate_zip_member(info, target_dir)

    def test_null_byte_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo("placeholder.txt")
            # ZipInfo truncates names at a null byte on construction, so assign
            # directly to exercise the defence-in-depth guard.
            info.filename = "evil\x00.txt"
            with pytest.raises(SecurityError, match="null bytes"):
                ZipExtractor.validate_zip_member(info, target_dir)

    def test_symlink_member_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with pytest.raises(SecurityError, match="symbolic link"):
                ZipExtractor.validate_zip_member(info, target_dir)

    def test_special_file_member_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo("fifo")
            info.external_attr = (stat.S_IFIFO | 0o644) << 16
            with pytest.raises(SecurityError, match="special file"):
                ZipExtractor.validate_zip_member(info, target_dir)

    def test_long_name_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            info = zipfile.ZipInfo("a" * 1001)
            with pytest.raises(SecurityError, match="too long"):
                ZipExtractor.validate_zip_member(info, target_dir)


class TestZipExtractorArchiveSafety:
    """Archive-level limits via `validate_archive_safety`."""

    def test_oversized_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "big.zip"
            _make_zip(zip_path, {"a.txt": b"hello"})
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = ZipExtractor.MAX_ARCHIVE_SIZE + 1
                with pytest.raises(SecurityError, match="Archive too large"):
                    ZipExtractor.validate_archive_safety(zip_path)

    def test_too_many_members_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "many.zip"
            _make_zip(zip_path, {f"f_{i}.txt": b"x" for i in range(6)})
            with patch.object(ZipExtractor, "MAX_MEMBER_COUNT", 5):
                with pytest.raises(SecurityError, match="Too many files"):
                    ZipExtractor.validate_archive_safety(zip_path)

    def test_oversized_member_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "bigmember.zip"
            _make_zip(zip_path, {"large.txt": b"x" * 2048})
            with patch.object(ZipExtractor, "MAX_MEMBER_SIZE", 1024):
                with pytest.raises(SecurityError, match="File too large"):
                    ZipExtractor.validate_archive_safety(zip_path)

    def test_highly_compressible_member_accepted(self):
        """A high compression ratio alone must not be rejected (PR #408).

        Sparse, well-compressing content (e.g. Minecraft ``.mca`` region files
        reaching ~999:1) is legitimate. The ZIP path bounds bomb damage via the
        absolute size caps, not a per-member ratio cap, so a tiny-compressed /
        large-uncompressed member within those caps passes validation.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "sparse.zip"
            payload = b"0" * (1024 * 1024)  # 1 MB of zeros -> ~1000:1 ratio
            _make_zip(zip_path, {"region.mca": payload})

            with zipfile.ZipFile(zip_path) as zf:
                info = zf.getinfo("region.mca")
                # Guard the premise: this really is a high-ratio member.
                assert info.file_size / max(1, info.compress_size) > 100

            # Should not raise — within MAX_MEMBER_SIZE / MAX_EXTRACTED_SIZE.
            ZipExtractor.validate_archive_safety(zip_path)

    def test_total_extracted_size_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "total.zip"
            members = {f"f_{i}.bin": bytes(range(256)) * 4 for i in range(3)}
            _make_zip(zip_path, members)
            with patch.object(ZipExtractor, "MAX_EXTRACTED_SIZE", 2048):
                with pytest.raises(
                    SecurityError, match="Total extracted size too large"
                ):
                    ZipExtractor.validate_archive_safety(zip_path)

    def test_corrupted_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "corrupt.zip"
            zip_path.write_bytes(b"not a zip file")
            with pytest.raises(SecurityError, match="Invalid or corrupted"):
                ZipExtractor.validate_archive_safety(zip_path)


class TestZipExtractorSafeExtract:
    """End-to-end extraction via `safe_extract_zip`."""

    def test_safe_archive_extracts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "safe.zip"
            _make_zip(zip_path, {"dir/safe.txt": b"safe content"})

            target_dir = temp_path / "extract"
            names = ZipExtractor.safe_extract_zip(zip_path, target_dir)

            extracted = target_dir / "dir" / "safe.txt"
            assert extracted.exists()
            assert extracted.read_text() == "safe content"
            assert "dir/safe.txt" in names

    def test_traversal_archive_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "evil.zip"
            _make_zip(
                zip_path,
                {"safe.txt": b"ok", "../escape.txt": b"pwned"},
            )

            target_dir = temp_path / "extract"
            with pytest.raises(SecurityError):
                ZipExtractor.safe_extract_zip(zip_path, target_dir)

            # Validation happens before extraction, so nothing escaped.
            assert not (temp_path / "escape.txt").exists()

    def test_symlink_archive_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "link.zip"
            _make_symlink_zip(zip_path, "link", "/etc/passwd")

            target_dir = temp_path / "extract"
            with pytest.raises(SecurityError, match="symbolic link"):
                ZipExtractor.safe_extract_zip(zip_path, target_dir)

    def test_missing_archive_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "nope.zip"
            with pytest.raises(FileNotFoundError):
                ZipExtractor.safe_extract_zip(zip_path, Path(temp_dir) / "out")
