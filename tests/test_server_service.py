import pytest
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
from fastapi import HTTPException

from app.servers.service import ServerService, server_service
from app.servers.models import Server, ServerStatus, ServerType
from app.servers.schemas import ServerCreateRequest, ServerUpdateRequest
from app.users.models import Role


class TestServerService:
    """Test cases for ServerService"""

    def test_list_servers_for_admin(self, db, admin_user):
        """Test listing servers for admin user"""
        # Create test servers
        server1 = Server(
            name="test-server-1",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server1",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        server2 = Server(
            name="test-server-2",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=999,  # Different owner
            status=ServerStatus.running,
            directory_path="/test/server2",
            port=25566,
            max_memory=2048,
            max_players=30,
        )
        db.add_all([server1, server2])
        db.commit()

        # Test admin can see all servers
        result = server_service.list_servers(owner_id=None, page=1, size=10, db=db)

        assert result["total"] == 2
        assert len(result["servers"]) == 2
        assert result["page"] == 1
        assert result["size"] == 10

    def test_list_servers_for_regular_user(self, db, test_user, admin_user):
        """Test listing servers for regular user"""
        # Create test servers
        server1 = Server(
            name="user-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=test_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/user-server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        server2 = Server(
            name="admin-server",
            minecraft_version="1.19.4",
            server_type=ServerType.paper,
            owner_id=admin_user.id,
            status=ServerStatus.running,
            directory_path="/test/admin-server",
            port=25566,
            max_memory=2048,
            max_players=30,
        )
        db.add_all([server1, server2])
        db.commit()

        # Test regular user can only see their own servers
        result = server_service.list_servers(owner_id=test_user.id, page=1, size=10, db=db)

        assert result["total"] == 1
        assert len(result["servers"]) == 1
        assert result["servers"][0].name == "user-server"
        assert result["servers"][0].owner_id == test_user.id

    def test_list_servers_pagination(self, db, admin_user):
        """Test server listing pagination"""
        # Create multiple servers
        servers = []
        for i in range(15):
            server = Server(
                name=f"server-{i}",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
                owner_id=admin_user.id,
                status=ServerStatus.stopped,
                directory_path=f"/test/server{i}",
                port=25565 + i,
                max_memory=1024,
                max_players=20,
            )
            servers.append(server)
        db.add_all(servers)
        db.commit()

        # Test first page
        result = server_service.list_servers(owner_id=admin_user.id, page=1, size=10, db=db)
        assert result["total"] == 15
        assert len(result["servers"]) == 10
        assert result["page"] == 1

        # Test second page
        result = server_service.list_servers(owner_id=admin_user.id, page=2, size=10, db=db)
        assert result["total"] == 15
        assert len(result["servers"]) == 5
        assert result["page"] == 2

    @pytest.mark.asyncio
    async def test_get_server_success(self, db, admin_user):
        """Test getting server by ID"""
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        result = await server_service.get_server(server.id, db)
        assert result.id == server.id
        assert result.name == "test-server"

    @pytest.mark.asyncio
    async def test_get_server_not_found(self, db):
        """Test getting nonexistent server"""
        with pytest.raises(Exception):  # Should raise ServerNotFoundException
            await server_service.get_server(999, db)

    @pytest.mark.asyncio
    async def test_update_server_success(self, db, admin_user):
        """Test updating server"""
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        update_request = ServerUpdateRequest(
            name="updated-server",
            description="Updated description",
            max_memory=2048,
            max_players=30
        )

        result = await server_service.update_server(server.id, update_request, db)
        assert result.name == "updated-server"
        assert result.description == "Updated description"
        assert result.max_memory == 2048
        assert result.max_players == 30

    @pytest.mark.asyncio
    async def test_delete_server_success(self, db, admin_user):
        """Test soft deleting server"""
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        result = await server_service.delete_server(server.id, db)
        assert result is True

        # Verify server is marked as deleted
        db.refresh(server)
        assert server.is_deleted is True

    @patch('app.services.version_manager.minecraft_version_manager')
    @patch('app.servers.service.jar_cache_manager')
    @patch('app.servers.service.server_properties_generator')
    @pytest.mark.asyncio
    async def test_create_server_success(self, mock_props_gen, mock_cache, mock_version_mgr, db, admin_user, tmp_path):
        """Test successful server creation with new architecture"""
        # Mock version manager
        mock_version_mgr.is_version_supported.return_value = True
        mock_version_mgr.get_download_url = AsyncMock(return_value="http://example.com/server.jar")
        
        # Mock JAR cache
        mock_cache.get_or_download_jar = AsyncMock(return_value=tmp_path / "cached.jar")
        mock_cache.copy_jar_to_server = AsyncMock(return_value=tmp_path / "server.jar")
        
        # Mock properties generator
        mock_props_gen.generate_properties.return_value = {
            "server-port": "25565",
            "motd": "Test server"
        }

        # Create the test directory structure
        server_dir = tmp_path / "test-server"
        server_dir.mkdir(parents=True, exist_ok=True)
        
        with patch.object(server_service.filesystem_service, 'create_server_directory', return_value=server_dir):
            with patch.object(server_service.filesystem_service, 'generate_server_files') as mock_gen_files:
                mock_gen_files.return_value = None
                
                request = ServerCreateRequest(
                    name="test-server",
                    minecraft_version="1.20.1",
                    server_type=ServerType.vanilla,
                    port=25565,
                    max_memory=1024,
                    max_players=20,
                    description="Test server"
                )

                result = await server_service.create_server(request, admin_user, db)
                
                assert result.name == "test-server"
                assert result.minecraft_version == "1.20.1"
                assert result.server_type == ServerType.vanilla
                assert result.owner_id == admin_user.id

    @pytest.mark.asyncio
    async def test_create_server_unsupported_version(self, db, admin_user):
        """Test server creation with unsupported version"""
        # This should fail at the schema validation level
        with pytest.raises(Exception):  # Should raise ValidationError  
            request = ServerCreateRequest(
                name="test-server",
                minecraft_version="1.7.10",  # Unsupported version - will fail schema validation
                server_type=ServerType.vanilla,
                port=25565,
                max_memory=1024,
                max_players=20
            )

    @pytest.mark.asyncio
    async def test_create_server_duplicate_name(self, db, admin_user):
        """Test server creation with duplicate name"""
        # Create existing server
        existing_server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(existing_server)
        db.commit()

        request = ServerCreateRequest(
            name="test-server",  # Duplicate name
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25566,  # Different port
            max_memory=1024,
            max_players=20
        )

        with pytest.raises(Exception):  # Should raise ConflictException
            await server_service.create_server(request, admin_user, db)



