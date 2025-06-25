"""Tests for database utility functions and transaction management"""

import time
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.database_utils import (
    RetryExhaustedException,
    TransactionException,
    batch_query,
    transactional,
    with_transaction,
)
from app.servers.models import Server


class TestWithTransaction:
    """Test the with_transaction function"""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session"""
        session = Mock(spec=Session)
        session.in_transaction.return_value = False
        session.begin = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        return session

    def test_successful_transaction(self, mock_session):
        """Test successful transaction execution"""

        def test_func(session, value):
            return value * 2

        result = with_transaction(mock_session, test_func, 5)

        assert result == 10
        mock_session.begin.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    def test_retry_on_operational_error(self, mock_session):
        """Test retry logic on operational errors"""
        call_count = 0

        def test_func(session, value):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OperationalError("Connection lost", None, None)
            return value * 2

        with patch("time.sleep"):  # Mock sleep to speed up test
            result = with_transaction(mock_session, test_func, 5, max_retries=3)

        assert result == 10
        assert call_count == 3
        assert mock_session.rollback.call_count == 2
        assert mock_session.commit.call_count == 1

    def test_retry_exhausted(self, mock_session):
        """Test when all retries are exhausted"""

        def test_func(session, value):
            raise OperationalError("Connection lost", None, None)

        with patch("time.sleep"):  # Mock sleep to speed up test
            with pytest.raises(RetryExhaustedException) as exc_info:
                with_transaction(mock_session, test_func, 5, max_retries=3)

        assert "failed after 3 attempts" in str(exc_info.value)
        assert mock_session.rollback.call_count == 3
        assert mock_session.commit.call_count == 0

    def test_non_retryable_error(self, mock_session):
        """Test non-retryable errors are raised immediately"""

        def test_func(session, value):
            raise IntegrityError("Constraint violation", None, None, None)

        with pytest.raises(TransactionException) as exc_info:
            with_transaction(mock_session, test_func, 5)

        assert "Integrity constraint violation" in str(exc_info.value)
        assert mock_session.rollback.call_count == 1
        assert mock_session.commit.call_count == 0

    def test_exponential_backoff(self, mock_session):
        """Test exponential backoff timing"""
        call_times = []

        def test_func(session, value):
            call_times.append(time.time())
            raise OperationalError("Connection lost", None, None)

        start_time = time.time()

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(RetryExhaustedException):
                with_transaction(
                    mock_session, test_func, 5, max_retries=3, backoff_factor=0.1
                )

        # Check sleep was called with exponential backoff
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.1)  # First retry: 0.1 * 2^0
        mock_sleep.assert_any_call(0.2)  # Second retry: 0.1 * 2^1


class TestTransactionalDecorator:
    """Test the @transactional decorator"""

    class MockService:
        """Mock service class for testing"""

        def __init__(self):
            self.SessionLocal = Mock()

        @transactional(max_retries=2, propagate_errors=True)
        def update_with_session(self, session: Session, value: int) -> int:
            """Method that accepts session as first argument"""
            return value * 2

        @transactional(max_retries=2, propagate_errors=False)
        def update_no_propagate(self, session: Session, value: int) -> int:
            """Method that doesn't propagate errors"""
            if value < 0:
                raise ValueError("Negative value")
            return value * 2

    def test_decorator_with_session_arg(self):
        """Test decorator when session is provided as argument"""
        service = TestTransactionalDecorator.MockService()
        mock_session = Mock(spec=Session)
        mock_session.in_transaction.return_value = False

        with patch("app.core.database_utils.with_transaction") as mock_with_tx:
            mock_with_tx.return_value = 10

            result = service.update_with_session(mock_session, 5)

            assert result == 10
            mock_with_tx.assert_called_once()

    def test_decorator_validates_session_parameter(self):
        """Test decorator validates session parameter type"""
        service = TestTransactionalDecorator.MockService()

        # Test with non-Session object should raise ValueError
        with pytest.raises(ValueError, match="requires a Session as first argument"):
            service.update_with_session(5)

    def test_decorator_error_not_propagated(self):
        """Test decorator with propagate_errors=False"""
        service = TestTransactionalDecorator.MockService()
        mock_session = Mock(spec=Session)

        result = service.update_no_propagate(mock_session, -5)

        assert result is None  # Error not propagated, returns None


class TestBatchQuery:
    """Test the batch_query function"""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session with query capabilities"""
        session = Mock(spec=Session)
        query_mock = Mock()
        filter_mock = Mock()

        session.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = []

        return session, query_mock, filter_mock

    def test_batch_query_empty_ids(self, mock_session):
        """Test batch query with empty ID list"""
        session, _, _ = mock_session

        result = batch_query(session, Server, [])

        assert result == []
        session.query.assert_not_called()

    def test_batch_query_single_batch(self, mock_session):
        """Test batch query with IDs fitting in single batch"""
        session, query_mock, filter_mock = mock_session

        mock_servers = [Mock(id=i) for i in range(5)]
        filter_mock.all.return_value = mock_servers

        result = batch_query(session, Server, [1, 2, 3, 4, 5], batch_size=10)

        assert result == mock_servers
        session.query.assert_called_once_with(Server)
        # Check that in_ was called on the filter
        assert filter_mock.all.call_count == 1

    def test_batch_query_multiple_batches(self, mock_session):
        """Test batch query with IDs requiring multiple batches"""
        session, query_mock, filter_mock = mock_session

        # Create mock returns for each batch
        batch1 = [Mock(id=i) for i in range(1, 4)]
        batch2 = [Mock(id=i) for i in range(4, 6)]
        filter_mock.all.side_effect = [batch1, batch2]

        result = batch_query(session, Server, [1, 2, 3, 4, 5], batch_size=3)

        assert len(result) == 5
        assert result[:3] == batch1
        assert result[3:] == batch2
        assert filter_mock.all.call_count == 2
