"""Regression tests for the lifespan-scoped ``database_integration_service``.

PR #279 (#228 PR 2d follow-up) replaced the import-time singleton with a
holder-based pattern (mirrors ``backup_scheduler_instance`` from
PR #264). These tests pin the contract so a future regression — re-binding
the symbol at module import or removing the ``__getattr__`` lazy resolver —
will be caught immediately:

* ``POST /api/v1/servers/sync`` must resolve the lifespan-published
  service through the holder and respond with HTTP 200 (not 500 from
  ``RuntimeError: asyncio.run() cannot be called from a running event
  loop`` that the old shim produced).
* The ``app.services.database_integration.database_integration_service``
  shim attribute must lazily resolve to the same instance the holder
  published in lifespan startup.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import status


@pytest.fixture
def stub_database_integration_service():
    """Replace the lifespan-installed service with a stub for assertion.

    The ``client`` fixture triggers FastAPI's lifespan which installs a
    real service on the holder; tests restore it on teardown so they
    do not leak state across the session.
    """
    from app.servers.application.database_integration import (
        database_integration_instance,
    )

    previous = (
        database_integration_instance.get()
        if database_integration_instance.is_set()
        else None
    )
    stub = MagicMock()
    stub.sync_server_states = MagicMock(return_value=True)
    stub.get_all_running_servers = MagicMock(return_value=[1, 2, 3])
    database_integration_instance.set(stub)
    try:
        yield stub
    finally:
        if previous is None:
            database_integration_instance.clear()
        else:
            database_integration_instance.set(previous)


class TestSyncRouteHolderResolution:
    def test_sync_route_returns_200_via_holder(
        self,
        client,
        admin_headers,
        stub_database_integration_service,
    ):
        """B1 regression pin.

        Before PR #279, the shim bound ``database_integration_service`` at
        import time to the un-initialised singleton, so this route raised
        ``RuntimeError: asyncio.run() cannot be called from a running
        event loop`` → HTTP 500. With the holder + ``__getattr__`` lazy
        resolver, the route resolves to the lifespan-installed instance
        (or the test stub here) and returns 200.
        """
        response = client.post("/api/v1/servers/sync", headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body["message"] == "Server states synchronized"
        assert body["total_running"] == 3
        stub_database_integration_service.sync_server_states.assert_called_once()
        stub_database_integration_service.get_all_running_servers.assert_called_once()

    def test_shim_attribute_resolves_to_holder_instance(
        self, client, stub_database_integration_service
    ):
        """The legacy ``from app.servers.application.database_integration import
        database_integration_service`` access path must lazily resolve
        to the holder's current instance (the lifespan-published
        singleton in production, our stub here)."""
        # ``client`` fixture forces lifespan run + holder publication
        # before our stub replacement. Import the shim and confirm
        # ``__getattr__`` returns the stub.
        from app.servers.application import database_integration as shim

        assert shim.database_integration_service is stub_database_integration_service


class TestHolderRaisesWhenUninitialised:
    def test_shim_raises_runtimeerror_when_holder_empty(self):
        """Pre-lifespan / cleared holder → clear RuntimeError instead of
        the silent ``asyncio.run() from a running event loop`` failure
        the old shim produced."""
        from app.servers.application import database_integration as shim
        from app.servers.application.database_integration import (
            database_integration_instance,
        )

        previous = (
            database_integration_instance.get()
            if database_integration_instance.is_set()
            else None
        )
        database_integration_instance.clear()
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                _ = shim.database_integration_service
        finally:
            if previous is not None:
                database_integration_instance.set(previous)