class TestServerValidationService:
    """Test cases for ServerValidationService"""

    @pytest.mark.asyncio
    async def test_validate_server_uniqueness_success(self, db):
        """Test successful server uniqueness validation"""
        from app.servers.service import ServerValidationService
        
        validation_service = ServerValidationService()
        request = ServerCreateRequest(
            name="unique-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20
        )

        # Should not raise exception
        await validation_service.validate_server_uniqueness(request, db)

    @pytest.mark.asyncio
    async def test_validate_server_uniqueness_duplicate_name(self, db, admin_user):
        """Test server uniqueness validation with duplicate name"""
        from app.servers.service import ServerValidationService
        
        # Create existing server
        existing_server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(existing_server)
        db.commit()

        validation_service = ServerValidationService()
        request = ServerCreateRequest(
            name="test-server",  # Duplicate name
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25566,
            max_memory=1024,
            max_players=20
        )

        with pytest.raises(Exception):  # Should raise ConflictException
            await validation_service.validate_server_uniqueness(request, db)

    def test_validate_server_exists_success(self, db, admin_user):
        """Test successful server existence validation"""
        from app.servers.service import ServerValidationService
        
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        db.add(server)
        db.commit()

        validation_service = ServerValidationService()
        result = validation_service.validate_server_exists(server.id, db)
        assert result.id == server.id

    def test_validate_server_exists_not_found(self, db):
        """Test server existence validation with nonexistent server"""
        from app.servers.service import ServerValidationService
        
        validation_service = ServerValidationService()
        with pytest.raises(Exception):  # Should raise ServerNotFoundException
            validation_service.validate_server_exists(999, db)

    def test_validate_server_exists_deleted(self, db, admin_user):
        """Test server existence validation with deleted server"""
        from app.servers.service import ServerValidationService
        
        server = Server(
            name="deleted-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path="/test/server",
            port=25565,
            max_memory=1024,
            max_players=20,
            is_deleted=True,
        )
        db.add(server)
        db.commit()

        validation_service = ServerValidationService()
        with pytest.raises(Exception):  # Should raise ServerNotFoundException
            validation_service.validate_server_exists(server.id, db)


