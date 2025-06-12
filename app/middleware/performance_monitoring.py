import logging
import time
from contextvars import ContextVar
from typing import Dict, List, Optional

import psutil
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Context variables for tracking metrics per request
request_start_time: ContextVar[float] = ContextVar("request_start_time")
database_queries: ContextVar[List[Dict]] = ContextVar("database_queries", default=[])
memory_usage_start: ContextVar[float] = ContextVar("memory_usage_start")


class DatabaseQueryTracker:
    """Helper class to track database queries during request processing"""

    def __init__(self):
        self.queries: List[Dict] = []

    def track_query(self, query_type: str, duration: float, query: str = None):
        """Track a database query with timing information"""
        self.queries.append(
            {
                "type": query_type,
                "duration_ms": round(duration * 1000, 2),
                "query": query[:200] + "..." if query and len(query) > 200 else query,
                "timestamp": time.time(),
            }
        )

    def get_stats(self) -> Dict:
        """Get aggregated query statistics"""
        if not self.queries:
            return {
                "total_queries": 0,
                "total_duration_ms": 0,
                "avg_duration_ms": 0,
                "queries": [],
            }

        total_duration = sum(q["duration_ms"] for q in self.queries)
        return {
            "total_queries": len(self.queries),
            "total_duration_ms": round(total_duration, 2),
            "avg_duration_ms": round(total_duration / len(self.queries), 2),
            "queries": self.queries,
        }


