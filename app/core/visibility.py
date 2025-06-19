"""
Resource Visibility System Models and Enums

Phase 2 implementation of the shared resource access model with granular visibility controls.
"""

from enum import Enum
from typing import List

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.users.models import Role


class VisibilityType(str, Enum):
    """Enumeration of resource visibility types"""

    PRIVATE = "private"  # Only owner + admins can access
    SPECIFIC_USERS = "specific_users"  # Owner + specified users + admins
    ROLE_BASED = "role_based"  # Users with certain roles + owner + admins
    PUBLIC = "public"  # Everyone can access (Phase 1 behavior)


class ResourceType(str, Enum):
    """Enumeration of resource types that support visibility controls"""

    SERVER = "server"
    GROUP = "group"
    # Future extensions:
    # TEMPLATE = "template"
    # BACKUP = "backup"


class ResourceVisibility(Base):
    """
    Resource visibility configuration model

    Defines how a specific resource can be accessed by users.
    Supports multiple visibility patterns for flexible access control.
    """

    __tablename__ = "resource_visibility"

    id = Column(Integer, primary_key=True, index=True)

    # Resource identification
    resource_type = Column(SQLEnum(ResourceType), nullable=False, index=True)
    resource_id = Column(Integer, nullable=False, index=True)

    # Visibility configuration
    visibility_type = Column(
        SQLEnum(VisibilityType), nullable=False, default=VisibilityType.PRIVATE
    )
    role_restriction = Column(SQLEnum(Role), nullable=True)  # For role_based visibility

    # Metadata
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user_access_grants = relationship(
        "ResourceUserAccess",
        back_populates="visibility",
        cascade="all, delete-orphan",
        lazy="dynamic",  # Changed from selectin to dynamic for better performance on large datasets
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_resource_visibility"),
        {"comment": "Resource visibility configuration for granular access control"},
    )

    def __repr__(self):
        return (
            f"<ResourceVisibility(id={self.id}, "
            f"resource_type={self.resource_type.value}, "
            f"resource_id={self.resource_id}, "
            f"visibility_type={self.visibility_type.value})>"
        )

    def has_user_access(self, user_id: int) -> bool:
        """Check if a specific user has been granted access to this resource"""
        if self.visibility_type != VisibilityType.SPECIFIC_USERS:
            return False
        return any(grant.user_id == user_id for grant in self.user_access_grants)

    def get_granted_users(self) -> List[int]:
        """Get list of user IDs that have been granted specific access"""
        return [grant.user_id for grant in self.user_access_grants]


class ResourceUserAccess(Base):
    """
    Specific user access grants for resources

    Used when visibility_type is SPECIFIC_USERS to track which users
    have been explicitly granted access to a resource.
    """

    __tablename__ = "resource_user_access"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign keys
    resource_visibility_id = Column(
        Integer,
        ForeignKey("resource_visibility.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granted_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Metadata
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    visibility = relationship("ResourceVisibility", back_populates="user_access_grants")
    user = relationship(
        "User", foreign_keys=[user_id], lazy="joined"
    )  # Optimized for common access patterns
    granted_by = relationship(
        "User", foreign_keys=[granted_by_user_id], lazy="select"
    )  # Less frequently accessed

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "resource_visibility_id", "user_id", name="uq_resource_user_access"
        ),
        {
            "comment": "Specific user access grants for resources with SPECIFIC_USERS visibility"
        },
    )

    def __repr__(self):
        return (
            f"<ResourceUserAccess(id={self.id}, "
            f"resource_visibility_id={self.resource_visibility_id}, "
            f"user_id={self.user_id}, "
            f"granted_by_user_id={self.granted_by_user_id})>"
        )


# Export the main classes and enums
__all__ = ["VisibilityType", "ResourceType", "ResourceVisibility", "ResourceUserAccess"]
