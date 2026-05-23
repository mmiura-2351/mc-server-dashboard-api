"""Tests for ``ServerService`` creation pre-flight validation (Issue #33).

These tests exercise the new ``_validate_creation_preconditions`` path
and the public ``validate_creation_request`` API. They construct a
``ServerService`` with a fake ``ServerRepository`` so the in-DB checks
are exercised without standing up SQLAlchemy.
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, Mock

import pytest

from app.servers.application.service import ServerService
from app.servers.domain.entities import ServerEntity
from app.servers.domain.exceptions import (
    JavaCompatibilityError,
    ServerNameConflictError,
    ServerPortConflictError,
    UnsupportedMinecraftVersionError,
)
from app.servers.models import ServerStatus, ServerType
from app.servers.schemas import ServerCreateRequest
from app.users.domain.value_objects import Role
from app.users.models import User


def _entity(*, id_: int, name: str, port: int, status: ServerStatus) -> ServerEntity:
    """Build a minimal :class:`ServerEntity` for fake-repo responses.

    Uses ``Mock(spec=ServerEntity)`` to dodge the frozen-dataclass
    construction cost; only the attributes touched by the production
    code under test (``name``, ``port``, ``id``) need to be set.
    """
    e = Mock(spec=ServerEntity)
    e.id = id_
    e.name = name
    e.port = port
    e.status = status
    return e


class _FakeServerRepo:
    """Minimal in-memory ``ServerRepository`` stand-in for the tests."""

    def __init__(
        self,
        *,
        existing_name: Optional[str] = None,
        port_owner: Optional[str] = None,
        port_in_use: Optional[int] = None,
    ) -> None:
        self._existing_name = existing_name
        self._port_owner = port_owner
        self._port_in_use = port_in_use

    async def get_by_name(self, name: str, *, include_deleted: bool = False):
        if self._existing_name and name == self._existing_name:
            return _entity(id_=1, name=name, port=25565, status=ServerStatus.stopped)
        return None

    async def list_by_port(
        self,
        port,
        *,
        statuses=None,
        exclude_id=None,
        include_deleted: bool = False,
    ) -> List[ServerEntity]:
        # The pre-flight check passes ``port=<requested>`` with the
        # active-status filter; the suggestion lookup passes
        # ``port=None``.
        if port is None:
            # Suggestions: report a single "running" server on port
            # 25565 so the iterator hops past it when start_port==25566.
            if self._port_in_use is not None:
                return [
                    _entity(
                        id_=99,
                        name=self._port_owner or "running-server",
                        port=self._port_in_use,
                        status=ServerStatus.running,
                    )
                ]
            return []
        # Specific port query
        if self._port_in_use is not None and port == self._port_in_use:
            return [
                _entity(
                    id_=99,
                    name=self._port_owner or "running-server",
                    port=port,
                    status=ServerStatus.running,
                )
            ]
        return []


@pytest.fixture
def owner():
    u = Mock(spec=User)
    u.id = 1
    u.username = "tester"
    u.role = Role.admin
    return u


@pytest.fixture
def request_25565():
    return ServerCreateRequest(
        name="my-server",
        description=None,
        minecraft_version="1.21.6",
        server_type=ServerType.vanilla,
        port=25565,
        max_memory=1024,
        max_players=20,
    )


class TestNameConflict:
    @pytest.mark.asyncio
    async def test_create_server_raises_name_conflict(self, owner, request_25565):
        repo = _FakeServerRepo(existing_name="my-server")
        service = ServerService(server_repo=repo)

        with pytest.raises(ServerNameConflictError) as exc:
            await service.create_server(request_25565, owner, db=Mock())

        assert exc.value.error_code == "SERVER_NAME_CONFLICT"
        assert exc.value.name == "my-server"
        details = exc.value.extra_details()
        assert any(d.field == "name" for d in details)


class TestPortConflict:
    @pytest.mark.asyncio
    async def test_port_conflict_includes_holder_and_suggestions(
        self, owner, request_25565
    ):
        repo = _FakeServerRepo(
            port_in_use=25565,
            port_owner="running-server",
        )
        service = ServerService(server_repo=repo)
        # Make the version + java probes pass so we hit the port branch.
        service._is_version_supported_db = AsyncMock(return_value=True)
        service._validate_java_compatibility = AsyncMock()

        with pytest.raises(ServerPortConflictError) as exc:
            await service.create_server(request_25565, owner, db=Mock())

        assert exc.value.port == 25565
        assert exc.value.conflicting_server == "running-server"
        # Suggestions are computed starting at port+1; since the fake
        # only reports port 25565 as taken, the first three free ports
        # are 25566/25567/25568.
        assert exc.value.suggested_ports[:3] == [25566, 25567, 25568]


class TestUnsupportedVersion:
    @pytest.mark.asyncio
    async def test_unsupported_version_raises_structured_error(
        self, owner, request_25565
    ):
        repo = _FakeServerRepo()
        service = ServerService(server_repo=repo)
        service._is_version_supported_db = AsyncMock(return_value=False)

        with pytest.raises(UnsupportedMinecraftVersionError) as exc:
            await service.create_server(request_25565, owner, db=Mock())

        assert exc.value.version == "1.21.6"
        assert exc.value.server_type == "vanilla"


class TestJavaCompatibility:
    @pytest.mark.asyncio
    async def test_java_compatibility_failure_translated(
        self, owner, request_25565, monkeypatch
    ):
        repo = _FakeServerRepo()
        service = ServerService(server_repo=repo)
        service._is_version_supported_db = AsyncMock(return_value=True)

        # Patch the module-level java_compatibility_service so the
        # "no java found" path is exercised.
        from app.servers.application import service as svc_mod

        fake_java = Mock()
        fake_java.get_required_java_version = Mock(return_value=21)
        fake_java.get_java_for_minecraft = AsyncMock(return_value=None)
        fake_java.discover_java_installations = AsyncMock(return_value={17: object()})
        monkeypatch.setattr(svc_mod, "java_compatibility_service", fake_java)

        with pytest.raises(JavaCompatibilityError) as exc:
            await service.create_server(request_25565, owner, db=Mock())

        assert exc.value.required_java == 21
        assert exc.value.available_java == [17]


class TestValidateCreationRequest:
    @pytest.mark.asyncio
    async def test_validate_returns_warnings_on_port_conflict(self, owner, request_25565):
        repo = _FakeServerRepo(port_in_use=25565, port_owner="running-server")
        service = ServerService(server_repo=repo)
        service._is_version_supported_db = AsyncMock(return_value=True)
        service._validate_java_compatibility = AsyncMock()

        result = await service.validate_creation_request(request_25565, db=Mock())

        assert result.valid is False
        # The warnings list carries the SERVER_PORT_CONFLICT entry plus
        # the structured ``details`` rows derived from ``extra_details``.
        warning_codes = {w.code for w in result.warnings}
        assert "SERVER_PORT_CONFLICT" in warning_codes
        assert "PORT_IN_USE" in warning_codes
        # ``suggested_ports`` is populated even on the failure path so
        # the frontend can render alternatives in a single round-trip.
        assert result.suggested_ports[:3] == [25566, 25567, 25568]

    @pytest.mark.asyncio
    async def test_validate_returns_valid_when_all_checks_pass(
        self, owner, request_25565
    ):
        repo = _FakeServerRepo()
        service = ServerService(server_repo=repo)
        service._is_version_supported_db = AsyncMock(return_value=True)
        service._validate_java_compatibility = AsyncMock()

        result = await service.validate_creation_request(request_25565, db=Mock())

        assert result.valid is True
        assert result.warnings == []
        # Suggestions are still computed (allocator returns ports near
        # the requested one).
        assert request_25565.port in result.suggested_ports
