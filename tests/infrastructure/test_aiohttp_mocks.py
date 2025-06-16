"""
Comprehensive aiohttp mock utilities for testing
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from contextlib import asynccontextmanager
import aiohttp


class MockAiohttpResponse:
    """Mock aiohttp response with proper async context manager support"""
    
    def __init__(self, status=200, headers=None, content_chunks=None, json_data=None, text_data=None):
        self.status = status
        self.headers = headers or {}
        self.content_chunks = content_chunks or []
        self.json_data = json_data
        self.text_data = text_data
        
        # Mock content attribute
        self.content = Mock()
        self.content.iter_chunked = self._iter_chunked
        
        # Mock methods
        self.raise_for_status = Mock()
        self.json = AsyncMock(return_value=json_data)
        self.text = AsyncMock(return_value=text_data)
    
    async def _iter_chunked(self, size):
        """Mock chunked content iteration"""
        for chunk in self.content_chunks:
            yield chunk
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockAiohttpSession:
    """Mock aiohttp session with proper async context manager support"""
    
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.request_history = []
    
    def get(self, url, **kwargs):
        """Mock GET request"""
        self.request_history.append(('GET', url, kwargs))
        response = self.responses.get(url, MockAiohttpResponse())
        return response
    
    def post(self, url, **kwargs):
        """Mock POST request"""
        self.request_history.append(('POST', url, kwargs))
        response = self.responses.get(url, MockAiohttpResponse())
        return response
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@asynccontextmanager
async def mock_aiohttp_session(responses=None):
    """Context manager for mocking aiohttp.ClientSession"""
    mock_session = MockAiohttpSession(responses)
    with patch('aiohttp.ClientSession', return_value=mock_session):
        yield mock_session


class TestAiohttpMocks:
    """Test cases for aiohttp mock utilities"""
    
    @pytest.mark.asyncio
    async def test_mock_response_basic(self):
        """Test basic mock response functionality"""
        response = MockAiohttpResponse(
            status=200,
            headers={'content-length': '100'},
            content_chunks=[b'chunk1', b'chunk2']
        )
        
        assert response.status == 200
        assert response.headers['content-length'] == '100'
        
        # Test async context manager
        async with response as resp:
            chunks = []
            async for chunk in resp.content.iter_chunked(8):
                chunks.append(chunk)
            assert chunks == [b'chunk1', b'chunk2']
    
    @pytest.mark.asyncio
    async def test_mock_session_basic(self):
        """Test basic mock session functionality"""
        responses = {
            'http://example.com/test': MockAiohttpResponse(
                status=200,
                json_data={'message': 'success'}
            )
        }
        
        async with mock_aiohttp_session(responses) as session:
            async with session.get('http://example.com/test') as response:
                assert response.status == 200
                data = await response.json()
                assert data == {'message': 'success'}
    
    @pytest.mark.asyncio
    async def test_mock_session_with_actual_aiohttp_import(self):
        """Test mocking when aiohttp.ClientSession is imported"""
        responses = {
            'http://test.com/file.jar': MockAiohttpResponse(
                status=200,
                headers={'content-length': '1000'},
                content_chunks=[b'jar content chunk']
            )
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MockAiohttpSession(responses)
            mock_session_class.return_value = mock_session
            
            # This simulates how the jar cache manager would use aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get('http://test.com/file.jar') as response:
                    assert response.status == 200
                    chunks = []
                    async for chunk in response.content.iter_chunked(8):
                        chunks.append(chunk)
                    assert chunks == [b'jar content chunk']