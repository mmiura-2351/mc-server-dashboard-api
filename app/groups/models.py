import enum
import json
from typing import Any, Dict, List

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class GroupType(enum.Enum):
    op = "op"
    whitelist = "whitelist"


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    type = Column(Enum(GroupType), nullable=False)
    players = Column(JSON, nullable=False)  # Array of player objects
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_template = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner = relationship("User", back_populates="groups")
    server_groups = relationship(
        "ServerGroup", back_populates="group", cascade="all, delete-orphan"
    )

    def get_players(self) -> List[Dict[str, Any]]:
        """Get players as Python list"""
        if isinstance(self.players, str):
            return json.loads(self.players)
        return self.players or []

    def set_players(self, players: List[Dict[str, Any]]) -> None:
        """Set players from Python list"""
        self.players = players

    def add_player(self, uuid: str, username: str) -> None:
        """Add a player to the group"""
        players = self.get_players()

        # Check if player already exists
        for player in players:
            if player.get("uuid") == uuid:
                # Update username if different
                if player.get("username") != username:
                    player["username"] = username
                return

        # Add new player
        from datetime import datetime

        players.append(
            {"uuid": uuid, "username": username, "added_at": datetime.now().isoformat()}
        )
        self.set_players(players)

    def remove_player(self, uuid: str) -> bool:
        """Remove a player from the group. Returns True if player was found and removed."""
        players = self.get_players()
        original_length = len(players)
        players = [p for p in players if p.get("uuid") != uuid]

        if len(players) < original_length:
            self.set_players(players)
            return True
        return False

    def has_player(self, uuid: str) -> bool:
        """Check if a player is in the group"""
        players = self.get_players()
        return any(p.get("uuid") == uuid for p in players)


class ServerGroup(Base):
    __tablename__ = "server_groups"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    priority = Column(Integer, default=0)
    attached_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    server = relationship("Server", back_populates="server_groups")
    group = relationship("Group", back_populates="server_groups")

    __table_args__ = (UniqueConstraint("server_id", "group_id"),)
