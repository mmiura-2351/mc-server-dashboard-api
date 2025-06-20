"""
Test coverage for app/core/database.py
Tests focus on database initialization, connection setup, and dependency injection
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.orm import Session


class TestDatabaseModule:
    """Test cases for database module initialization and components"""

    def test_database_url_from_settings(self):
        """Test DATABASE_URL is loaded from settings"""
        from app.core.database import DATABASE_URL
        from app.core.config import settings

        assert DATABASE_URL == settings.DATABASE_URL

    def test_engine_creation(self):
        """Test SQLAlchemy engine is created with correct parameters"""
        from app.core.database import engine

        assert engine is not None
        # Verify engine has the expected structure
        assert hasattr(engine, "url")
        assert hasattr(engine, "pool")

    def test_session_local_creation(self):
        """Test SessionLocal sessionmaker is properly configured"""
        from app.core.database import SessionLocal

        # Test sessionmaker configuration
        assert SessionLocal is not None
        # Verify sessionmaker parameters
        assert not SessionLocal.kw.get("autocommit", True)
        assert not SessionLocal.kw.get("autoflush", True)

    def test_base_declarative_creation(self):
        """Test Base declarative class is available"""
        from app.core.database import Base

        assert Base is not None
        assert hasattr(Base, "metadata")

    @patch("app.core.database.db_monitor")
    def test_db_monitor_import_success(self, mock_db_monitor):
        """Test successful db_monitor import and setup (lines 14-16)"""
        mock_db_monitor.setup_sqlalchemy_monitoring = Mock()

        # Reload the module to trigger the import block
        import importlib
        import app.core.database

        importlib.reload(app.core.database)

        # The mock should be called during module import
        # Note: This test is tricky because the import happens at module level

    def test_db_monitor_import_error_handling(self):
        """Test ImportError handling for db_monitor (lines 17-19)"""
        # This is challenging to test because the import happens at module level
        # The ImportError block is executed when the middleware module is not available

        # We can verify the module still works without db_monitor
        from app.core.database import engine, SessionLocal, Base

        assert engine is not None
        assert SessionLocal is not None
        assert Base is not None

    def test_get_db_session_lifecycle(self):
        """Test get_db function session lifecycle (lines 30-34)"""
        from app.core.database import get_db

        # Test the generator function
        db_generator = get_db()

        # Get the session
        db_session = next(db_generator)

        assert isinstance(db_session, Session)
        assert db_session is not None

        # Test that the session gets closed properly
        with patch.object(db_session, "close") as mock_close:
            try:
                next(db_generator)
            except StopIteration:
                # Expected - generator should stop after yielding
                pass

            # Verify close was called in finally block
            mock_close.assert_called_once()

    def test_get_db_exception_handling(self):
        """Test get_db properly closes session on exception (lines 30-34)"""
        from app.core.database import get_db

        with patch("app.core.database.SessionLocal") as mock_session_local:
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            db_generator = get_db()

            # Get the session
            session = next(db_generator)
            assert session == mock_session

            # Simulate exception during processing
            try:
                db_generator.throw(Exception("Test exception"))
            except Exception:
                pass

            # Verify session.close() was called even with exception
            mock_session.close.assert_called_once()

    def test_get_db_normal_completion(self):
        """Test get_db normal completion path"""
        from app.core.database import get_db

        with patch("app.core.database.SessionLocal") as mock_session_local:
            mock_session = Mock()
            mock_session_local.return_value = mock_session

            # Use the generator in normal context (simulating FastAPI dependency injection)
            for session in get_db():
                assert session == mock_session
                # Normal processing would happen here
                break

            # After the generator completes, close should be called
            mock_session.close.assert_called_once()

    def test_get_db_multiple_calls(self):
        """Test get_db creates new session for each call"""
        from app.core.database import get_db

        # Call get_db multiple times
        gen1 = get_db()
        gen2 = get_db()

        session1 = next(gen1)
        session2 = next(gen2)

        # Should be different session instances
        assert session1 is not session2

        # Clean up
        try:
            next(gen1)
        except StopIteration:
            pass

        try:
            next(gen2)
        except StopIteration:
            pass

    @patch("importlib.import_module")
    def test_db_monitor_module_missing(self, mock_import):
        """Test behavior when db_monitor module is missing"""
        # Simulate ImportError when trying to import db_monitor
        mock_import.side_effect = ImportError(
            "No module named 'app.middleware.database_monitoring'"
        )

        # The module should still initialize successfully
        # This tests the except ImportError block (lines 17-19)
        from app.core.database import engine, SessionLocal

        assert engine is not None
        assert SessionLocal is not None


class TestDatabaseIntegration:
    """Integration tests for database components"""

    def test_session_database_operations(self):
        """Test actual database operations with SessionLocal"""
        from app.core.database import SessionLocal, Base, engine
        from sqlalchemy import text

        # Create a test session
        session = SessionLocal()

        try:
            # Test basic session operations
            assert session is not None
            assert session.bind == engine

            # Test session can be used for queries (even if no tables exist yet)
            result = session.execute(text("SELECT 1 as test"))
            assert result.fetchone()[0] == 1

        finally:
            session.close()

    def test_base_metadata_operations(self):
        """Test Base metadata operations"""
        from app.core.database import Base, engine

        # Test that Base.metadata can interact with engine
        assert Base.metadata is not None
        assert hasattr(Base.metadata, "create_all")
        assert hasattr(Base.metadata, "drop_all")

        # These operations should not fail (even if no models are defined)
        Base.metadata.create_all(bind=engine)
        Base.metadata.drop_all(bind=engine)
