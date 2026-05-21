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
    The session should be passed explicitly to maintain clear session lifecycle.

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
        def wrapper(self, session: Session, *args, **kwargs) -> Optional[T]:
            """
            Simplified wrapper that requires explicit session parameter.
            This eliminates complex session detection logic and potential lifecycle issues.
            """
            if not isinstance(session, Session):
                raise ValueError(
                    f"{func.__name__} requires a Session as first argument, got {type(session)}"
                )

            try:
                result = with_transaction(
                    session,
                    lambda s, *a, **k: func(self, s, *a, **k),
                    *args,
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


def migrate_file_history_unique_index(engine: Any) -> None:
    """Idempotent migration: ensure `uq_file_edit_history_server_path_version`
    is present on `file_edit_history (server_id, file_path, version_number)`.

    Behaviour:
    1. SELECT existing duplicate rows. If any are found, log a
       maintainer-actionable error listing the first 10 offenders and
       raise `RuntimeError` to abort startup before any DDL is issued
       — installing a UNIQUE index on a table with duplicates would
       fail anyway, but failing fast with a readable message saves
       operators from chasing a cryptic SQLite/MySQL error.
    2. If no duplicates exist, execute
       `CREATE UNIQUE INDEX IF NOT EXISTS` so the migration is safe
       to re-run on already-migrated databases.

    Called once during application startup, immediately after
    `Base.metadata.create_all`.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        # Pre-check: detect any existing duplicate (server_id, file_path,
        # version_number) tuples that would block the unique index.
        dup_check = conn.execute(
            text(
                "SELECT server_id, file_path, version_number, COUNT(*) AS cnt "
                "FROM file_edit_history "
                "GROUP BY server_id, file_path, version_number "
                "HAVING COUNT(*) > 1 "
                "LIMIT 10"
            )
        ).fetchall()

        if dup_check:
            # Total distinct duplicate-key groups, so the operator-facing
            # message can report "showing first 10 of N" instead of just
            # the first slice (operators were anchoring on the sample
            # length and underestimating the scope of the cleanup).
            total_dup_count = (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM ("
                        "  SELECT 1 FROM file_edit_history"
                        "   GROUP BY server_id, file_path, version_number"
                        "  HAVING COUNT(*) > 1"
                        ") AS dup_groups"
                    )
                ).scalar()
                or 0
            )

            sample = "\n".join(
                f"  server_id={row[0]}, file_path={row[1]!r}, "
                f"version_number={row[2]}, count={row[3]}"
                for row in dup_check
            )
            shown = min(len(dup_check), total_dup_count)
            error_msg = (
                f"Cannot create UNIQUE INDEX on file_edit_history: "
                f"{total_dup_count} duplicate row group(s) detected.\n"
                "Maintainer action required: manually deduplicate before "
                "next deploy.\n"
                f"Affected rows (showing first {shown} of {total_dup_count}):\n"
                f"{sample}\n\n"
                "Suggested inspection query:\n"
                "  SELECT * FROM file_edit_history\n"
                "   WHERE (server_id, file_path, version_number) IN (\n"
                "     SELECT server_id, file_path, version_number\n"
                "       FROM file_edit_history\n"
                "      GROUP BY server_id, file_path, version_number\n"
                "      HAVING COUNT(*) > 1\n"
                "   );\n"
            )
            logger.error(error_msg)
            raise RuntimeError(
                "file_edit_history contains duplicate (server_id, file_path, "
                "version_number) rows; migration aborted"
            )

        # No duplicates — safe to (re)create the unique index.
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_file_edit_history_server_path_version "
                "ON file_edit_history (server_id, file_path, version_number)"
            )
        )
        conn.commit()


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
