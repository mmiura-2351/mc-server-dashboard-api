import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.performance_monitoring import (
    DatabaseQueryTracker,
    MemoryTracker,
    PerformanceMetrics,
    PerformanceMonitoringMiddleware,
    get_performance_metrics,
    track_database_query,
)


class TestDatabaseQueryTracker:
    def test_track_query(self):
        """Test tracking database queries"""
        tracker = DatabaseQueryTracker()

        # Track some queries
        tracker.track_query("SELECT", 0.05, "SELECT * FROM users")
        tracker.track_query("INSERT", 0.02, "INSERT INTO users VALUES (...)")
        tracker.track_query("UPDATE", 0.03, "UPDATE users SET ...")

        stats = tracker.get_stats()

        assert stats["total_queries"] == 3
        assert stats["total_duration_ms"] == 100.0  # 50 + 20 + 30 ms
        assert stats["avg_duration_ms"] == 33.33
        assert len(stats["queries"]) == 3

        # Check query details
        assert stats["queries"][0]["type"] == "SELECT"
        assert stats["queries"][0]["duration_ms"] == 50.0

    def test_empty_tracker(self):
        """Test tracker with no queries"""
        tracker = DatabaseQueryTracker()
        stats = tracker.get_stats()

        assert stats["total_queries"] == 0
        assert stats["total_duration_ms"] == 0
        assert stats["avg_duration_ms"] == 0
        assert stats["queries"] == []

    def test_long_query_truncation(self):
        """Test that long queries are truncated"""
        tracker = DatabaseQueryTracker()
        long_query = "SELECT * FROM table WHERE " + "x" * 300

        tracker.track_query("SELECT", 0.01, long_query)
        stats = tracker.get_stats()

        query_text = stats["queries"][0]["query"]
        assert len(query_text) <= 203  # 200 chars + "..."
        assert query_text.endswith("...")


class TestMemoryTracker:
    def test_get_memory_usage(self):
        """Test memory usage tracking"""
        memory_info = MemoryTracker.get_memory_usage()

        # Should have all required fields
        assert "rss_mb" in memory_info
        assert "vms_mb" in memory_info
        assert "percent" in memory_info
        assert "available_mb" in memory_info

        # Values should be reasonable
        assert memory_info["rss_mb"] >= 0
        assert memory_info["vms_mb"] >= 0
        assert 0 <= memory_info["percent"] <= 100
        assert memory_info["available_mb"] >= 0


class TestPerformanceMetrics:
    def test_add_request_metric(self):
        """Test adding request metrics"""
        metrics = PerformanceMetrics()

        db_stats = {"total_queries": 3, "total_duration_ms": 50.0}
        memory_stats = {"percent": 25.5}

        metrics.add_request_metric(
            endpoint="/api/v1/users",
            method="GET",
            duration=0.15,
            db_stats=db_stats,
            memory_stats=memory_stats,
        )

        summary = metrics.get_summary()

        assert summary["total_requests"] == 1
        assert summary["avg_response_time_ms"] == 150.0
        assert summary["avg_db_queries_per_request"] == 3.0
        assert summary["avg_memory_usage_percent"] == 25.5
        assert summary["total_db_queries"] == 3

    def test_multiple_requests(self):
        """Test metrics with multiple requests"""
        metrics = PerformanceMetrics()

        # Add several requests
        for i in range(5):
            db_stats = {"total_queries": i + 1, "total_duration_ms": (i + 1) * 10}
            memory_stats = {"percent": 20 + i}

            metrics.add_request_metric(
                endpoint=f"/api/v1/endpoint{i}",
                method="GET",
                duration=0.1 + i * 0.05,  # Increasing duration
                db_stats=db_stats,
                memory_stats=memory_stats,
            )

        summary = metrics.get_summary()

        assert summary["total_requests"] == 5
        assert summary["total_db_queries"] == 15  # 1+2+3+4+5
        assert len(summary["slowest_endpoints"]) <= 5

        # Check that slowest endpoints are sorted correctly
        slowest = summary["slowest_endpoints"]
        if len(slowest) > 1:
            assert slowest[0]["avg_time_ms"] >= slowest[1]["avg_time_ms"]

    def test_percentile_calculation(self):
        """Test response time percentile calculations"""
        metrics = PerformanceMetrics()

        # Add 100 requests with known durations
        for i in range(100):
            db_stats = {"total_queries": 1}
            memory_stats = {"percent": 20}

            metrics.add_request_metric(
                endpoint="/test",
                method="GET",
                duration=i * 0.01,  # 0, 0.01, 0.02, ..., 0.99 seconds
                db_stats=db_stats,
                memory_stats=memory_stats,
            )

        summary = metrics.get_summary()

        # P95 should be around 95% of max (0.94 seconds = 940ms)
        assert 930 <= summary["p95_response_time_ms"] <= 950

        # P99 should be around 99% of max (0.98 seconds = 980ms)
        assert 970 <= summary["p99_response_time_ms"] <= 990

    def test_memory_limit(self):
        """Test that metrics don't grow indefinitely"""
        metrics = PerformanceMetrics()

        # Add more than the limit (1000 requests)
        for i in range(1200):
            db_stats = {"total_queries": 1}
            memory_stats = {"percent": 20}

            metrics.add_request_metric(
                endpoint="/test",
                method="GET",
                duration=0.1,
                db_stats=db_stats,
                memory_stats=memory_stats,
            )

        # Should be limited to 1000
        assert len(metrics.request_times) == 1000
        assert len(metrics.db_query_stats) == 1000
        assert len(metrics.memory_peaks) == 1000


