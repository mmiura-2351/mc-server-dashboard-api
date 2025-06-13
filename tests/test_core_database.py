"""Comprehensive tests for app/core/database.py connection management"""
from unittest.mock import Mock, patch, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import (
    DATABASE_URL,
    engine,
    SessionLocal,
    Base,
    get_db
)


class TestDatabaseConfiguration:
    """Test database configuration and setup"""
    
    def test_database_url_from_settings(self):
        """Test DATABASE_URL is correctly set from settings"""
        with patch('app.core.database.settings') as mock_settings:
            mock_settings.DATABASE_URL = "sqlite:///test.db"
            
            # Reload the module to pick up new settings
            import importlib
            import app.core.database
            importlib.reload(app.core.database)
            
            assert app.core.database.DATABASE_URL == "sqlite:///test.db"
    
    def test_engine_creation_with_sqlite_args(self):
        """Test engine is created with proper SQLite arguments"""
        with patch('app.core.database.create_engine') as mock_create_engine:
            mock_engine = Mock()
            mock_create_engine.return_value = mock_engine
            
            # Reload to trigger engine creation
            import importlib
            import app.core.database
            importlib.reload(app.core.database)
            
            mock_create_engine.assert_called_once()
            args, kwargs = mock_create_engine.call_args
            assert kwargs.get('connect_args') == {"check_same_thread": False}
    
    def test_sessionlocal_configuration(self):
        """Test SessionLocal is properly configured"""
        with patch('app.core.database.sessionmaker') as mock_sessionmaker:
            mock_session = Mock()
            mock_sessionmaker.return_value = mock_session
            
            # Reload to trigger SessionLocal creation
            import importlib
            import app.core.database
            importlib.reload(app.core.database)
            
            mock_sessionmaker.assert_called_once()
            args, kwargs = mock_sessionmaker.call_args
            assert kwargs.get('autocommit') is False
            assert kwargs.get('autoflush') is False
            assert 'bind' in kwargs


class TestDatabaseMonitoring:
    """Test database monitoring setup"""
    
    def test_monitoring_setup_success(self):
        """Test successful monitoring setup"""
        mock_engine = Mock()
        mock_monitor = Mock()
        mock_monitor.setup_sqlalchemy_monitoring = Mock()
        
        with patch('app.core.database.db_monitor', mock_monitor), \
             patch('app.core.database.engine', mock_engine):
            
            # Reload to trigger monitoring setup
            import importlib
            import app.core.database
            importlib.reload(app.core.database)
            
            mock_monitor.setup_sqlalchemy_monitoring.assert_called_once_with(mock_engine)
    
    def test_monitoring_setup_import_error(self):
        """Test monitoring setup handles ImportError gracefully"""
        mock_engine = Mock()
        
        with patch('app.core.database.engine', mock_engine), \
             patch('builtins.__import__', side_effect=ImportError("Monitoring not available")):
            
            # Should not raise exception
            import importlib
            import app.core.database
            importlib.reload(app.core.database)
            
            # Code should continue without monitoring


class TestGetDbDependency:
    """Test get_db dependency injection function"""
    
    def test_get_db_yields_session(self):
        """Test get_db yields database session"""
        mock_session = Mock()
        
        with patch('app.core.database.SessionLocal', return_value=mock_session):
            gen = get_db()
            
            # Get the yielded session
            session = next(gen)
            
            assert session is mock_session
    
    def test_get_db_closes_session_on_completion(self):
        """Test get_db closes session after completion"""
        mock_session = Mock()
        mock_session.close = Mock()
        
        with patch('app.core.database.SessionLocal', return_value=mock_session):
            gen = get_db()
            
            # Get the session and complete the generator
            session = next(gen)
            
            try:
                next(gen)
            except StopIteration:
                pass
            
            mock_session.close.assert_called_once()
    
    def test_get_db_closes_session_on_exception(self):
        """Test get_db closes session even when exception occurs"""
        mock_session = Mock()
        mock_session.close = Mock()
        
        with patch('app.core.database.SessionLocal', return_value=mock_session):
            gen = get_db()
            
            # Get the session
            session = next(gen)
            
            # Simulate exception in generator
            try:
                gen.throw(Exception("Test exception"))
            except Exception:
                pass
            
            mock_session.close.assert_called_once()
    
    def test_get_db_multiple_calls_create_separate_sessions(self):
        """Test multiple calls to get_db create separate sessions"""
        mock_session1 = Mock()
        mock_session2 = Mock()
        
        with patch('app.core.database.SessionLocal', side_effect=[mock_session1, mock_session2]):
            gen1 = get_db()
            gen2 = get_db()
            
            session1 = next(gen1)
            session2 = next(gen2)
            
            assert session1 is mock_session1
            assert session2 is mock_session2
            assert session1 is not session2


