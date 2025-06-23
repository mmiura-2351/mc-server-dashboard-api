"""
Unit tests for version router endpoints
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app
from app.servers.models import ServerType
from app.users.models import Role
from app.versions.schemas import VersionUpdateResult


class TestVersionRouter:
    """Test version router endpoints"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_db_versions(self):
        """Mock database versions"""
        # Create simple mock objects instead of SQLAlchemy instances
        mock_versions = []

        # Mock vanilla version
        vanilla_version = Mock()
        vanilla_version.id = 1
        vanilla_version.server_type = "vanilla"
        vanilla_version.version = "1.21.6"
        vanilla_version.download_url = "https://example.com/vanilla-1.21.6.jar"
        vanilla_version.release_date = datetime(2024, 12, 15)
        vanilla_version.is_stable = True
        vanilla_version.build_number = None
        vanilla_version.is_active = True
        vanilla_version.last_updated = datetime.utcnow()
        vanilla_version.created_at = datetime.utcnow()
        vanilla_version.updated_at = datetime.utcnow()
        mock_versions.append(vanilla_version)

        # Mock paper version
        paper_version = Mock()
        paper_version.id = 2
        paper_version.server_type = "paper"
        paper_version.version = "1.21.6-123"
        paper_version.download_url = "https://example.com/paper-1.21.6-123.jar"
        paper_version.release_date = datetime(2024, 12, 15)
        paper_version.is_stable = True
        paper_version.build_number = 123
        paper_version.is_active = True
        paper_version.last_updated = datetime.utcnow()
        paper_version.created_at = datetime.utcnow()
        paper_version.updated_at = datetime.utcnow()
        mock_versions.append(paper_version)

        # Mock forge version
        forge_version = Mock()
        forge_version.id = 3
        forge_version.server_type = "forge"
        forge_version.version = "1.21.6-forge"
        forge_version.download_url = "https://example.com/forge-1.21.6.jar"
        forge_version.release_date = datetime(2024, 12, 15)
        forge_version.is_stable = True
        forge_version.build_number = None
        forge_version.is_active = True
        forge_version.last_updated = datetime.utcnow()
        forge_version.created_at = datetime.utcnow()
        forge_version.updated_at = datetime.utcnow()
        mock_versions.append(forge_version)

        return mock_versions

    @pytest.fixture
    def admin_user_token(self):
        """Mock admin user token"""
        return "mock-admin-token"

    # ===================
    # Public endpoints tests
    # ===================

    def test_get_supported_versions_all(self, client, mock_db_versions):
        """Test getting all supported versions"""
        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_all_active_versions = AsyncMock(return_value=mock_db_versions)

            response = client.get("/api/v1/versions/supported")

            if response.status_code != 200:
                print(f"Error response: {response.text}")
            assert response.status_code == 200
            data = response.json()

            assert len(data) == 3
            assert data[0]["version"] == "1.21.6"
            assert data[0]["server_type"] == "vanilla"
            assert data[1]["server_type"] == "paper"
            assert data[1]["build_number"] == 123

    def test_get_supported_versions_by_server_type(self, client, mock_db_versions):
        """Test getting versions filtered by server type"""
        vanilla_versions = [v for v in mock_db_versions if v.server_type == "vanilla"]

        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_versions_by_type = AsyncMock(return_value=vanilla_versions)

            response = client.get("/api/v1/versions/supported?server_type=vanilla")

            assert response.status_code == 200
            data = response.json()

            assert len(data) == 1
            assert data[0]["server_type"] == "vanilla"
            assert data[0]["version"] == "1.21.6"

    def test_get_version_stats(self, client):
        """Test getting version statistics"""
        mock_stats = {
            "_total": {"total": 130, "active": 120},
            "vanilla": {"total": 50, "active": 45},
            "paper": {"total": 60, "active": 55},
            "forge": {"total": 20, "active": 20},
        }

        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_version_stats = AsyncMock(return_value=mock_stats)

            response = client.get("/api/v1/versions/stats")

            assert response.status_code == 200
            data = response.json()

            assert data["total_versions"] == 130
            assert data["active_versions"] == 120
            assert "by_server_type" in data
            assert data["by_server_type"]["vanilla"]["total"] == 50
            assert data["by_server_type"]["paper"]["active"] == 55

    def test_get_versions_by_server_type(self, client, mock_db_versions):
        """Test getting versions for specific server type"""
        paper_versions = [v for v in mock_db_versions if v.server_type == "paper"]

        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_versions_by_type = AsyncMock(return_value=paper_versions)

            response = client.get("/api/v1/versions/paper")

            assert response.status_code == 200
            data = response.json()

            assert len(data) == 1
            assert data[0]["server_type"] == "paper"
            assert data[0]["version"] == "1.21.6-123"
            assert data[0]["build_number"] == 123

    def test_get_specific_version_found(self, client, mock_db_versions):
        """Test getting specific version details"""
        specific_version = mock_db_versions[0]  # vanilla 1.21.6

        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_version_by_type_and_version = AsyncMock(return_value=specific_version)

            response = client.get("/api/v1/versions/vanilla/1.21.6")

            assert response.status_code == 200
            data = response.json()

            assert data["version"] == "1.21.6"
            assert data["server_type"] == "vanilla"
            assert data["is_stable"] is True

    def test_get_specific_version_not_found(self, client):
        """Test getting specific version that doesn't exist"""
        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_version_by_type_and_version = AsyncMock(return_value=None)

            response = client.get("/api/v1/versions/vanilla/1.99.99")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    # ===================
    # Admin endpoints tests
    # ===================

    def test_trigger_version_update_success_admin(self, client):
        """Test manual version update trigger by admin"""
        from app.auth.dependencies import get_current_user

        mock_result = VersionUpdateResult(
            success=True,
            message="Update completed successfully",
            versions_added=5,
            versions_updated=2,
            versions_removed=1,
            execution_time_ms=2500,
            errors=[]
        )

        # Mock admin user
        def mock_admin_user():
            mock_user = Mock()
            mock_user.role = Role.admin
            return mock_user

        # Override dependency
        app.dependency_overrides[get_current_user] = mock_admin_user

        try:
            with patch('app.versions.router.version_update_scheduler') as mock_scheduler:
                # Mock scheduler
                mock_scheduler.trigger_immediate_update = AsyncMock(return_value=mock_result)

                response = client.post("/api/v1/versions/update?force_refresh=true")

                assert response.status_code == 200
                data = response.json()

                assert data["success"] is True
                assert data["versions_added"] == 5
                assert data["message"] == "Update completed successfully"

                # Verify scheduler was called correctly
                mock_scheduler.trigger_immediate_update.assert_called_once_with(force_refresh=True)
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_trigger_version_update_forbidden_non_admin(self, client):
        """Test manual version update trigger by non-admin user"""
        from app.auth.dependencies import get_current_user

        # Mock non-admin user
        def mock_user_user():
            mock_user = Mock()
            mock_user.role = Role.user
            return mock_user

        # Override dependency
        app.dependency_overrides[get_current_user] = mock_user_user

        try:
            response = client.post("/api/v1/versions/update")

            assert response.status_code == 403
            data = response.json()
            assert "administrator" in data["detail"].lower()
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_get_scheduler_status_admin(self, client):
        """Test getting scheduler status as admin"""
        from app.auth.dependencies import get_current_user

        mock_status = {
            "running": True,
            "update_interval_hours": 24,
            "last_successful_update": "2024-12-15T10:30:00",
            "next_update_time": "2024-12-16T10:30:00",
            "last_error": None,
            "retry_config": {
                "max_attempts": 3,
                "base_delay_seconds": 300
            }
        }

        # Mock admin user
        def mock_admin_user():
            mock_user = Mock()
            mock_user.role = Role.admin
            return mock_user

        # Override dependency
        app.dependency_overrides[get_current_user] = mock_admin_user

        try:
            with patch('app.versions.router.version_update_scheduler') as mock_scheduler:
                # Mock scheduler
                mock_scheduler.get_status.return_value = mock_status

                response = client.get("/api/v1/versions/scheduler/status")

                assert response.status_code == 200
                data = response.json()

                assert data["running"] is True
                assert data["update_interval_hours"] == 24
                assert "retry_config" in data
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_get_scheduler_status_forbidden_non_admin(self, client):
        """Test getting scheduler status as non-admin user"""
        from app.auth.dependencies import get_current_user

        # Mock non-admin user
        def mock_operator_user():
            mock_user = Mock()
            mock_user.role = Role.operator
            return mock_user

        # Override dependency
        app.dependency_overrides[get_current_user] = mock_operator_user

        try:
            response = client.get("/api/v1/versions/scheduler/status")

            assert response.status_code == 403
            data = response.json()
            assert "administrator" in data["detail"].lower()
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    # ===================
    # Error handling tests
    # ===================

    def test_get_supported_versions_database_error(self, client):
        """Test handling database errors in supported versions endpoint"""
        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository to raise exception
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_all_active_versions = AsyncMock(side_effect=Exception("Database connection failed"))

            response = client.get("/api/v1/versions/supported")

            assert response.status_code == 500
            data = response.json()
            assert "Failed to retrieve versions" in data["detail"]

    def test_get_version_stats_database_error(self, client):
        """Test handling database errors in stats endpoint"""
        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            # Mock repository to raise exception
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_version_stats = AsyncMock(side_effect=Exception("Database query failed"))

            response = client.get("/api/v1/versions/stats")

            assert response.status_code == 500
            data = response.json()
            assert "Failed to retrieve version statistics" in data["detail"]

    def test_trigger_version_update_scheduler_error(self, client):
        """Test handling scheduler errors in update trigger"""
        from app.auth.dependencies import get_current_user

        # Mock admin user
        def mock_admin_user():
            mock_user = Mock()
            mock_user.role = Role.admin
            return mock_user

        # Override dependency
        app.dependency_overrides[get_current_user] = mock_admin_user

        try:
            with patch('app.versions.router.version_update_scheduler') as mock_scheduler:
                # Mock scheduler to raise exception
                mock_scheduler.trigger_immediate_update = AsyncMock(side_effect=Exception("Scheduler failed"))

                response = client.post("/api/v1/versions/update")

                assert response.status_code == 500
                data = response.json()
                assert "Failed to trigger version update" in data["detail"]
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    # ===================
    # Parameter validation tests
    # ===================

    def test_get_versions_invalid_server_type(self, client):
        """Test getting versions with invalid server type"""
        response = client.get("/api/v1/versions/invalid_type")

        # Should return 422 for invalid enum value
        assert response.status_code == 422

    def test_get_supported_versions_invalid_server_type_query(self, client):
        """Test getting supported versions with invalid server type query parameter"""
        response = client.get("/api/v1/versions/supported?server_type=invalid_type")

        # Should return 422 for invalid enum value
        assert response.status_code == 422

    def test_trigger_version_update_invalid_server_types(self, client):
        """Test manual update trigger with invalid server types"""
        from app.auth.dependencies import get_current_user

        # Mock admin user
        def mock_admin_user():
            mock_user = Mock()
            mock_user.role = Role.admin
            return mock_user

        # Override dependency
        app.dependency_overrides[get_current_user] = mock_admin_user

        try:
            response = client.post("/api/v1/versions/update?server_types=invalid_type")

            # Should return 422 for invalid enum value
            assert response.status_code == 422
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()