class TestPerformanceMonitoringMiddleware:
    @pytest.fixture
    def test_app(self):
        """Create a test FastAPI app with monitoring middleware"""
        app = FastAPI()

        app.add_middleware(
            PerformanceMonitoringMiddleware,
            enabled=True,
            log_slow_requests=True,
            slow_request_threshold=0.1,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        @app.get("/slow")
        async def slow_endpoint():
            await asyncio.sleep(0.2)  # Simulate slow endpoint
            return {"message": "slow"}

        return app

    def test_middleware_adds_headers(self, test_app):
        """Test that middleware adds performance headers"""
        client = TestClient(test_app)

        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Response-Time" in response.headers
        assert "X-DB-Queries" in response.headers
        assert "X-Memory-Usage" in response.headers

        # Headers should have reasonable values
        response_time = response.headers["X-Response-Time"]
        assert response_time.endswith("ms")
        assert float(response_time[:-2]) > 0

    def test_middleware_tracks_metrics(self, test_app):
        """Test that middleware tracks performance metrics"""
        client = TestClient(test_app)

        # Clear any existing metrics by creating new instance
        import app.middleware.performance_monitoring
        from app.middleware.performance_monitoring import PerformanceMetrics

        # Store original metrics to restore later
        original_metrics = app.middleware.performance_monitoring.performance_metrics

        # Replace with fresh instance for this test
        test_metrics = PerformanceMetrics()
        app.middleware.performance_monitoring.performance_metrics = test_metrics

        try:
            # Make some requests
            client.get("/test")
            client.get("/test")

            metrics = get_performance_metrics()

            assert metrics["total_requests"] == 2
            assert metrics["avg_response_time_ms"] > 0
            assert len(metrics["slowest_endpoints"]) > 0
        finally:
            # Restore original metrics
            app.middleware.performance_monitoring.performance_metrics = original_metrics

    def test_disabled_middleware(self):
        """Test middleware when disabled"""
        app = FastAPI()

        app.add_middleware(PerformanceMonitoringMiddleware, enabled=False)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        # Headers should not be added when middleware is disabled
        assert "X-Response-Time" not in response.headers
        assert "X-DB-Queries" not in response.headers
        assert "X-Memory-Usage" not in response.headers


class TestDatabaseQueryTracking:
    def test_track_database_query_function(self):
        """Test the track_database_query function"""
        # This test will run outside of request context, so it should handle gracefully

        # Should not raise an exception even without request context
        track_database_query("SELECT", 0.05, "SELECT * FROM test")

        # The function should handle missing context gracefully
        assert True  # If we get here, no exception was raised


def test_get_performance_metrics():
    """Test the global get_performance_metrics function"""
    metrics = get_performance_metrics()

    # Should return a valid metrics dictionary
    assert isinstance(metrics, dict)
    assert "total_requests" in metrics
    assert "avg_response_time_ms" in metrics
    assert "slowest_endpoints" in metrics
