"""Database utility functions for transaction management and retry logic"""

import logging
import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union

from sqlalchemy.exc import (
    DatabaseError,
    DisconnectionError,
    IntegrityError,
    OperationalError,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DatabaseException(Exception):
    """Base exception for database operations"""

    pass


class TransactionException(DatabaseException):
    """Exception raised when a transaction fails"""

    pass


class RetryExhaustedException(DatabaseException):
    """Exception raised when all retry attempts are exhausted"""

    pass


def with_transaction(
    session: Session,
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    backoff_factor: float = 0.1,
    **kwargs,
) -> T:
    """
    Execute a function within a database transaction with retry logic.

    Args:
        session: SQLAlchemy session
        func: Function to execute within transaction
        *args: Arguments to pass to the function
        max_retries: Maximum number of retry attempts (default: 3)
        backoff_factor: Exponential backoff factor in seconds (default: 0.1)
        **kwargs: Keyword arguments to pass to the function

    Returns:
        The result of the function execution

    Raises:
        RetryExhaustedException: When all retry attempts are exhausted
        TransactionException: When a non-retryable error occurs
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            # Begin explicit transaction
            if not session.in_transaction():
                session.begin()

            # Execute the function
            result = func(session, *args, **kwargs)

            # Commit the transaction
            session.commit()

            return result

        except (OperationalError, DisconnectionError) as e:
            # These are retryable errors (connection issues, deadlocks, etc.)
            session.rollback()
            last_exception = e

            if attempt < max_retries - 1:
                wait_time = backoff_factor * (2**attempt)
                logger.warning(
                    f"Retryable database error on attempt {attempt + 1}/{max_retries}: {e}. "
                    f"Retrying in {wait_time:.2f}s..."
                )
                time.sleep(wait_time)
                continue

        except IntegrityError as e:
            # Integrity errors are not retryable
            session.rollback()
            logger.error(f"Database integrity error: {e}")
            raise TransactionException(f"Integrity constraint violation: {e}") from e

        except DatabaseError as e:
            # Other database errors
            session.rollback()
            logger.error(f"Database error: {e}")
            raise TransactionException(f"Database operation failed: {e}") from e

        except Exception as e:
            # Any other exception
            session.rollback()
            logger.error(f"Unexpected error during transaction: {e}")
            raise

    # All retries exhausted
    logger.error(
        f"Transaction failed after {max_retries} attempts. Last error: {last_exception}"
    )
    raise RetryExhaustedException(
        f"Transaction failed after {max_retries} attempts"
    ) from last_exception


def transactional(
    max_retries: int = 3,
    backoff_factor: float = 0.1,
    propagate_errors: bool = True,
):
    """
    Decorator for methods that require transaction management with retry logic.

    The decorated method must accept a Session as its first argument after self.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Exponential backoff factor in seconds
        propagate_errors: Whether to propagate errors to caller

    Example:
        @transactional(max_retries=3)
        def update_status(self, session: Session, server_id: int, status: str):
            server = session.query(Server).filter_by(id=server_id).first()
            server.status = status
    """

    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> Optional[T]:
            # Extract session from arguments
            session = None
            func_args = list(args)

            # Check if first argument is a Session
            if args and isinstance(args[0], Session):
                session = args[0]
                func_args = func_args[1:]
            elif "session" in kwargs:
                session = kwargs.pop("session")
            else:
                # Try to get session from self.SessionLocal if available
                if hasattr(self, "SessionLocal"):
                    session = self.SessionLocal()
                    try:
                        result = with_transaction(
                            session,
                            lambda s, *a, **k: func(self, s, *a, **k),
                            *func_args,
                            max_retries=max_retries,
                            backoff_factor=backoff_factor,
                            **kwargs,
                        )
                        return result
                    except Exception as e:
                        if propagate_errors:
                            raise
                        logger.error(f"Transaction failed in {func.__name__}: {e}")
                        return None
                    finally:
                        session.close()
                else:
                    raise ValueError(
                        f"{func.__name__} requires a database session but none was provided"
                    )

            # Session was provided, use it
            try:
                result = with_transaction(
                    session,
                    lambda s, *a, **k: func(self, s, *a, **k),
                    *func_args,
                    max_retries=max_retries,
                    backoff_factor=backoff_factor,
                    **kwargs,
                )
                return result
            except Exception as e:
                if propagate_errors:
                    raise
                logger.error(f"Transaction failed in {func.__name__}: {e}")
                return None

        return wrapper

    return decorator


def batch_query(
    session: Session,
    model: Any,
    ids: list[Union[int, str]],
    batch_size: int = 100,
) -> list[Any]:
    """
    Query multiple records in batches to avoid N+1 queries.

    Args:
        session: SQLAlchemy session
        model: SQLAlchemy model class
        ids: List of IDs to query
        batch_size: Number of records to query per batch

    Returns:
        List of model instances
    """
    if not ids:
        return []

    results = []

    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_results = session.query(model).filter(model.id.in_(batch_ids)).all()
        results.extend(batch_results)

    return results


def safe_commit(session: Session, raise_on_error: bool = False) -> bool:
    """
    Safely commit a session with proper error handling.

    Args:
        session: SQLAlchemy session to commit
        raise_on_error: Whether to raise exception on error

    Returns:
        True if commit succeeded, False otherwise
    """
    try:
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to commit transaction: {e}")
        if raise_on_error:
            raise
        return False
