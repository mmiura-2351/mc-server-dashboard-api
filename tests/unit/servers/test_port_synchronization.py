"""Test port synchronization between database and server.properties"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.servers.models import Server, ServerStatus, ServerType
from app.servers.schemas import ServerUpdateRequest
from app.servers.service import server_service
from app.services.minecraft_server import minecraft_server_manager
from app.users.models import User, Role


@pytest.fixture
def test_db():
    """Create a test database"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(test_db):
    """Create a test user"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password="hashed",
        role=Role.admin,
        is_active=True,
        is_approved=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture
def test_server(test_db, test_user):
    """Create a test server with temporary directory"""
    with tempfile.TemporaryDirectory() as temp_dir:
        server = Server(
            name="Test Server",
            description="Test server for port sync",
            server_type=ServerType.vanilla,
            minecraft_version="1.20.1",
            port=25565,
            max_memory=1024,
            max_players=20,
            directory_path=temp_dir,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
        )
        test_db.add(server)
        test_db.commit()
        test_db.refresh(server)
        
        # Create server.properties file
        properties_path = Path(temp_dir) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")
        
        # Create server.jar file
        jar_path = Path(temp_dir) / "server.jar"
        jar_path.touch()
        
        yield server
        
        # Cleanup is handled by tempfile.TemporaryDirectory


class TestPortSynchronization:
    """Test cases for port synchronization between database and server.properties"""
    
    @pytest.mark.asyncio 
    async def test_manual_properties_edit_sync_on_startup(self, test_db, test_server):
        """Test that server.properties is synced from database on server startup"""
        # Simulate manual edit of server.properties (change port)
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25566\n")  # Changed from 25565 to 25566
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")
        
        # Read properties to verify manual change
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25566" in content
        
        # Call the sync method directly
        result = await minecraft_server_manager._sync_server_properties_from_database(test_server, Path(test_server.directory_path))
        assert result is True
        
        # Verify server.properties was updated with database value
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25565" in content  # Should be restored to database value
            assert "server-port=25566" not in content
    
    
    @pytest.mark.asyncio
    async def test_max_players_update_syncs_properties(self, test_db, test_server):
        """Test that max_players update syncs to server.properties"""
        # Update max_players via API
        update_request = ServerUpdateRequest(max_players=50)
        
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=test_server):
            with patch.object(server_service.database_service, 'update_server_record') as mock_update:
                with patch.object(server_service, '_sync_server_properties_after_update') as mock_sync:
                    # Set initial value different from update value  
                    test_server.max_players = 20
                    
                    def update_side_effect(server, request, db):
                        server.max_players = 50  # Simulate database update
                        return server
                    
                    mock_update.side_effect = update_side_effect
                    
                    # Call update_server
                    await server_service.update_server(test_server.id, update_request, test_db)
                    
                    # Verify sync was called
                    mock_sync.assert_called_once_with(test_server)
        
        # Also test the actual sync method directly
        test_server.max_players = 50
        await server_service._sync_server_properties_after_update(test_server)
        
        # Verify server.properties was updated
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "r") as f:
            content = f.read()
            assert "max-players=50" in content
    
    @pytest.mark.asyncio
    async def test_properties_sync_preserves_other_settings(self, test_db, test_server):
        """Test that syncing properties preserves other settings"""
        # Add custom settings to server.properties
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=Custom MOTD\n")
            f.write("difficulty=hard\n")
            f.write("spawn-protection=16\n")
        
        # Sync properties
        result = await minecraft_server_manager._sync_server_properties_from_database(test_server, Path(test_server.directory_path))
        assert result is True
        
        # Verify other settings are preserved
        with open(properties_path, "r") as f:
            content = f.read()
            assert "motd=Custom MOTD" in content
            assert "difficulty=hard" in content
            assert "spawn-protection=16" in content
            assert "server-port=25565" in content
            assert "max-players=20" in content
    
    @pytest.mark.asyncio
    async def test_port_conflict_detection_uses_database_value(self, test_db, test_server):
        """Test that port conflict detection uses database value, not properties file"""
        # Create another server with port 25566
        another_server = Server(
            name="Another Server",
            description="Another test server",
            server_type=ServerType.vanilla,
            minecraft_version="1.20.1",
            port=25566,
            max_memory=1024,
            max_players=20,
            directory_path="/tmp/another",
            owner_id=test_server.owner_id,
            status=ServerStatus.running,
        )
        test_db.add(another_server)
        test_db.commit()
        
        # Manually edit first server's properties to use port 25566
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "w") as f:
            f.write("server-port=25566\n")  # Conflicts with another_server
            f.write("max-players=20\n")
        
        # Mock the running servers check
        with patch.object(minecraft_server_manager, 'list_running_servers', return_value=[another_server.id]):
            # Validate port availability should pass because database has 25565
            is_available, message = await minecraft_server_manager._validate_port_availability(test_server, test_db)
            assert is_available is True
            assert "available" in message
        
        # Now test with actual port conflict in database
        test_server.port = 25566  # Change database value to conflict
        test_db.commit()
        
        with patch.object(minecraft_server_manager, 'list_running_servers', return_value=[another_server.id]):
            # Validate port availability should fail
            is_available, message = await minecraft_server_manager._validate_port_availability(test_server, test_db)
            assert is_available is False
            assert "already in use" in message