import logging
import time
from functools import wraps
from typing import Any, Callable

from sqlalchemy.event import listen
from sqlalchemy.orm import Session

from app.middleware.performance_monitoring import track_database_query

logger = logging.getLogger(__name__)


class DatabaseQueryMonitor:
    """Monitor database queries for performance tracking"""

    def __init__(self):
        self.query_count = 0
        self.total_time = 0.0
        self.slow_query_threshold = 0.1  # 100ms

    def setup_sqlalchemy_monitoring(self, engine):
        """Set up SQLAlchemy event listeners for query monitoring"""

        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            context._query_start_time = time.time()

        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            if hasattr(context, "_query_start_time"):
                duration = time.time() - context._query_start_time

                # Track the query
                track_database_query(
                    query_type=self._get_query_type(statement),
                    duration=duration,
                    query=statement,
                )

                # Log slow queries
                if duration > self.slow_query_threshold:
                    logger.warning(
                        f"Slow database query detected: {duration:.3f}s - "
                        f"{statement[:200]}..."
                    )

        # Register the event listeners
        listen(engine, "before_cursor_execute", before_cursor_execute)
        listen(engine, "after_cursor_execute", after_cursor_execute)

        logger.info("Database query monitoring enabled")

    def _get_query_type(self, statement: str) -> str:
        """Determine the type of SQL query"""
        statement_upper = statement.upper().strip()

        if statement_upper.startswith("SELECT"):
            return "SELECT"
        elif statement_upper.startswith("INSERT"):
            return "INSERT"
        elif statement_upper.startswith("UPDATE"):
            return "UPDATE"
        elif statement_upper.startswith("DELETE"):
            return "DELETE"
        elif statement_upper.startswith("CREATE"):
            return "CREATE"
        elif statement_upper.startswith("DROP"):
            return "DROP"
        elif statement_upper.startswith("ALTER"):
            return "ALTER"
        else:
            return "OTHER"


def monitor_database_operation(operation_name: str = None):
    """Decorator to monitor database operations"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            operation = operation_name or func.__name__

            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time

                # Track as a database operation
                track_database_query(
                    query_type=f"OPERATION:{operation}", duration=duration
                )

                return result
            except Exception as e:
                duration = time.time() - start_time

                # Track failed operation
                track_database_query(
                    query_type=f"OPERATION:{operation}:ERROR",
                    duration=duration,
                    query=str(e),
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            operation = operation_name or func.__name__

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # Track as a database operation
                track_database_query(
                    query_type=f"OPERATION:{operation}", duration=duration
                )

                return result
            except Exception as e:
                duration = time.time() - start_time

                # Track failed operation
                track_database_query(
                    query_type=f"OPERATION:{operation}:ERROR",
                    duration=duration,
                    query=str(e),
                )
                raise

        # Return appropriate wrapper based on whether function is async
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def monitor_session_operations(session: Session):
    """Add monitoring to a database session"""
    original_execute = session.execute
    original_commit = session.commit
    original_rollback = session.rollback

    def monitored_execute(
        statement,
        parameters=None,
        execution_options=None,
        bind_arguments=None,
        _parent_execute_state=None,
        _add_event=None,
    ):
        start_time = time.time()
        try:
            result = original_execute(
                statement,
                parameters,
                execution_options,
                bind_arguments,
                _parent_execute_state,
                _add_event,
            )
            duration = time.time() - start_time

            track_database_query(
                query_type="SESSION_EXECUTE", duration=duration, query=str(statement)
            )

            return result
        except Exception as e:
            duration = time.time() - start_time
            track_database_query(
                query_type="SESSION_EXECUTE_ERROR", duration=duration, query=str(e)
            )
            raise

    def monitored_commit():
        start_time = time.time()
        try:
            result = original_commit()
            duration = time.time() - start_time

            track_database_query(query_type="COMMIT", duration=duration)

            return result
        except Exception as e:
            duration = time.time() - start_time
            track_database_query(
                query_type="COMMIT_ERROR", duration=duration, query=str(e)
            )
            raise

    def monitored_rollback():
        start_time = time.time()
        try:
            result = original_rollback()
            duration = time.time() - start_time

            track_database_query(query_type="ROLLBACK", duration=duration)

            return result
        except Exception as e:
            duration = time.time() - start_time
            track_database_query(
                query_type="ROLLBACK_ERROR", duration=duration, query=str(e)
            )
            raise

    # Replace methods with monitored versions
    session.execute = monitored_execute
    session.commit = monitored_commit
    session.rollback = monitored_rollback

    return session


# Global database monitor instance
db_monitor = DatabaseQueryMonitor()
