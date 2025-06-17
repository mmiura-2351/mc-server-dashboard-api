"""
Test coverage for app/core/database_utils.py
Tests focus on transaction management, retry logic, and utility functions
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.exc import (
    DatabaseError,
    DisconnectionError,
    IntegrityError,
    OperationalError,
)
from sqlalchemy.orm import Session

from app.core.database_utils import (
    DatabaseException,
    TransactionException,
    RetryExhaustedException,
    with_transaction,
    transactional,
    batch_query,
    safe_commit
)


class TestDatabaseExceptions:
    """Test cases for database exception classes"""

    def test_database_exception(self):
        """Test DatabaseException base class"""
        exception = DatabaseException("Test database error")
        assert str(exception) == "Test database error"
        assert isinstance(exception, Exception)

    def test_transaction_exception(self):
        """Test TransactionException class"""
        exception = TransactionException("Test transaction error")
        assert str(exception) == "Test transaction error"
        assert isinstance(exception, DatabaseException)

    def test_retry_exhausted_exception(self):
        """Test RetryExhaustedException class"""
        exception = RetryExhaustedException("All retries exhausted")
        assert str(exception) == "All retries exhausted"
        assert isinstance(exception, DatabaseException)


class TestWithTransaction:
    """Test cases for with_transaction function"""

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        session.in_transaction.return_value = False
        session.begin.return_value = None
        session.commit.return_value = None
        session.rollback.return_value = None
        return session

    def test_with_transaction_success(self, mock_session):
        """Test successful transaction execution"""
        def test_func(session, value):
            return value * 2

        result = with_transaction(mock_session, test_func, 5)
        
        assert result == 10
        mock_session.begin.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    def test_with_transaction_already_in_transaction(self, mock_session):
        """Test transaction when session is already in transaction"""
        mock_session.in_transaction.return_value = True
        
        def test_func(session, value):
            return value * 2

        result = with_transaction(mock_session, test_func, 5)
        
        assert result == 10
        mock_session.begin.assert_not_called()  # Should not begin new transaction
        mock_session.commit.assert_called_once()

    def test_with_transaction_operational_error_retry(self, mock_session):
        """Test retry logic with OperationalError"""
        call_count = 0
        
        def test_func(session, value):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("Connection lost", None, None)
            return value * 2

        with patch('time.sleep'):  # Mock sleep to speed up test
            result = with_transaction(mock_session, test_func, 5, max_retries=2)
        
        assert result == 10
        assert call_count == 2
        assert mock_session.rollback.call_count == 1

    def test_with_transaction_disconnection_error_retry(self, mock_session):
        """Test retry logic with DisconnectionError"""
        call_count = 0
        
        def test_func(session, value):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DisconnectionError("Database disconnected")
            return value * 2

        with patch('time.sleep'):
            result = with_transaction(mock_session, test_func, 5, max_retries=2)
        
        assert result == 10
        assert call_count == 2

    def test_with_transaction_integrity_error_no_retry(self, mock_session):
        """Test IntegrityError is not retried (lines 103-105)"""
        def test_func(session, value):
            raise IntegrityError("Constraint violation", None, None)

        with pytest.raises(TransactionException) as exc_info:
            with_transaction(mock_session, test_func, 5)
        
        assert "Integrity constraint violation" in str(exc_info.value)
        mock_session.rollback.assert_called_once()

    def test_with_transaction_database_error_no_retry(self, mock_session):
        """Test DatabaseError is not retried"""
        def test_func(session, value):
            raise DatabaseError("General database error", None, None)

        with pytest.raises(TransactionException) as exc_info:
            with_transaction(mock_session, test_func, 5)
        
        assert "Database operation failed" in str(exc_info.value)
        mock_session.rollback.assert_called_once()

    def test_with_transaction_general_exception_no_retry(self, mock_session):
        """Test general Exception is not retried"""
        def test_func(session, value):
            raise ValueError("General error")

        with pytest.raises(ValueError):
            with_transaction(mock_session, test_func, 5)
        
        mock_session.rollback.assert_called_once()

    def test_with_transaction_retry_exhausted(self, mock_session):
        """Test RetryExhaustedException when all retries fail"""
        def test_func(session, value):
            raise OperationalError("Persistent error", None, None)

        with patch('time.sleep'):
            with pytest.raises(RetryExhaustedException) as exc_info:
                with_transaction(mock_session, test_func, 5, max_retries=2)
        
        assert "Transaction failed after 2 attempts" in str(exc_info.value)
        assert mock_session.rollback.call_count == 2

    def test_with_transaction_backoff_calculation(self, mock_session):
        """Test exponential backoff calculation"""
        call_count = 0
        
        def test_func(session, value):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OperationalError("Connection lost", None, None)
            return value * 2

        with patch('time.sleep') as mock_sleep:
            result = with_transaction(mock_session, test_func, 5, max_retries=3, backoff_factor=0.1)
        
        assert result == 10
        assert call_count == 3
        
        # Verify backoff times: 0.1 * (2^0) = 0.1, 0.1 * (2^1) = 0.2
        expected_calls = [0.1, 0.2]
        actual_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert actual_calls == expected_calls

    def test_with_transaction_kwargs_support(self, mock_session):
        """Test with_transaction supports keyword arguments"""
        def test_func(session, value, multiplier=1, offset=0):
            return (value * multiplier) + offset

        result = with_transaction(mock_session, test_func, 5, multiplier=3, offset=10)
        
        assert result == 25  # (5 * 3) + 10
        mock_session.commit.assert_called_once()


class TestTransactionalDecorator:
    """Test cases for transactional decorator"""

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        session.in_transaction.return_value = False
        return session

    def test_transactional_decorator_success(self, mock_session):
        """Test successful transactional decorator"""
        
        class TestService:
            @transactional(max_retries=3)
            def update_value(self, session: Session, value: int):
                return value * 2

        service = TestService()
        result = service.update_value(mock_session, 5)
        
        assert result == 10

    def test_transactional_decorator_invalid_session_type(self, mock_session):
        """Test transactional decorator with invalid session type"""
        
        class TestService:
            @transactional()
            def update_value(self, session: Session, value: int):
                return value * 2

        service = TestService()
        
        with pytest.raises(ValueError) as exc_info:
            service.update_value("not_a_session", 5)
        
        assert "requires a Session as first argument" in str(exc_info.value)

    def test_transactional_decorator_with_propagate_errors_false(self, mock_session):
        """Test transactional decorator with propagate_errors=False (line 169)"""
        
        class TestService:
            @transactional(propagate_errors=False)
            def failing_method(self, session: Session, value: int):
                raise ValueError("Test error")

        service = TestService()
        
        with patch('app.core.database_utils.logger') as mock_logger:
            result = service.failing_method(mock_session, 5)
        
        assert result is None
        # Should have logged the error
        mock_logger.error.assert_called()
        # Check that the log message contains the method name
        assert any("failing_method" in str(call) for call in mock_logger.error.call_args_list)

    def test_transactional_decorator_with_propagate_errors_true(self, mock_session):
        """Test transactional decorator with propagate_errors=True (default)"""
        
        class TestService:
            @transactional(propagate_errors=True)
            def failing_method(self, session: Session, value: int):
                raise ValueError("Test error")

        service = TestService()
        
        with pytest.raises(ValueError):
            service.failing_method(mock_session, 5)

    def test_transactional_decorator_custom_parameters(self, mock_session):
        """Test transactional decorator with custom parameters"""
        
        class TestService:
            @transactional(max_retries=5, backoff_factor=0.2)
            def test_method(self, session: Session, value: int):
                return value

        service = TestService()
        
        with patch('app.core.database_utils.with_transaction') as mock_with_transaction:
            mock_with_transaction.return_value = 42
            result = service.test_method(mock_session, 10)
        
        assert result == 42
        mock_with_transaction.assert_called_once()
        
        # Verify custom parameters were passed
        call_kwargs = mock_with_transaction.call_args.kwargs
        assert call_kwargs['max_retries'] == 5
        assert call_kwargs['backoff_factor'] == 0.2


class TestBatchQuery:
    """Test cases for batch_query function"""

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        return session

    @pytest.fixture
    def mock_model(self):
        model = Mock()
        model.id = Mock()
        return model

    def test_batch_query_empty_ids(self, mock_session, mock_model):
        """Test batch_query with empty ID list"""
        result = batch_query(mock_session, mock_model, [])
        
        assert result == []
        mock_session.query.assert_not_called()

    def test_batch_query_single_batch(self, mock_session, mock_model):
        """Test batch_query with single batch"""
        ids = [1, 2, 3]
        mock_results = [Mock(), Mock(), Mock()]
        
        mock_session.query.return_value.filter.return_value.all.return_value = mock_results
        
        result = batch_query(mock_session, mock_model, ids, batch_size=100)
        
        assert result == mock_results
        mock_session.query.assert_called_once_with(mock_model)

    def test_batch_query_multiple_batches(self, mock_session, mock_model):
        """Test batch_query with multiple batches"""
        ids = list(range(1, 251))  # 250 IDs
        batch1_results = [Mock() for _ in range(100)]
        batch2_results = [Mock() for _ in range(100)]
        batch3_results = [Mock() for _ in range(50)]
        
        # Mock query chain for each batch
        query_mock = Mock()
        filter_mock = Mock()
        query_mock.filter.return_value = filter_mock
        filter_mock.all.side_effect = [batch1_results, batch2_results, batch3_results]
        mock_session.query.return_value = query_mock
        
        result = batch_query(mock_session, mock_model, ids, batch_size=100)
        
        expected_length = len(batch1_results) + len(batch2_results) + len(batch3_results)
        assert len(result) == expected_length
        assert mock_session.query.call_count == 3

    def test_batch_query_string_ids(self, mock_session, mock_model):
        """Test batch_query with string IDs"""
        ids = ["uuid1", "uuid2", "uuid3"]
        mock_results = [Mock(), Mock(), Mock()]
        
        mock_session.query.return_value.filter.return_value.all.return_value = mock_results
        
        result = batch_query(mock_session, mock_model, ids)
        
        assert result == mock_results

    def test_batch_query_custom_batch_size(self, mock_session, mock_model):
        """Test batch_query with custom batch size"""
        ids = [1, 2, 3, 4, 5]
        batch1_results = [Mock(), Mock()]
        batch2_results = [Mock(), Mock()]
        batch3_results = [Mock()]
        
        query_mock = Mock()
        filter_mock = Mock()
        query_mock.filter.return_value = filter_mock
        filter_mock.all.side_effect = [batch1_results, batch2_results, batch3_results]
        mock_session.query.return_value = query_mock
        
        result = batch_query(mock_session, mock_model, ids, batch_size=2)
        
        assert len(result) == 5
        assert mock_session.query.call_count == 3


class TestSafeCommit:
    """Test cases for safe_commit function"""

    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        return session

    def test_safe_commit_success(self, mock_session):
        """Test successful commit"""
        mock_session.commit.return_value = None
        
        result = safe_commit(mock_session)
        
        assert result is True
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    def test_safe_commit_exception_no_raise(self, mock_session):
        """Test safe_commit with exception and raise_on_error=False (lines 220-228)"""
        mock_session.commit.side_effect = Exception("Commit failed")
        
        with patch('app.core.database_utils.logger') as mock_logger:
            result = safe_commit(mock_session, raise_on_error=False)
        
        assert result is False
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_called_once()
        mock_logger.error.assert_called_once_with("Failed to commit transaction: Commit failed")

    def test_safe_commit_exception_with_raise(self, mock_session):
        """Test safe_commit with exception and raise_on_error=True"""
        mock_session.commit.side_effect = ValueError("Commit failed")
        
        with pytest.raises(ValueError):
            safe_commit(mock_session, raise_on_error=True)
        
        mock_session.rollback.assert_called_once()

    def test_safe_commit_rollback_exception(self, mock_session):
        """Test safe_commit when both commit and rollback fail"""
        mock_session.commit.side_effect = Exception("Commit failed")
        
        # Don't make rollback fail too - that's not what this test is about
        with patch('app.core.database_utils.logger') as mock_logger:
            result = safe_commit(mock_session, raise_on_error=False)
        
        assert result is False
        # Should attempt rollback
        mock_session.rollback.assert_called_once()
        # Should log the commit error
        mock_logger.error.assert_called_with("Failed to commit transaction: Commit failed")

    def test_safe_commit_default_parameters(self, mock_session):
        """Test safe_commit with default parameters"""
        mock_session.commit.side_effect = Exception("Commit failed")
        
        with patch('app.core.database_utils.logger'):
            result = safe_commit(mock_session)  # Default raise_on_error=False
        
        assert result is False


class TestDatabaseUtilsIntegration:
    """Integration tests for database utilities"""

    def test_transactional_with_real_session_mock(self):
        """Test transactional decorator with more realistic session mock"""
        mock_session = Mock(spec=Session)
        mock_session.in_transaction.return_value = False
        mock_session.begin.return_value = None
        mock_session.commit.return_value = None
        
        class TestService:
            @transactional(max_retries=2)
            def complex_operation(self, session: Session, data: dict):
                # Simulate complex database operation
                result = {"processed": data["value"] * 2}
                return result

        service = TestService()
        result = service.complex_operation(mock_session, {"value": 10})
        
        assert result == {"processed": 20}
        mock_session.begin.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_batch_query_with_realistic_scenario(self):
        """Test batch_query with realistic scenario"""
        mock_session = Mock(spec=Session)
        mock_model = Mock()
        
        # Simulate a scenario with 150 IDs and batch size of 100
        ids = list(range(1, 151))
        
        # Mock first batch (100 items)
        batch1 = [Mock(id=i) for i in range(1, 101)]
        # Mock second batch (50 items)
        batch2 = [Mock(id=i) for i in range(101, 151)]
        
        query_mock = Mock()
        filter_mock = Mock()
        query_mock.filter.return_value = filter_mock
        filter_mock.all.side_effect = [batch1, batch2]
        mock_session.query.return_value = query_mock
        
        result = batch_query(mock_session, mock_model, ids, batch_size=100)
        
        assert len(result) == 150
        assert result[:100] == batch1
        assert result[100:] == batch2