# ===================
# Integration-style tests
# ===================

class TestVersionRouterIntegration:
    """Integration-style tests for version router"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    def test_version_endpoints_integration_flow(self, client):
        """Test complete flow of version endpoints"""
        # Mock complete version data flow
        mock_version = Mock()
        mock_version.id = 1
        mock_version.server_type = "vanilla"
        mock_version.version = "1.21.6"
        mock_version.download_url = "https://example.com/vanilla.jar"
        mock_version.release_date = datetime(2024, 12, 15)
        mock_version.is_stable = True
        mock_version.build_number = None
        mock_version.is_active = True
        mock_version.last_updated = datetime.utcnow()
        mock_version.created_at = datetime.utcnow()
        mock_version.updated_at = datetime.utcnow()

        mock_versions = [mock_version]

        mock_stats = {
            "_total": {"total": 1, "active": 1},
            "vanilla": {"total": 1, "active": 1}
        }

        with patch('app.versions.router.VersionRepository') as mock_repo_class:
            mock_repo = Mock()
            mock_repo_class.return_value = mock_repo
            mock_repo.get_all_active_versions = AsyncMock(return_value=mock_versions)
            mock_repo.get_version_stats = AsyncMock(return_value=mock_stats)
            mock_repo.get_versions_by_type = AsyncMock(return_value=mock_versions)
            mock_repo.get_version_by_type_and_version = AsyncMock(return_value=mock_versions[0])

            # Test 1: Get all supported versions
            response1 = client.get("/api/v1/versions/supported")
            assert response1.status_code == 200
            assert len(response1.json()) == 1

            # Test 2: Get version statistics
            response2 = client.get("/api/v1/versions/stats")
            assert response2.status_code == 200
            assert response2.json()["total_versions"] == 1

            # Test 3: Get versions by server type
            response3 = client.get("/api/v1/versions/vanilla")
            assert response3.status_code == 200
            assert response3.json()[0]["server_type"] == "vanilla"

            # Test 4: Get specific version
            response4 = client.get("/api/v1/versions/vanilla/1.21.6")
            assert response4.status_code == 200
            assert response4.json()["version"] == "1.21.6"
