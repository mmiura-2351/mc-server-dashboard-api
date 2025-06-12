import json
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Integer, nullable=True)
    details = Column(JSON)
    ip_address = Column(String(45))  # IPv6 support
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User")

    def get_details(self) -> Dict[str, Any]:
        """Get details as Python dict"""
        if isinstance(self.details, str):
            return json.loads(self.details)
        return self.details or {}

    def set_details(self, details: Dict[str, Any]) -> None:
        """Set details from Python dict"""
        self.details = details

    @classmethod
    def create_log(
        cls,
        action: str,
        resource_type: str,
        user_id: Optional[int] = None,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ):
        """Create a new audit log entry"""
        log = cls(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
        )
        if details:
            log.set_details(details)
        return log
