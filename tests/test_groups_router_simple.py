import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.groups.models import GroupType
from app.users.models import Role


class TestGroupsRouterConfiguration:
    """Test groups router configuration"""
    
    def test_router_tag_configuration(self):
        """Test that router is configured with correct tags"""
        from app.groups.router import router
        assert router.tags == ["groups"]

    def test_router_imports(self):
        """Test basic router imports and initialization"""
        from app.groups.router import (
            router,
            GroupService,
            GroupType,
            Role,
            User
        )
        assert router is not None
        assert GroupService is not None
        assert GroupType is not None
        assert Role is not None

    def test_group_type_enum_values(self):
        """Test that GroupType enum has expected values"""
        assert hasattr(GroupType, 'op')
        assert hasattr(GroupType, 'whitelist')
        assert GroupType.op.value == "op"
        assert GroupType.whitelist.value == "whitelist"

    def test_role_enum_values(self):
        """Test that Role enum has expected values"""
        assert hasattr(Role, 'admin')
        assert hasattr(Role, 'operator')
        assert hasattr(Role, 'user')


class TestGroupsRouterSchemas:
    """Test groups router schema imports"""
    
    def test_schema_imports(self):
        """Test that all required schemas are importable"""
        try:
            from app.groups.router import (
                AttachedServerResponse,
                GroupCreateRequest,
                GroupListResponse,
                GroupResponse,
                GroupServersResponse,
                GroupUpdateRequest,
                PlayerAddRequest,
                ServerAttachRequest,
                ServerGroupsResponse
            )
            # Basic existence check
            assert AttachedServerResponse is not None
            assert GroupCreateRequest is not None
            assert GroupListResponse is not None
            assert GroupResponse is not None
            assert GroupServersResponse is not None
            assert GroupUpdateRequest is not None
            assert PlayerAddRequest is not None
            assert ServerAttachRequest is not None
            assert ServerGroupsResponse is not None
        except ImportError as e:
            pytest.fail(f"Failed to import required schemas: {e}")


class TestGroupsRouterAPI:
    """Basic API endpoint tests for groups router"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    def test_groups_router_in_app(self, client):
        """Test that groups router is included in the app"""
        # Test that the groups endpoints exist (should return 401/422 without auth)
        response = client.get("/api/v1/groups")
        # Should return 401 (unauthorized) or 422 (validation error) not 404 (not found)
        assert response.status_code in [401, 422]

    def test_groups_endpoints_require_auth(self, client):
        """Test that groups endpoints require authentication"""
        endpoints = [
            "/api/v1/groups",
            "/api/v1/groups/1", 
            "/api/v1/groups/1/players",
            "/api/v1/groups/1/servers",
        ]
        
        for endpoint in endpoints:
            # GET requests
            response = client.get(endpoint)
            assert response.status_code in [401, 422, 405]  # Auth required or method not allowed
            
            # POST requests for create endpoints
            if endpoint == "/api/v1/groups" or "players" in endpoint:
                response = client.post(endpoint, json={})
                assert response.status_code in [401, 422]  # Auth required

    def test_groups_create_endpoint_exists(self, client):
        """Test that groups create endpoint exists"""
        # POST to /api/v1/groups should not return 404
        response = client.post("/api/v1/groups", json={})
        assert response.status_code in [401, 422]  # Auth or validation error, not 404

    def test_groups_list_endpoint_exists(self, client):
        """Test that groups list endpoint exists"""
        # GET to /api/v1/groups should not return 404
        response = client.get("/api/v1/groups")
        assert response.status_code in [401, 422]  # Auth error, not 404


class TestGroupsRouterDependencies:
    """Test groups router dependencies"""
    
    def test_auth_dependencies_import(self):
        """Test that auth dependencies are importable"""
        try:
            from app.groups.router import get_current_user, get_db
            assert get_current_user is not None
            assert get_db is not None
        except ImportError as e:
            pytest.fail(f"Failed to import auth dependencies: {e}")

    def test_group_service_import(self):
        """Test that GroupService is properly imported"""
        from app.groups.router import GroupService
        assert GroupService is not None
        # Check that it has expected methods
        assert hasattr(GroupService, '__init__')


class TestGroupsRouterHTTPStatus:
    """Test HTTP status codes used in groups router"""
    
    def test_status_codes_import(self):
        """Test that HTTP status codes are properly imported"""
        try:
            from app.groups.router import status, HTTPException
            assert status is not None
            assert HTTPException is not None
            
            # Test that common status codes are available
            assert hasattr(status, 'HTTP_200_OK')
            assert hasattr(status, 'HTTP_201_CREATED') 
            assert hasattr(status, 'HTTP_400_BAD_REQUEST')
            assert hasattr(status, 'HTTP_401_UNAUTHORIZED')
            assert hasattr(status, 'HTTP_403_FORBIDDEN')
            assert hasattr(status, 'HTTP_404_NOT_FOUND')
        except ImportError as e:
            pytest.fail(f"Failed to import HTTP status utilities: {e}")


class TestGroupsRouterBasicFunctionality:
    """Test basic router functionality"""
    
    def test_router_creation(self):
        """Test that router can be created and has expected attributes"""
        from app.groups.router import router
        assert router is not None
        assert hasattr(router, 'routes')
        assert hasattr(router, 'tags')
        assert len(router.routes) > 0  # Should have some routes defined

    def test_fastapi_dependencies(self):
        """Test that FastAPI dependencies are properly imported"""
        try:
            from app.groups.router import APIRouter, Depends, Query
            assert APIRouter is not None
            assert Depends is not None
            assert Query is not None
        except ImportError as e:
            pytest.fail(f"Failed to import FastAPI dependencies: {e}")

    def test_sqlalchemy_dependencies(self):
        """Test that SQLAlchemy dependencies are properly imported"""
        try:
            from app.groups.router import Session
            assert Session is not None
        except ImportError as e:
            pytest.fail(f"Failed to import SQLAlchemy dependencies: {e}")


class TestGroupsRouterTypeHints:
    """Test type hints and typing imports"""
    
    def test_typing_imports(self):
        """Test that typing imports work correctly"""
        try:
            from app.groups.router import Optional
            assert Optional is not None
        except ImportError as e:
            pytest.fail(f"Failed to import typing utilities: {e}")

    def test_user_model_import(self):
        """Test that User model is properly imported"""
        try:
            from app.groups.router import User
            assert User is not None
        except ImportError as e:
            pytest.fail(f"Failed to import User model: {e}")


class TestGroupsRouterEndpointStructure:
    """Test the structure of router endpoints"""
    
    def test_router_has_routes(self):
        """Test that router has defined routes"""
        from app.groups.router import router
        assert len(router.routes) > 0
        
        # Check that routes have expected attributes
        for route in router.routes:
            assert hasattr(route, 'path')
            assert hasattr(route, 'methods')

    def test_api_router_instance(self):
        """Test that router is an APIRouter instance"""
        from app.groups.router import router
        from fastapi import APIRouter
        assert isinstance(router, APIRouter)