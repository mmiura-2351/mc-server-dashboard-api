"""
Database models for Minecraft version management
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.core.database import Base


class MinecraftVersion(Base):
    """
    Minecraft version information stored in database

    This replaces the real-time external API calls with cached database lookups,
    improving response time from 4-5 seconds to 10-50ms.
    """

    __tablename__ = "minecraft_versions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Version identification
    server_type = Column(
        String(20), nullable=False, index=True
    )  # 'vanilla', 'paper', 'forge'
    version = Column(String(50), nullable=False, index=True)  # '1.21.6'

    # Download information
    download_url = Column(Text, nullable=False)  # Full download URL

    # Version metadata
    release_date = Column(DateTime, nullable=True)  # Release date from API
    is_stable = Column(Boolean, default=True, nullable=False)  # Stable release flag
    build_number = Column(Integer, nullable=True)  # PaperMC build number

    # Management flags
    is_active = Column(
        Boolean, default=True, nullable=False, index=True
    )  # Active/inactive flag

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Indexes for performance
    __table_args__ = (
        # Unique constraint to prevent duplicates
        Index("idx_unique_server_version", "server_type", "version", unique=True),
        # Composite indexes for common queries
        Index("idx_server_type_active", "server_type", "is_active"),
        Index("idx_version_active", "version", "is_active"),
        Index("idx_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<MinecraftVersion({self.server_type} {self.version}, active={self.is_active})>"

    @property
    def version_tuple(self) -> tuple:
        """Convert version string to tuple for sorting"""
        try:
            # Split by dots and handle pre-release suffixes
            parts = self.version.split(".")
            numeric_parts = []

            for part in parts:
                # Extract numeric part before any non-numeric characters (e.g., "6-pre1" -> "6")
                numeric_part = ""
                for char in part:
                    if char.isdigit():
                        numeric_part += char
                    else:
                        break

                if numeric_part:
                    numeric_parts.append(int(numeric_part))

            return tuple(numeric_parts) if numeric_parts else (0, 0, 0)
        except (ValueError, AttributeError):
            return (0, 0, 0)


class VersionUpdateLog(Base):
    """
    Log of version update operations for monitoring and debugging
    """

    __tablename__ = "version_update_logs"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Update operation details
    update_type = Column(
        String(20), nullable=False, index=True
    )  # 'manual', 'scheduled', 'startup'
    server_type = Column(String(20), nullable=True)  # NULL = all types

    # Operation results
    versions_added = Column(Integer, default=0, nullable=False)  # New versions added
    versions_updated = Column(
        Integer, default=0, nullable=False
    )  # Existing versions updated
    versions_removed = Column(Integer, default=0, nullable=False)  # Versions deactivated

    # Performance metrics
    execution_time_ms = Column(Integer, nullable=True)  # Execution time in milliseconds
    external_api_calls = Column(
        Integer, default=0, nullable=False
    )  # Number of API calls made

    # Status and error tracking
    status = Column(
        String(20), nullable=False, index=True
    )  # 'success', 'failed', 'partial'
    error_message = Column(Text, nullable=True)  # Error details if failed

    # User tracking (for manual updates)
    executed_by_user_id = Column(Integer, nullable=True)  # User ID for manual updates

    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)

    # Indexes for performance
    __table_args__ = (
        Index("idx_update_type_status", "update_type", "status"),
        Index("idx_started_at_desc", "started_at", postgresql_using="btree"),
        Index("idx_server_type_started", "server_type", "started_at"),
    )

    def __repr__(self) -> str:
        return f"<VersionUpdateLog({self.update_type}, {self.status}, {self.started_at})>"

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate operation duration in seconds"""
        if self.execution_time_ms is not None:
            return self.execution_time_ms / 1000.0
        elif self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds()
        return None

    @property
    def total_changes(self) -> int:
        """Total number of version changes made"""
        return (
            (self.versions_added or 0)
            + (self.versions_updated or 0)
            + (self.versions_removed or 0)
        )