class MemoryTracker:
    """Helper class to track memory usage"""

    @staticmethod
    def get_memory_usage() -> Dict:
        """Get current memory usage information"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()

            return {
                "rss_mb": round(memory_info.rss / 1024 / 1024, 2),  # Resident set size
                "vms_mb": round(memory_info.vms / 1024 / 1024, 2),  # Virtual memory size
                "percent": round(memory_percent, 2),
                "available_mb": round(psutil.virtual_memory().available / 1024 / 1024, 2),
            }
        except Exception as e:
            logger.warning(f"Failed to get memory usage: {e}")
            return {"rss_mb": 0, "vms_mb": 0, "percent": 0, "available_mb": 0}


class PerformanceMetrics:
    """Class to store and aggregate performance metrics"""

    def __init__(self):
        self.request_times: List[float] = []
        self.endpoint_stats: Dict[str, List[float]] = {}
        self.db_query_stats: List[Dict] = []
        self.memory_peaks: List[float] = []

    def add_request_metric(
        self,
        endpoint: str,
        method: str,
        duration: float,
        db_stats: Dict,
        memory_stats: Dict,
    ):
        """Add metrics for a completed request"""
        self.request_times.append(duration)

        endpoint_key = f"{method} {endpoint}"
        if endpoint_key not in self.endpoint_stats:
            self.endpoint_stats[endpoint_key] = []
        self.endpoint_stats[endpoint_key].append(duration)

        self.db_query_stats.append(db_stats)
        self.memory_peaks.append(memory_stats.get("percent", 0))

        # Keep only last 1000 entries to prevent memory bloat
        if len(self.request_times) > 1000:
            self.request_times = self.request_times[-1000:]
            self.db_query_stats = self.db_query_stats[-1000:]
            self.memory_peaks = self.memory_peaks[-1000:]

        # Keep only last 100 entries per endpoint
        for key in self.endpoint_stats:
            if len(self.endpoint_stats[key]) > 100:
                self.endpoint_stats[key] = self.endpoint_stats[key][-100:]

    def get_summary(self) -> Dict:
        """Get performance summary statistics"""
        if not self.request_times:
            return {
                "total_requests": 0,
                "avg_response_time_ms": 0,
                "p95_response_time_ms": 0,
                "p99_response_time_ms": 0,
                "avg_db_queries_per_request": 0,
                "avg_memory_usage_percent": 0,
                "slowest_endpoints": [],
                "total_db_queries": 0,
            }

        sorted_times = sorted(self.request_times)
        total_requests = len(sorted_times)

        # Calculate percentiles
        p95_index = int(total_requests * 0.95)
        p99_index = int(total_requests * 0.99)

        # Calculate endpoint averages
        endpoint_averages = []
        for endpoint, times in self.endpoint_stats.items():
            avg_time = sum(times) / len(times)
            endpoint_averages.append(
                {
                    "endpoint": endpoint,
                    "avg_time_ms": round(avg_time * 1000, 2),
                    "request_count": len(times),
                }
            )

        # Sort by slowest endpoints
        slowest_endpoints = sorted(
            endpoint_averages, key=lambda x: x["avg_time_ms"], reverse=True
        )[:10]

        # Calculate database statistics
        total_db_queries = sum(
            stats.get("total_queries", 0) for stats in self.db_query_stats
        )
        avg_db_queries = (
            total_db_queries / len(self.db_query_stats) if self.db_query_stats else 0
        )

        return {
            "total_requests": total_requests,
            "avg_response_time_ms": round(sum(sorted_times) / total_requests * 1000, 2),
            "p95_response_time_ms": (
                round(sorted_times[p95_index] * 1000, 2)
                if p95_index < total_requests
                else 0
            ),
            "p99_response_time_ms": (
                round(sorted_times[p99_index] * 1000, 2)
                if p99_index < total_requests
                else 0
            ),
            "avg_db_queries_per_request": round(avg_db_queries, 2),
            "avg_memory_usage_percent": (
                round(sum(self.memory_peaks) / len(self.memory_peaks), 2)
                if self.memory_peaks
                else 0
            ),
            "slowest_endpoints": slowest_endpoints,
            "total_db_queries": total_db_queries,
        }


# Global performance metrics instance
performance_metrics = PerformanceMetrics()


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware to monitor request performance, database queries, and memory usage"""

    def __init__(
        self,
        app,
        enabled: bool = True,
        log_slow_requests: bool = True,
        slow_request_threshold: float = 1.0,
    ):
        super().__init__(app)
        self.enabled = enabled
        self.log_slow_requests = log_slow_requests
        self.slow_request_threshold = slow_request_threshold  # seconds

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # Skip monitoring for health check and monitoring endpoints
        if request.url.path in ["/health", "/metrics", "/monitoring"]:
            return await call_next(request)

        # Initialize tracking for this request
        start_time = time.time()
        request_start_time.set(start_time)

        db_tracker = DatabaseQueryTracker()
        database_queries.set([])

        memory_start = MemoryTracker.get_memory_usage()
        memory_usage_start.set(memory_start.get("percent", 0))

        # Process the request
        try:
            response = await call_next(request)
        except Exception as e:
            # Still record metrics for failed requests
            duration = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path} - {str(e)} (took {duration:.3f}s)"
            )
            raise

        # Calculate final metrics
        end_time = time.time()
        duration = end_time - start_time

        # Get database query stats
        db_stats = db_tracker.get_stats()

        # Get memory usage at end of request
        memory_end = MemoryTracker.get_memory_usage()

        # Add metrics to global tracker
        endpoint = self._extract_endpoint_pattern(request.url.path)
        performance_metrics.add_request_metric(
            endpoint=endpoint,
            method=request.method,
            duration=duration,
            db_stats=db_stats,
            memory_stats=memory_end,
        )

        # Add performance headers to response
        response.headers["X-Response-Time"] = f"{duration * 1000:.2f}ms"
        response.headers["X-DB-Queries"] = str(db_stats.get("total_queries", 0))
        response.headers["X-Memory-Usage"] = f"{memory_end.get('percent', 0):.1f}%"

        # Log slow requests
        if self.log_slow_requests and duration > self.slow_request_threshold:
            logger.warning(
                f"Slow request detected: {request.method} {request.url.path} "
                f"took {duration:.3f}s with {db_stats.get('total_queries', 0)} DB queries "
                f"(Memory: {memory_end.get('percent', 0):.1f}%)"
            )

        # Log request for debugging (at debug level)
        logger.debug(
            f"{request.method} {request.url.path} - "
            f"{response.status_code} - {duration * 1000:.2f}ms - "
            f"{db_stats.get('total_queries', 0)} queries - "
            f"Memory: {memory_end.get('percent', 0):.1f}%"
        )

        return response

    def _extract_endpoint_pattern(self, path: str) -> str:
        """Extract endpoint pattern by replacing IDs with placeholders"""
        # Replace common ID patterns
        import re

        # Replace numeric IDs
        path = re.sub(r"/\d+", "/{id}", path)

        # Replace UUIDs
        path = re.sub(r"/[a-f0-9-]{36}", "/{uuid}", path)

        # Replace file paths (anything after /files/)
        path = re.sub(r"/files/[^/\s]+.*", "/files/{path}", path)

        return path


def get_performance_metrics() -> Dict:
    """Get current performance metrics summary"""
    return performance_metrics.get_summary()


def get_database_query_tracker() -> Optional[DatabaseQueryTracker]:
    """Get the current request's database query tracker"""
    try:
        queries = database_queries.get()
        tracker = DatabaseQueryTracker()
        tracker.queries = queries
        return tracker
    except LookupError:
        # No active request context
        return None


def track_database_query(query_type: str, duration: float, query: str = None):
    """Track a database query in the current request context"""
    try:
        tracker = get_database_query_tracker()
        if tracker:
            tracker.track_query(query_type, duration, query)
            database_queries.set(tracker.queries)
    except LookupError:
        # No active request context, skip tracking
        pass
