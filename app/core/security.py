"""Security utilities for path validation and safe operations.

This module provides security utilities to prevent path traversal attacks
and other security vulnerabilities in file operations.
"""

import re
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Union


class SecurityError(Exception):
    """Raised when a security violation is detected."""

    pass


class PathValidator:
    """Utility class for validating and sanitizing file paths."""

    # Allow alphanumeric, hyphens, underscores, dots, and spaces (but not .. sequences)
    SAFE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_. -]+$")

    # Reserved names that should not be allowed
    RESERVED_NAMES = {
        ".",
        "..",
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    @staticmethod
    def validate_safe_name(name: str, max_length: int = 255) -> str:
        """Validate a name for use in file/directory operations.

        Args:
            name: The name to validate
            max_length: Maximum allowed length (default: 255)

        Returns:
            The validated name if safe

        Raises:
            SecurityError: If the name contains unsafe characters or patterns
        """
        if not name or not isinstance(name, str):
            raise SecurityError("Name must be a non-empty string")

        # Check length
        if len(name) > max_length:
            raise SecurityError(f"Name too long (max {max_length} characters)")

        # Check for invalid characters
        if not PathValidator.SAFE_NAME_PATTERN.match(name):
            raise SecurityError(
                "Name contains invalid characters. Only alphanumeric, hyphens, underscores, dots, and spaces are allowed"
            )

        # Check for reserved names
        if name.upper() in PathValidator.RESERVED_NAMES:
            raise SecurityError(f"'{name}' is a reserved name and cannot be used")

        # Check for path traversal patterns
        if ".." in name:
            raise SecurityError("Path traversal patterns (..) are not allowed")

        # Check for backslashes (can be used for path traversal on Windows)
        if "\\" in name:
            raise SecurityError("Backslashes are not allowed in names")

        # Check for starting/ending with dots (problematic on some systems)
        if name.startswith(".") or name.endswith("."):
            if name not in {".gitkeep", ".gitignore"}:  # Allow some common exceptions
                raise SecurityError("Names cannot start or end with dots")

        # Check for starting/ending with spaces (can cause issues)
        if name.startswith(" ") or name.endswith(" "):
            raise SecurityError("Names cannot start or end with spaces")

        return name

    @staticmethod
    def validate_safe_path(path: Union[str, Path], base_directory: Path) -> Path:
        """Validate that a path is safe and within the expected base directory.

        Args:
            path: The path to validate (can be string or Path object)
            base_directory: The base directory that the path should be contained within

        Returns:
            The resolved Path object if safe

        Raises:
            SecurityError: If the path is unsafe or attempts directory traversal
        """
        if isinstance(path, str):
            path = Path(path)

        try:
            # Resolve both paths to handle symlinks and relative paths
            resolved_path = path.resolve()
            resolved_base = base_directory.resolve()

            # Check if the resolved path is within the base directory
            resolved_path.relative_to(resolved_base)

            return resolved_path

        except ValueError as e:
            raise SecurityError(f"Path traversal attempt detected: {path}") from e
        except Exception as e:
            raise SecurityError(f"Invalid path: {path}") from e

    @staticmethod
    def create_safe_server_directory(server_name: str, base_directory: Path) -> Path:
        """Safely create a server directory with validation.

        Args:
            server_name: Name of the server (will be validated)
            base_directory: Base directory where server directories are stored

        Returns:
            Path to the created directory

        Raises:
            SecurityError: If server_name is unsafe
            FileExistsError: If directory already exists
        """
        # Convert server name to safe directory name
        safe_name = PathValidator.sanitize_directory_name(server_name)

        # Construct path
        server_dir = base_directory / safe_name

        # Validate the constructed path is within base directory
        validated_path = PathValidator.validate_safe_path(server_dir, base_directory)

        return validated_path

    @staticmethod
    def sanitize_directory_name(name: str) -> str:
        """Convert a server name to a safe directory name.

        Args:
            name: The original server name

        Returns:
            A safe directory name
        """
        # Replace spaces and other problematic characters with underscores
        safe_name = re.sub(r"[^\w\-.]", "_", name)
        # Remove multiple consecutive underscores
        safe_name = re.sub(r"_+", "_", safe_name)
        # Remove leading/trailing underscores and dots
        safe_name = safe_name.strip("_.")

        # Ensure it's not empty
        if not safe_name:
            safe_name = "server"

        return safe_name


class TarExtractor:
    """Secure tar file extraction utility."""

    # Security limits for archive extraction
    MAX_ARCHIVE_SIZE = 1024 * 1024 * 1024  # 1GB max archive size
    MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024  # 2GB max extracted size
    MAX_MEMBER_COUNT = 10000  # Maximum number of files in archive
    MAX_COMPRESSION_RATIO = 100  # Maximum compression ratio to prevent zip bombs
    MAX_MEMBER_SIZE = 100 * 1024 * 1024  # 100MB max individual file size

    @staticmethod
    def validate_archive_safety(tar_path: Path) -> None:
        """Validate archive safety before extraction.

        Args:
            tar_path: Path to the tar archive

        Raises:
            SecurityError: If the archive is unsafe
        """
        if not tar_path.exists():
            raise SecurityError(f"Archive not found: {tar_path}")

        # Check archive size
        archive_size = tar_path.stat().st_size
        if archive_size > TarExtractor.MAX_ARCHIVE_SIZE:
            raise SecurityError(
                f"Archive too large: {archive_size} bytes (max {TarExtractor.MAX_ARCHIVE_SIZE})"
            )

        # Validate archive contents
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                members = tar.getmembers()

                # Check member count
                if len(members) > TarExtractor.MAX_MEMBER_COUNT:
                    raise SecurityError(
                        f"Too many files in archive: {len(members)} (max {TarExtractor.MAX_MEMBER_COUNT})"
                    )

                total_extracted_size = 0

                for member in members:
                    # Validate member for path traversal and other security issues
                    # Use a dummy target directory for validation (we're not extracting here)
                    dummy_target = Path("/tmp/dummy")
                    TarExtractor.validate_tar_member(member, dummy_target)

                    # Check individual member size
                    if member.size > TarExtractor.MAX_MEMBER_SIZE:
                        raise SecurityError(
                            f"File too large in archive: {member.name} - {member.size} bytes"
                        )

                    total_extracted_size += member.size

                    # Check compression ratio for each member
                    if member.size > 0:
                        # Approximate compressed size (this is a rough estimate)
                        compressed_size = max(
                            1, archive_size // len(members)
                        )  # Simple heuristic
                        compression_ratio = member.size / compressed_size

                        if compression_ratio > TarExtractor.MAX_COMPRESSION_RATIO:
                            raise SecurityError(
                                f"Suspicious compression ratio for {member.name}: {compression_ratio:.1f}"
                            )

                # Check total extracted size
                if total_extracted_size > TarExtractor.MAX_EXTRACTED_SIZE:
                    raise SecurityError(
                        f"Total extracted size too large: {total_extracted_size} bytes"
                    )

        except tarfile.TarError as e:
            raise SecurityError(f"Invalid or corrupted archive: {e}")

    @staticmethod
    def validate_tar_member(member: tarfile.TarInfo, target_dir: Path) -> None:
        """Validate a tar member for safe extraction.

        Args:
            member: The tar member to validate
            target_dir: Target directory for extraction

        Raises:
            SecurityError: If the member is unsafe for extraction
        """
        # Check for absolute paths
        if member.name.startswith("/"):
            raise SecurityError(f"Tar member has absolute path: {member.name}")

        # Check for path traversal sequences
        if ".." in member.name:
            raise SecurityError(f"Tar member contains path traversal: {member.name}")

        # Check for null bytes (can cause issues)
        if "\x00" in member.name:
            raise SecurityError(f"Tar member contains null bytes: {member.name}")

        # Validate the target path would be within the target directory
        target_path = target_dir / member.name
        try:
            target_path.resolve().relative_to(target_dir.resolve())
        except ValueError as e:
            raise SecurityError(
                f"Tar member would extract outside target directory: {member.name}"
            ) from e

        # Check for suspicious file types
        if member.issym() or member.islnk():
            raise SecurityError(
                f"Tar member is a symbolic/hard link (not allowed): {member.name}"
            )

        # Check for device files
        if member.isdev():
            raise SecurityError(
                f"Tar member is a device file (not allowed): {member.name}"
            )

        # Check for very long filenames that could cause issues
        if len(member.name) > 1000:
            raise SecurityError(f"Tar member name too long: {member.name[:100]}...")

    @staticmethod
    def safe_extract_tar(tar_path: Path, target_dir: Path) -> None:
        """Safely extract a tar file with comprehensive security validation.

        Args:
            tar_path: Path to the tar file to extract
            target_dir: Directory to extract to

        Raises:
            SecurityError: If any tar member is unsafe or archive is malicious
            FileNotFoundError: If tar file doesn't exist
        """
        if not tar_path.exists():
            raise FileNotFoundError(f"Tar file not found: {tar_path}")

        # First, validate archive safety (size, member count, compression ratio)
        TarExtractor.validate_archive_safety(tar_path)

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(tar_path, "r:gz") as tar:
            # Validate all members before extracting any
            members = tar.getmembers()

            for member in members:
                TarExtractor.validate_tar_member(member, target_dir)

            # If all members are safe, extract them with future-compatible filter
            try:
                # Use the safer extract method for Python 3.14+ compatibility
                tar.extractall(path=target_dir, members=members, filter="data")
            except (TypeError, ValueError):
                # Fallback for older Python versions without filter support
                for member in members:
                    tar.extract(member, path=target_dir)

    @staticmethod
    def safe_extract_tar_member(
        tar: tarfile.TarFile, member: tarfile.TarInfo, target_dir: Path
    ) -> None:
        """Safely extract a single tar member.

        Args:
            tar: Open tar file object
            member: The member to extract
            target_dir: Target directory for extraction

        Raises:
            SecurityError: If the member is unsafe for extraction
        """
        TarExtractor.validate_tar_member(member, target_dir)

        try:
            # Use safer extraction method for Python 3.14+ compatibility
            tar.extractall(path=target_dir, members=[member], filter="data")
        except (TypeError, ValueError):
            # Fallback for older Python versions without filter support
            tar.extract(member, path=target_dir)


class ZipExtractor:
    """Secure zip file extraction utility.

    Mirrors ``TarExtractor`` for ZIP archives. Python's ``zipfile`` sanitises
    member names on extraction, but it does not enforce size/ratio caps and
    silently drops unsafe components rather than rejecting the archive, so the
    same per-member and archive-level validation is applied here before
    extracting anything. Limits are shared with ``TarExtractor`` so both
    archive paths stay in lock-step.
    """

    # Reuse the tar limits so both archive paths share one source of truth.
    MAX_ARCHIVE_SIZE = TarExtractor.MAX_ARCHIVE_SIZE
    MAX_EXTRACTED_SIZE = TarExtractor.MAX_EXTRACTED_SIZE
    MAX_MEMBER_COUNT = TarExtractor.MAX_MEMBER_COUNT
    MAX_COMPRESSION_RATIO = TarExtractor.MAX_COMPRESSION_RATIO
    MAX_MEMBER_SIZE = TarExtractor.MAX_MEMBER_SIZE

    @staticmethod
    def validate_zip_member(info: zipfile.ZipInfo, target_dir: Path) -> None:
        """Validate a zip member for safe extraction.

        Args:
            info: The zip member to validate
            target_dir: Target directory for extraction

        Raises:
            SecurityError: If the member is unsafe for extraction
        """
        name = info.filename

        # Check for absolute paths (POSIX and Windows drive/UNC roots)
        if name.startswith("/") or name.startswith("\\"):
            raise SecurityError(f"Zip member has absolute path: {name}")

        # Check for path traversal sequences
        if ".." in name:
            raise SecurityError(f"Zip member contains path traversal: {name}")

        # Check for null bytes (can cause issues)
        if "\x00" in name:
            raise SecurityError(f"Zip member contains null bytes: {name}")

        # Reject backslashes outright: ZIP names are forward-slash separated, so
        # a backslash is either a Windows traversal attempt or a literal that
        # would be misinterpreted on extraction.
        if "\\" in name:
            raise SecurityError(f"Zip member contains backslashes: {name}")

        # Validate the target path would be within the target directory
        target_path = target_dir / name
        try:
            target_path.resolve().relative_to(target_dir.resolve())
        except ValueError as e:
            raise SecurityError(
                f"Zip member would extract outside target directory: {name}"
            ) from e

        # Reject symlink / non-regular members. ZIP encodes the Unix mode in the
        # high 16 bits of ``external_attr``; default ``zipfile`` does not follow
        # symlinks but extracting them is still a defence-in-depth risk.
        mode = info.external_attr >> 16
        if mode:
            if stat.S_ISLNK(mode):
                raise SecurityError(
                    f"Zip member is a symbolic link (not allowed): {name}"
                )
            if (
                stat.S_ISBLK(mode)
                or stat.S_ISCHR(mode)
                or stat.S_ISFIFO(mode)
                or stat.S_ISSOCK(mode)
            ):
                raise SecurityError(f"Zip member is a special file (not allowed): {name}")

        # Check for very long filenames that could cause issues
        if len(name) > 1000:
            raise SecurityError(f"Zip member name too long: {name[:100]}...")

    @staticmethod
    def validate_archive_safety(zip_path: Path) -> None:
        """Validate zip archive safety before extraction.

        Args:
            zip_path: Path to the zip archive

        Raises:
            SecurityError: If the archive is unsafe
        """
        if not zip_path.exists():
            raise SecurityError(f"Archive not found: {zip_path}")

        # Check archive size
        archive_size = zip_path.stat().st_size
        if archive_size > ZipExtractor.MAX_ARCHIVE_SIZE:
            raise SecurityError(
                f"Archive too large: {archive_size} bytes "
                f"(max {ZipExtractor.MAX_ARCHIVE_SIZE})"
            )

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                members = zip_ref.infolist()

                # Check member count
                if len(members) > ZipExtractor.MAX_MEMBER_COUNT:
                    raise SecurityError(
                        f"Too many files in archive: {len(members)} "
                        f"(max {ZipExtractor.MAX_MEMBER_COUNT})"
                    )

                total_extracted_size = 0

                for info in members:
                    # Path-traversal / symlink / null-byte validation. Use a
                    # dummy target since we are only inspecting, not extracting.
                    dummy_target = Path("/tmp/dummy")
                    ZipExtractor.validate_zip_member(info, dummy_target)

                    # Check individual member size (uncompressed)
                    if info.file_size > ZipExtractor.MAX_MEMBER_SIZE:
                        raise SecurityError(
                            f"File too large in archive: {info.filename} - "
                            f"{info.file_size} bytes"
                        )

                    total_extracted_size += info.file_size

                    # Check per-member compression ratio to catch zip bombs. ZIP
                    # records the true compressed size per member, so this is an
                    # exact ratio rather than the tar heuristic.
                    if info.file_size > 0:
                        compressed_size = max(1, info.compress_size)
                        compression_ratio = info.file_size / compressed_size
                        if compression_ratio > ZipExtractor.MAX_COMPRESSION_RATIO:
                            raise SecurityError(
                                f"Suspicious compression ratio for "
                                f"{info.filename}: {compression_ratio:.1f}"
                            )

                # Check total extracted size
                if total_extracted_size > ZipExtractor.MAX_EXTRACTED_SIZE:
                    raise SecurityError(
                        f"Total extracted size too large: {total_extracted_size} bytes"
                    )

        except zipfile.BadZipFile as e:
            raise SecurityError(f"Invalid or corrupted archive: {e}") from e

    @staticmethod
    def safe_extract_zip(zip_path: Path, target_dir: Path) -> list[str]:
        """Safely extract a zip file with comprehensive security validation.

        Args:
            zip_path: Path to the zip file to extract
            target_dir: Directory to extract to

        Returns:
            The list of member names contained in the archive.

        Raises:
            SecurityError: If any zip member is unsafe or the archive is malicious
            FileNotFoundError: If the zip file doesn't exist
        """
        if not zip_path.exists():
            raise FileNotFoundError(f"Zip file not found: {zip_path}")

        # First, validate archive safety (size, member count, compression ratio).
        ZipExtractor.validate_archive_safety(zip_path)

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            members = zip_ref.infolist()

            # Validate every member against the real target before extracting any.
            for info in members:
                ZipExtractor.validate_zip_member(info, target_dir)

            # All members are safe; extract them.
            zip_ref.extractall(target_dir)
            return zip_ref.namelist()


class FileOperationValidator:
    """Validator for general file operations."""

    @staticmethod
    def validate_server_file_path(
        server_name: str, file_path: str, base_directory: Path
    ) -> Path:
        """Validate a file path within a server directory.

        Args:
            server_name: Name of the server
            file_path: Relative path within the server directory
            base_directory: Base directory containing server directories

        Returns:
            Validated full path to the file

        Raises:
            SecurityError: If the path is unsafe
        """
        # Validate server name
        safe_server_name = PathValidator.validate_safe_name(server_name)

        # Validate file path for common path traversal patterns
        if ".." in file_path:
            raise SecurityError(
                f"File path contains path traversal patterns: {file_path}"
            )
        if "\\" in file_path:
            raise SecurityError(f"File path contains backslashes: {file_path}")
        if file_path.startswith("/"):
            raise SecurityError(f"File path cannot be absolute: {file_path}")

        # Construct server directory path
        server_dir = base_directory / safe_server_name

        # Validate server directory is within base
        validated_server_dir = PathValidator.validate_safe_path(
            server_dir, base_directory
        )

        # Construct full file path
        full_file_path = validated_server_dir / file_path

        # Validate the file path is within the server directory
        validated_file_path = PathValidator.validate_safe_path(
            full_file_path, validated_server_dir
        )

        return validated_file_path
