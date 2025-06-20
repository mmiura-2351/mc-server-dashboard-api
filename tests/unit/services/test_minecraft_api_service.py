import pytest
import asyncio
import uuid
from unittest.mock import AsyncMock, Mock, patch
import aiohttp

from app.services.minecraft_api_service import MinecraftAPIService


class TestMinecraftAPIService:
    """Comprehensive tests for MinecraftAPI Service"""

    def test_service_constants(self):
        """Test that service has correct API endpoints"""
        assert MinecraftAPIService.MOJANG_API_BASE == "https://api.mojang.com"
        assert (
            MinecraftAPIService.MOJANG_SESSION_API == "https://sessionserver.mojang.com"
        )

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_success(self):
        """Test successful UUID retrieval from username"""
        mock_response_data = {"id": "853c80ef3c3749fdaa49938b674adae6", "name": "jeb_"}

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("jeb_")

            expected_uuid = "853c80ef-3c37-49fd-aa49-938b674adae6"
            assert result == expected_uuid

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_not_found(self):
        """Test UUID retrieval when username not found (404)"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 404

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("nonexistent_user")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_api_error(self):
        """Test UUID retrieval when API returns error status"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 500

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("test_user")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_timeout(self):
        """Test UUID retrieval with timeout error"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = Mock(side_effect=asyncio.TimeoutError())
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("test_user")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_network_error(self):
        """Test UUID retrieval with network error"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = Mock(side_effect=aiohttp.ClientError("Network error"))
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("test_user")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_malformed_response(self):
        """Test UUID retrieval with malformed response (no id field)"""
        mock_response_data = {"name": "test_user"}  # Missing 'id' field

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("test_user")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_uuid_from_username_json_error(self):
        """Test UUID retrieval with JSON parsing error"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(side_effect=ValueError("JSON decode error"))

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_uuid_from_username("test_user")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_success(self):
        """Test successful username retrieval from UUID"""
        mock_response_data = {"id": "853c80ef3c3749fdaa49938b674adae6", "name": "jeb_"}

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_username_from_uuid(
                "853c80ef-3c37-49fd-aa49-938b674adae6"
            )

            assert result == "jeb_"

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_without_dashes(self):
        """Test username retrieval with UUID without dashes"""
        mock_response_data = {"id": "853c80ef3c3749fdaa49938b674adae6", "name": "jeb_"}

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            # UUID without dashes should work the same way
            result = await MinecraftAPIService.get_username_from_uuid(
                "853c80ef3c3749fdaa49938b674adae6"
            )

            assert result == "jeb_"

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_not_found(self):
        """Test username retrieval when UUID not found (404)"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 404

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_username_from_uuid(
                "00000000-0000-0000-0000-000000000000"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_api_error(self):
        """Test username retrieval when API returns error status"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 500

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_username_from_uuid(
                "853c80ef-3c37-49fd-aa49-938b674adae6"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_timeout(self):
        """Test username retrieval with timeout error"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = Mock(side_effect=asyncio.TimeoutError())
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_username_from_uuid(
                "853c80ef-3c37-49fd-aa49-938b674adae6"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_network_error(self):
        """Test username retrieval with network error"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = Mock(side_effect=aiohttp.ClientError("Network error"))
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_username_from_uuid(
                "853c80ef-3c37-49fd-aa49-938b674adae6"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_get_username_from_uuid_malformed_response(self):
        """Test username retrieval with malformed response (no name field)"""
        mock_response_data = {
            "id": "853c80ef3c3749fdaa49938b674adae6"
        }  # Missing 'name' field

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)

            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            result = await MinecraftAPIService.get_username_from_uuid(
                "853c80ef-3c37-49fd-aa49-938b674adae6"
            )

            assert result is None

    def test_generate_offline_uuid_consistency(self):
        """Test that offline UUID generation is consistent for same username"""
        username = "test_player"

        uuid1 = MinecraftAPIService.generate_offline_uuid(username)
        uuid2 = MinecraftAPIService.generate_offline_uuid(username)

        assert uuid1 == uuid2
        assert isinstance(uuid1, str)

    def test_generate_offline_uuid_different_usernames(self):
        """Test that different usernames generate different UUIDs"""
        uuid1 = MinecraftAPIService.generate_offline_uuid("player1")
        uuid2 = MinecraftAPIService.generate_offline_uuid("player2")

        assert uuid1 != uuid2

    def test_generate_offline_uuid_format(self):
        """Test that generated offline UUID has correct format"""
        test_uuid = MinecraftAPIService.generate_offline_uuid("test_player")

        # Should be a valid UUID string
        parsed_uuid = uuid.UUID(test_uuid)
        assert str(parsed_uuid) == test_uuid

        # Should contain dashes in correct positions
        assert test_uuid.count("-") == 4
        parts = test_uuid.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12

    def test_generate_offline_uuid_case_sensitivity(self):
        """Test that offline UUID generation is case sensitive"""
        uuid1 = MinecraftAPIService.generate_offline_uuid("TestPlayer")
        uuid2 = MinecraftAPIService.generate_offline_uuid("testplayer")

        assert uuid1 != uuid2

    def test_generate_offline_uuid_special_characters(self):
        """Test offline UUID generation with special characters in username"""
        usernames = ["player_1", "player-2", "player.3", "player@4"]

        uuids = []
        for username in usernames:
            test_uuid = MinecraftAPIService.generate_offline_uuid(username)
            uuids.append(test_uuid)

            # Each should be a valid UUID
            uuid.UUID(test_uuid)

        # All UUIDs should be unique
        assert len(set(uuids)) == len(uuids)

    @pytest.mark.asyncio
    async def test_api_url_construction(self):
        """Test that API URLs are constructed correctly"""
        username = "test_user"
        test_uuid = "853c80ef-3c37-49fd-aa49-938b674adae6"

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 404
            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            # Test username to UUID URL
            await MinecraftAPIService.get_uuid_from_username(username)
            expected_url = f"{MinecraftAPIService.MOJANG_API_BASE}/users/profiles/minecraft/{username}"
            mock_session.get.assert_called_with(
                expected_url, timeout=aiohttp.ClientTimeout(total=10)
            )

            # Test UUID to username URL
            await MinecraftAPIService.get_username_from_uuid(test_uuid)
            clean_uuid = test_uuid.replace("-", "")
            expected_url = f"{MinecraftAPIService.MOJANG_SESSION_API}/session/minecraft/profile/{clean_uuid}"
            mock_session.get.assert_called_with(
                expected_url, timeout=aiohttp.ClientTimeout(total=10)
            )

    @pytest.mark.asyncio
    async def test_timeout_configuration(self):
        """Test that requests use correct timeout configuration"""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 404
            # Create a proper async context manager for the get response
            mock_get_cm = Mock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = Mock(return_value=mock_get_cm)
            mock_session_class.return_value.__aenter__.return_value = mock_session

            await MinecraftAPIService.get_uuid_from_username("test")

            # Verify timeout is set to 10 seconds
            call_args = mock_session.get.call_args
            timeout_arg = call_args[1]["timeout"]
            assert timeout_arg.total == 10

    def test_uuid_formatting(self):
        """Test UUID formatting logic"""
        # Test the UUID formatting in get_uuid_from_username
        raw_uuid = "853c80ef3c3749fdaa49938b674adae6"
        expected_formatted = "853c80ef-3c37-49fd-aa49-938b674adae6"

        # Extract the formatting logic
        formatted_uuid = f"{raw_uuid[:8]}-{raw_uuid[8:12]}-{raw_uuid[12:16]}-{raw_uuid[16:20]}-{raw_uuid[20:]}"

        assert formatted_uuid == expected_formatted

    def test_uuid_dash_removal(self):
        """Test UUID dash removal logic"""
        uuid_with_dashes = "853c80ef-3c37-49fd-aa49-938b674adae6"
        expected_clean = "853c80ef3c3749fdaa49938b674adae6"

        # Extract the cleaning logic from get_username_from_uuid
        clean_uuid = uuid_with_dashes.replace("-", "")

        assert clean_uuid == expected_clean

    @pytest.mark.parametrize(
        "username,expected_uuid_type",
        [
            ("Notch", str),
            ("jeb_", str),
            ("Dinnerbone", str),
            ("_test_", str),
            ("123player", str),
        ],
    )
    def test_generate_offline_uuid_parametrized(self, username, expected_uuid_type):
        """Parametrized test for offline UUID generation with various usernames"""
        result = MinecraftAPIService.generate_offline_uuid(username)

        assert isinstance(result, expected_uuid_type)
        assert uuid.UUID(result)  # Should be parseable as UUID

        # Should be reproducible
        result2 = MinecraftAPIService.generate_offline_uuid(username)
        assert result == result2