class TestServerJarService:
    """Test cases for ServerJarService"""

    @pytest.mark.asyncio
    async def test_get_server_jar_success(self, tmp_path):
        """Test successful JAR retrieval"""
        from app.servers.service import ServerJarService
        
        with patch('app.servers.service.minecraft_version_manager') as mock_version_mgr:
            with patch('app.servers.service.jar_cache_manager') as mock_cache:
                # Mock version manager
                mock_version_mgr.is_version_supported.return_value = True
                mock_version_mgr.get_download_url = AsyncMock(return_value="http://example.com/server.jar")
                
                # Mock cache manager
                cached_jar = tmp_path / "cached.jar"
                server_jar = tmp_path / "server.jar"
                mock_cache.get_or_download_jar = AsyncMock(return_value=cached_jar)
                mock_cache.copy_jar_to_server = AsyncMock(return_value=server_jar)

                jar_service = ServerJarService()
                result = await jar_service.get_server_jar(
                    ServerType.vanilla, "1.20.1", tmp_path
                )

                assert result == server_jar
                mock_version_mgr.is_version_supported.assert_called_once()
                mock_cache.get_or_download_jar.assert_called_once()
                mock_cache.copy_jar_to_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_server_jar_unsupported_version(self, tmp_path):
        """Test JAR retrieval with unsupported version"""
        from app.servers.service import ServerJarService
        
        with patch('app.servers.service.minecraft_version_manager') as mock_version_mgr:
            # Mock version manager to return False
            mock_version_mgr.is_version_supported.return_value = False

            jar_service = ServerJarService()
            with pytest.raises(Exception):  # Should raise InvalidRequestException
                await jar_service.get_server_jar(
                    ServerType.vanilla, "1.7.10", tmp_path
                )


class TestServerFileSystemService:
    """Test cases for ServerFileSystemService"""

    @pytest.mark.asyncio
    async def test_create_server_directory_success(self, tmp_path):
        """Test successful server directory creation"""
        from app.servers.service import ServerFileSystemService
        
        # Create a temporary base directory
        base_dir = tmp_path / "servers"
        
        filesystem_service = ServerFileSystemService()
        filesystem_service.base_directory = base_dir
        
        result = await filesystem_service.create_server_directory("test-server")
        
        assert result.exists()
        assert result.name == "test-server"
        assert result.parent == base_dir

    @pytest.mark.asyncio
    async def test_create_server_directory_already_exists(self, tmp_path):
        """Test server directory creation when directory already exists"""
        from app.servers.service import ServerFileSystemService
        
        # Create a temporary base directory and server directory
        base_dir = tmp_path / "servers"
        base_dir.mkdir()
        server_dir = base_dir / "test-server"
        server_dir.mkdir()
        
        filesystem_service = ServerFileSystemService()
        filesystem_service.base_directory = base_dir
        
        with pytest.raises(Exception):  # Should raise ConflictException
            await filesystem_service.create_server_directory("test-server")

    @patch('app.servers.service.server_properties_generator')
    @pytest.mark.asyncio
    async def test_generate_server_files_success(self, mock_props_gen, tmp_path, admin_user):
        """Test successful server file generation"""
        from app.servers.service import ServerFileSystemService
        
        # Mock properties generator
        mock_props_gen.generate_properties.return_value = {
            "server-port": "25565",
            "motd": "Test server",
            "max-players": "20"
        }
        
        # Create test server and request
        server = Server(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            owner_id=admin_user.id,
            status=ServerStatus.stopped,
            directory_path=str(tmp_path),
            port=25565,
            max_memory=1024,
            max_players=20,
        )
        
        request = ServerCreateRequest(
            name="test-server",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
            port=25565,
            max_memory=1024,
            max_players=20
        )

        filesystem_service = ServerFileSystemService()
        await filesystem_service.generate_server_files(server, request, tmp_path)
        
        # Check that files were created
        assert (tmp_path / "server.properties").exists()
        assert (tmp_path / "eula.txt").exists()
        assert (tmp_path / "start.sh").exists()
        
        # Check start.sh is executable
        start_sh = tmp_path / "start.sh"
        assert start_sh.stat().st_mode & 0o111  # Check execute permissions