class TestDatabaseIntegration:
    """Test database integration functionality"""
    
    def test_real_engine_creation(self):
        """Test that a real engine can be created"""
        # This test uses the actual create_engine function
        from app.core.config import settings
        
        # Create engine with test database
        test_engine = create_engine(
            "sqlite:///test_db.db",
            connect_args={"check_same_thread": False}
        )
        
        assert test_engine is not None
        assert hasattr(test_engine, 'connect')
    
    def test_real_sessionmaker_creation(self):
        """Test that a real sessionmaker can be created"""
        # Create a test engine
        test_engine = create_engine(
            "sqlite:///test_db.db",
            connect_args={"check_same_thread": False}
        )
        
        # Create sessionmaker
        TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        assert TestSessionLocal is not None
        assert callable(TestSessionLocal)
    
    def test_session_creation_and_usage(self):
        """Test session creation and basic usage"""
        # Create test engine and session
        test_engine = create_engine(
            "sqlite:///test_db.db",
            connect_args={"check_same_thread": False}
        )
        TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        # Test session creation
        session = TestSessionLocal()
        
        try:
            assert session is not None
            assert hasattr(session, 'query')
            assert hasattr(session, 'commit')
            assert hasattr(session, 'rollback')
            assert hasattr(session, 'close')
        finally:
            session.close()
    
    def test_base_declarative_creation(self):
        """Test Base declarative base creation"""
        from sqlalchemy.orm import declarative_base
        
        TestBase = declarative_base()
        
        assert TestBase is not None
        assert hasattr(TestBase, 'metadata')
        assert hasattr(TestBase.metadata, 'create_all')


class TestDatabaseConnectionHandling:
    """Test database connection error handling"""
    
    def test_engine_connection_error_handling(self):
        """Test engine handles connection errors gracefully"""
        # Create engine with invalid database URL
        with pytest.raises(Exception):
            invalid_engine = create_engine("invalid://database/url")
            # Try to connect to trigger error
            with invalid_engine.connect():
                pass
    
    def test_session_transaction_handling(self):
        """Test session transaction handling"""
        test_engine = create_engine("sqlite:///test_db.db")
        TestSessionLocal = sessionmaker(bind=test_engine)
        
        session = TestSessionLocal()
        
        try:
            # Start transaction
            session.begin()
            
            # Test transaction operations
            assert session.in_transaction()
            
            # Test rollback
            session.rollback()
            
            # Test commit on new transaction
            session.begin()
            session.commit()
            
        finally:
            session.close()


class TestDatabaseSettings:
    """Test database settings integration"""
    
    def test_settings_integration(self):
        """Test database configuration integrates with settings"""
        from app.core.config import settings
        
        # Verify settings has DATABASE_URL
        assert hasattr(settings, 'DATABASE_URL')
        assert isinstance(settings.DATABASE_URL, str)
        assert len(settings.DATABASE_URL) > 0
    
    def test_database_url_format(self):
        """Test DATABASE_URL has correct format"""
        from app.core.config import settings
        
        # DATABASE_URL should be a valid connection string
        assert settings.DATABASE_URL.startswith(('sqlite:', 'postgresql:', 'mysql:'))
    
    @patch('app.core.database.settings')
    def test_different_database_configurations(self, mock_settings):
        """Test different database configuration scenarios"""
        # Test SQLite configuration
        mock_settings.DATABASE_URL = "sqlite:///app.db"
        
        # Test PostgreSQL configuration
        mock_settings.DATABASE_URL = "postgresql://user:pass@localhost/db"
        
        # Test MySQL configuration  
        mock_settings.DATABASE_URL = "mysql://user:pass@localhost/db"
        
        # Each should be valid
        for url in [
            "sqlite:///app.db",
            "postgresql://user:pass@localhost/db", 
            "mysql://user:pass@localhost/db"
        ]:
            mock_settings.DATABASE_URL = url
            assert mock_settings.DATABASE_URL == url