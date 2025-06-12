"""
Encoding detection and handling service for file operations.
"""

from typing import Tuple

import chardet


class EncodingHandler:
    """Handle file encoding detection and conversion."""

    # Common encodings to try in order of likelihood
    COMMON_ENCODINGS = [
        "utf-8",
        "shift_jis",
        "euc-jp",
        "iso-2022-jp",
        "cp932",  # Windows Japanese
        "latin1",
        "cp1252",  # Windows Western
        "ascii",
    ]

    @staticmethod
    def read_file_with_encoding_detection(file_path: str) -> Tuple[str, str]:
        """
        Read file with automatic encoding detection.

        Args:
            file_path: Path to the file to read

        Returns:
            Tuple of (file_content, detected_encoding)

        Raises:
            UnicodeDecodeError: If no encoding works
            FileNotFoundError: If file doesn't exist
        """
        # First, try to detect encoding using chardet
        try:
            with open(file_path, "rb") as f:
                raw_data = f.read()

            # Use chardet for detection
            detection_result = chardet.detect(raw_data)
            detected_encoding = detection_result.get("encoding")
            confidence = detection_result.get("confidence", 0)

            # If confidence is high enough, try the detected encoding first
            if detected_encoding and confidence > 0.7:
                try:
                    content = raw_data.decode(detected_encoding)
                    return content, detected_encoding
                except UnicodeDecodeError:
                    pass  # Fall back to trying common encodings

        except Exception:
            pass  # Fall back to trying common encodings

        # Try common encodings one by one
        for encoding in EncodingHandler.COMMON_ENCODINGS:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                return content, encoding
            except UnicodeDecodeError:
                continue
            except Exception as e:
                # Handle other file errors
                raise e

        # If all encodings fail, try with error handling
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return content, "utf-8 (with replacement)"
        except Exception as e:
            raise UnicodeDecodeError(
                f"Could not decode file {file_path} with any common encoding"
            ) from e

    @staticmethod
    def safe_read_text_file(file_path: str) -> dict:
        """
        Safely read a text file with encoding detection.

        Returns:
            Dictionary with content, encoding, and success status
        """
        try:
            content, encoding = EncodingHandler.read_file_with_encoding_detection(
                file_path
            )
            return {
                "success": True,
                "content": content,
                "encoding": encoding,
                "error": None,
            }
        except Exception as e:
            return {"success": False, "content": "", "encoding": None, "error": str(e)}
