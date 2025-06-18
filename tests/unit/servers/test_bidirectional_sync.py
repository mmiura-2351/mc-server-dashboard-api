"""Test bidirectional synchronization between database and server.properties"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from time import sleep

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.servers.models import Server, ServerStatus, ServerType
from app.servers.schemas import ServerUpdateRequest
from app.servers.service import server_service
from app.services.bidirectional_sync import bidirectional_sync_service
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
            description="Test server for bidirectional sync",
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
        
        yield server


class TestBidirectionalSync:
    """Test cases for bidirectional synchronization"""
    
    def test_file_port_extraction(self, test_server):
        """Test extracting port from server.properties file"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        port = bidirectional_sync_service.get_properties_file_port(properties_path)
        assert port == 25565
    
    def test_file_modification_time(self, test_server):
        """Test getting file modification time"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        mtime = bidirectional_sync_service.get_file_modification_time(properties_path)
        assert mtime is not None
        assert isinstance(mtime, datetime)
        assert mtime.tzinfo is not None
    
    def test_sync_from_newer_file_to_database(self, test_db, test_server):
        """Test syncing from file to database when file is newer"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        # Make file newer by waiting and then updating it
        sleep(0.1)  # Ensure time difference
        with open(properties_path, "w") as f:
            f.write("server-port=25570\n")
            f.write("max-players=20\n")
            f.write("motd=A Minecraft Server\n")
        
        # Perform bidirectional sync
        success, description = bidirectional_sync_service.perform_bidirectional_sync(
            test_server, properties_path, test_db
        )
        
        assert success is True
        assert "Synced from file to database" in description
        
        # Verify database was updated
        test_db.refresh(test_server)
        assert test_server.port == 25570
    
    def test_sync_from_newer_database_to_file(self, test_db, test_server):
        """Test syncing from database to file when database is newer"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        # Get current file modification time
        import time
        file_mtime = time.time()
        
        # Wait to ensure database timestamp is newer
        sleep(0.1)
        
        # Update database port with explicit timestamp update
        test_server.port = 25580
        test_server.updated_at = datetime.now(timezone.utc)
        test_db.commit()
        test_db.refresh(test_server)
        
        # Set file modification time to be older than database
        import os
        os.utime(properties_path, (file_mtime, file_mtime))
        
        # Database is now newer than file
        success, description = bidirectional_sync_service.perform_bidirectional_sync(
            test_server, properties_path, test_db
        )
        
        assert success is True
        assert "Synced from database to file" in description
        
        # Verify file was updated
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25580" in content
    
    def test_no_sync_when_ports_match(self, test_db, test_server):
        """Test no sync when ports are already in sync"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        success, description = bidirectional_sync_service.perform_bidirectional_sync(
            test_server, properties_path, test_db
        )
        
        assert success is True
        assert "already in sync" in description
    
    @pytest.mark.asyncio
    async def test_api_port_update_direct(self, test_db, test_server):
        """Test API port update via direct port field"""
        update_request = ServerUpdateRequest(port=25590)
        
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=test_server):
            with patch.object(server_service.database_service, 'update_server_record') as mock_update:
                # Set initial value different from update value  
                test_server.port = 25565
                
                def update_side_effect(server, request, db):
                    server.port = 25590  # Simulate database update
                    return server
                
                mock_update.side_effect = update_side_effect
                
                # Call update_server
                await server_service.update_server(test_server.id, update_request, test_db)
        
        # Verify server.properties was updated
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25590" in content
    
    @pytest.mark.asyncio
    async def test_api_port_update_via_server_properties(self, test_db, test_server):
        """Test API port update via server_properties field"""
        update_request = ServerUpdateRequest(
            server_properties={"server-port": "25600", "motd": "Updated MOTD"}
        )
        
        with patch.object(server_service.validation_service, 'validate_server_exists', return_value=test_server):
            with patch.object(server_service.database_service, 'update_server_record') as mock_update:
                # Simulate database update - the service should set port from server_properties
                def update_side_effect(server, request, db):
                    server.port = request.port  # Should be set to 25600
                    return server
                
                mock_update.side_effect = update_side_effect
                
                # Call update_server
                result = await server_service.update_server(test_server.id, update_request, test_db)
        
        # Verify request.port was set from server_properties
        assert update_request.port == 25600
        
        # Also test direct sync method
        test_server.port = 25600
        await server_service._sync_server_properties_after_update(
            test_server, {"motd": "Updated MOTD"}
        )
        
        # Verify server.properties was updated
        properties_path = Path(test_server.directory_path) / "server.properties"
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25600" in content
            assert "motd=Updated MOTD" in content
    
    def test_invalid_port_in_server_properties(self, test_db, test_server):
        """Test handling of invalid port in server_properties"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        # Write invalid port
        with open(properties_path, "w") as f:
            f.write("server-port=invalid\n")
            f.write("max-players=20\n")
        
        port = bidirectional_sync_service.get_properties_file_port(properties_path)
        assert port is None
    
    def test_missing_properties_file(self, test_db, test_server):
        """Test handling when server.properties file doesn't exist"""
        properties_path = Path(test_server.directory_path) / "nonexistent.properties"
        
        should_sync, file_port, reason = bidirectional_sync_service.should_sync_from_file(
            test_server, properties_path
        )
        
        assert should_sync is False
        assert file_port is None
        assert "No port found" in reason
    
    def test_sync_preserves_other_properties(self, test_db, test_server):
        """Test that sync preserves other properties in the file"""
        properties_path = Path(test_server.directory_path) / "server.properties"
        
        # Add custom properties
        with open(properties_path, "w") as f:
            f.write("server-port=25565\n")
            f.write("max-players=20\n")
            f.write("motd=Custom Server\n")
            f.write("difficulty=hard\n")
            f.write("spawn-protection=16\n")
        
        # Update database port
        test_server.port = 25610
        test_db.commit()
        
        # Sync from database to file
        success = bidirectional_sync_service.sync_port_from_database_to_file(
            test_server, properties_path
        )
        
        assert success is True
        
        # Verify custom properties are preserved
        with open(properties_path, "r") as f:
            content = f.read()
            assert "server-port=25610" in content
            assert "motd=Custom Server" in content
            assert "difficulty=hard" in content
            assert "spawn-protection=16" in content