"""Tests for `FileOperationService.extract_archive` (Issue #407).

Focus on the security wiring: ZIP uploads go through `ZipExtractor` and an
unsafe archive surfaces as a 400 `InvalidRequestException`, not a 500.
"""

import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.exceptions import InvalidRequestException
from app.files.application.file_io import FileBackupService, FileOperationService


def _service() -> FileOperationService:
    return FileOperationService(backup_service=Mock(spec=FileBackupService))


def _make_zip(zip_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)


def test_extract_safe_zip_returns_member_names(tmp_path):
    zip_path = tmp_path / "good.zip"
    _make_zip(zip_path, {"dir/a.txt": b"alpha", "b.txt": b"beta"})
    target = tmp_path / "out"

    names = _service().extract_archive(zip_path, target)

    assert set(names) == {"dir/a.txt", "b.txt"}
    assert (target / "dir" / "a.txt").read_text() == "alpha"


def test_traversal_zip_rejected_as_bad_request(tmp_path):
    zip_path = tmp_path / "evil.zip"
    _make_zip(zip_path, {"ok.txt": b"ok", "../escape.txt": b"pwned"})
    target = tmp_path / "out"

    with pytest.raises(InvalidRequestException) as exc:
        _service().extract_archive(zip_path, target)

    assert exc.value.status_code == 400
    # Nothing escaped the target directory.
    assert not (tmp_path / "escape.txt").exists()


def test_non_zip_archive_rejected_as_bad_request(tmp_path):
    archive = tmp_path / "data.tar.gz"
    archive.write_bytes(b"irrelevant")

    with pytest.raises(InvalidRequestException) as exc:
        _service().extract_archive(archive, tmp_path / "out")

    assert exc.value.status_code == 400
    assert "Unsupported archive format" in str(exc.value.detail)
