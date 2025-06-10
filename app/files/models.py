"""
File edit history models for tracking file changes.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class FileEditHistory(Base):
    """File edit history tracking model"""

    __tablename__ = "file_edit_history"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    file_path = Column(String(500), nullable=False)  # Relative path from server root
    version_number = Column(Integer, nullable=False)
    backup_file_path = Column(String(500), nullable=False)  # Absolute path to backup file
    file_size = Column(BigInteger, nullable=False)
    content_hash = Column(
        String(64), nullable=True
    )  # SHA256 hash for duplicate detection
    editor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    description = Column(Text, nullable=True)  # Optional description of the edit

    # Relationships
    server = relationship("Server", back_populates="file_edit_history")
    editor = relationship("User")

    def __repr__(self):
        return f"<FileEditHistory(id={self.id}, server_id={self.server_id}, file_path={self.file_path}, version={self.version_number})>"
