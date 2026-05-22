"""Integration tests for `app.templates.router`.

Drives the FastAPI app via `TestClient` and overrides
`get_template_service` (and `get_authorization_service` for the
``/from-server/{id}`` endpoint) with hand-rolled fakes. Each fake
method either returns a pre-canned value or raises a configured
exception, so the router's exception-to-HTTP mapping can be checked
without touching SQLAlchemy.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from app.main import app
from app.servers.api.dependencies import get_authorization_service
from app.servers.domain.exceptions import ServerNotFoundError
from app.servers.models import ServerType
from app.templates.api.dependencies import get_template_service
from app.templates.domain.entities import TemplateEntity, TemplateListPage
from app.templates.domain.exceptions import (
    TemplateAccessError,
    TemplateError,
    TemplateNotFoundError,
)

# ---------------------------------------------------------------- helpers


def _entity(
    *,
    id: int = 1,
    name: str = "tpl",
    description: Optional[str] = None,
    minecraft_version: str = "1.20.1",
    server_type: ServerType = ServerType.vanilla,
    configuration: Optional[Dict[str, Any]] = None,
    default_groups: Optional[Dict[str, List[int]]] = None,
    is_public: bool = False,
    created_by: int = 1,
) -> TemplateEntity:
    now = datetime.now(timezone.utc)
    return TemplateEntity(
        id=id,
        name=name,
        description=description,
        minecraft_version=minecraft_version,
        server_type=server_type,
        configuration=configuration or {},
        default_groups=default_groups or {"op_groups": [], "whitelist_groups": []},
        is_public=is_public,
        created_by=created_by,
        creator_name=None,
        created_at=now,
        updated_at=now,
    )


class _FakeTemplateService:
    """Hand-rolled stand-in for `TemplateService` used by the router."""

    def __init__(self) -> None:
        self.entity: TemplateEntity = _entity()
        # If set, the next call to that named method raises this exception.
        self.raise_on: Dict[str, BaseException] = {}
        # Override return value of `get_template` / `delete_template`.
        self.get_template_return: Any = "USE_ENTITY"  # sentinel
        self.delete_template_return: bool = True
        self.list_page: TemplateListPage = TemplateListPage(
            entities=[], total=0, page=1, size=50
        )
        self.stats: Dict[str, Any] = {
            "total_templates": 0,
            "public_templates": 0,
            "user_templates": 0,
            "server_type_distribution": {st.value: 0 for st in ServerType},
        }
        # Spy log.
        self.calls: List[tuple] = []

    def _maybe_raise(self, method: str) -> None:
        if method in self.raise_on:
            raise self.raise_on[method]

    async def create_template_from_server(self, **kwargs) -> TemplateEntity:
        self.calls.append(("create_template_from_server", kwargs))
        self._maybe_raise("create_template_from_server")
        return self.entity

    async def create_custom_template(self, **kwargs) -> TemplateEntity:
        self.calls.append(("create_custom_template", kwargs))
        self._maybe_raise("create_custom_template")
        return self.entity

    async def list_templates(self, **kwargs) -> TemplateListPage:
        self.calls.append(("list_templates", kwargs))
        self._maybe_raise("list_templates")
        return self.list_page

    async def get_template(self, *args, **kwargs) -> Optional[TemplateEntity]:
        # The router calls `get_template(template_id, viewer_id=..., viewer_is_admin=...)`
        merged = {"args": args, **kwargs}
        self.calls.append(("get_template", merged))
        self._maybe_raise("get_template")
        if self.get_template_return == "USE_ENTITY":
            return self.entity
        return self.get_template_return

    async def update_template(self, **kwargs) -> Optional[TemplateEntity]:
        self.calls.append(("update_template", kwargs))
        self._maybe_raise("update_template")
        return self.entity

    async def delete_template(self, *args, **kwargs) -> bool:
        merged = {"args": args, **kwargs}
        self.calls.append(("delete_template", merged))
        self._maybe_raise("delete_template")
        return self.delete_template_return

    async def get_template_statistics(self, **kwargs) -> Dict[str, Any]:
        self.calls.append(("get_template_statistics", kwargs))
        self._maybe_raise("get_template_statistics")
        return self.stats


class _FakeAuthorizationService:
    """Stand-in for `AuthorizationService` used by `/from-server/{id}`."""

    def __init__(self) -> None:
        self.raise_on_check_server_access: Optional[BaseException] = None
        self.calls: List[tuple] = []

    async def check_server_access(self, server_id, user):
        self.calls.append(("check_server_access", server_id, user.id))
        if self.raise_on_check_server_access is not None:
            raise self.raise_on_check_server_access
        return None  # router does not use the returned value


@pytest.fixture
def fake_service() -> _FakeTemplateService:
    return _FakeTemplateService()


@pytest.fixture
def fake_auth() -> _FakeAuthorizationService:
    return _FakeAuthorizationService()


@pytest.fixture
def override_service(fake_service: _FakeTemplateService):
    def _provide() -> _FakeTemplateService:
        return fake_service

    app.dependency_overrides[get_template_service] = _provide
    yield fake_service
    app.dependency_overrides.pop(get_template_service, None)


@pytest.fixture
def override_auth(fake_auth: _FakeAuthorizationService):
    def _provide() -> _FakeAuthorizationService:
        return fake_auth

    app.dependency_overrides[get_authorization_service] = _provide
    yield fake_auth
    app.dependency_overrides.pop(get_authorization_service, None)


# ---------------------------------------------------------------- POST /from-server/{server_id}


class TestCreateTemplateFromServer:
    PATH = "/api/v1/templates/from-server/5"
    BODY = {"name": "from-srv", "is_public": False}

    def test_201(self, client, admin_headers, override_service, override_auth):
        override_service.entity = _entity(id=10, name="from-srv")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["id"] == 10

    def test_404_when_template_not_found(
        self, client, admin_headers, override_service, override_auth
    ):
        override_service.raise_on["create_template_from_server"] = TemplateNotFoundError(
            "missing"
        )
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 404

    def test_400_on_template_error(
        self, client, admin_headers, override_service, override_auth
    ):
        override_service.raise_on["create_template_from_server"] = TemplateError("bad")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 400

    def test_404_when_server_missing(
        self, client, admin_headers, override_service, override_auth
    ):
        override_auth.raise_on_check_server_access = ServerNotFoundError("nope")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        # ServerNotFoundError is handled by global exception handler -> 404
        assert r.status_code == 404

    def test_500_on_unexpected(
        self, client, admin_headers, override_service, override_auth
    ):
        override_service.raise_on["create_template_from_server"] = RuntimeError("boom")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 500

    def test_422_invalid_payload(
        self, client, admin_headers, override_service, override_auth
    ):
        r = client.post(self.PATH, json={"name": "bad/name"}, headers=admin_headers)
        assert r.status_code == 422


# ---------------------------------------------------------------- POST /


class TestCreateCustomTemplate:
    PATH = "/api/v1/templates/"
    BODY: Dict[str, Any] = {
        "name": "custom",
        "minecraft_version": "1.20.1",
        "server_type": "vanilla",
    }

    def test_201(self, client, admin_headers, override_service):
        override_service.entity = _entity(id=11, name="custom")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["id"] == 11

    def test_400_on_template_error(self, client, admin_headers, override_service):
        override_service.raise_on["create_custom_template"] = TemplateError("bad")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 400

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["create_custom_template"] = RuntimeError("boom")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 500

    def test_422_invalid_name(self, client, admin_headers, override_service):
        body = {**self.BODY, "name": "bad/name"}
        r = client.post(self.PATH, json=body, headers=admin_headers)
        assert r.status_code == 422


# ---------------------------------------------------------------- GET /


class TestListTemplates:
    def test_200_empty(self, client, admin_headers, override_service):
        r = client.get("/api/v1/templates/", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["templates"] == []

    def test_200_with_entities(self, client, admin_headers, override_service):
        override_service.list_page = TemplateListPage(
            entities=[_entity(id=1), _entity(id=2, name="b")],
            total=2,
            page=1,
            size=50,
        )
        r = client.get("/api/v1/templates/", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert len(body["templates"]) == 2

    def test_passes_filters_through(self, client, admin_headers, override_service):
        r = client.get(
            "/api/v1/templates/"
            "?minecraft_version=1.20.1&server_type=paper&is_public=true&page=2&size=10",
            headers=admin_headers,
        )
        assert r.status_code == 200
        kwargs = override_service.calls[-1][1]
        assert kwargs["minecraft_version"] == "1.20.1"
        assert kwargs["server_type"] == ServerType.paper
        assert kwargs["is_public"] is True
        assert kwargs["page"] == 2
        assert kwargs["size"] == 10

    def test_admin_flag_passed_through(self, client, admin_headers, override_service):
        client.get("/api/v1/templates/", headers=admin_headers)
        kwargs = override_service.calls[-1][1]
        assert kwargs["viewer_is_admin"] is True

    def test_regular_user_admin_flag_false(self, client, user_headers, override_service):
        client.get("/api/v1/templates/", headers=user_headers)
        kwargs = override_service.calls[-1][1]
        assert kwargs["viewer_is_admin"] is False

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["list_templates"] = RuntimeError("boom")
        r = client.get("/api/v1/templates/", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- GET /statistics


class TestGetTemplateStatistics:
    def test_200(self, client, admin_headers, override_service):
        override_service.stats = {
            "total_templates": 5,
            "public_templates": 2,
            "user_templates": 3,
            "server_type_distribution": {
                "vanilla": 3,
                "paper": 1,
                "forge": 1,
                "spigot": 0,
                "fabric": 0,
                "bukkit": 0,
                "neoforge": 0,
                "purpur": 0,
                "quilt": 0,
            },
        }
        r = client.get("/api/v1/templates/statistics", headers=admin_headers)
        # Some ServerType enum values may not be present in the dict; only
        # assert on what's well-defined.
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_templates"] == 5
        assert body["public_templates"] == 2

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["get_template_statistics"] = RuntimeError("boom")
        r = client.get("/api/v1/templates/statistics", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- GET /{id}


class TestGetTemplate:
    def test_200(self, client, admin_headers, override_service):
        override_service.entity = _entity(id=7)
        r = client.get("/api/v1/templates/7", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["id"] == 7

    def test_404_when_none(self, client, admin_headers, override_service):
        override_service.get_template_return = None
        r = client.get("/api/v1/templates/7", headers=admin_headers)
        assert r.status_code == 404

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["get_template"] = TemplateAccessError("nope")
        r = client.get("/api/v1/templates/7", headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["get_template"] = RuntimeError("boom")
        r = client.get("/api/v1/templates/7", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- PUT /{id}


class TestUpdateTemplate:
    def test_200(self, client, admin_headers, override_service):
        override_service.entity = _entity(id=3, name="renamed")
        r = client.put(
            "/api/v1/templates/3",
            json={"name": "renamed"},
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["update_template"] = TemplateAccessError("nope")
        r = client.put("/api/v1/templates/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 403

    def test_400_template_error(self, client, admin_headers, override_service):
        override_service.raise_on["update_template"] = TemplateError("bad")
        r = client.put("/api/v1/templates/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 400

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["update_template"] = RuntimeError("boom")
        r = client.put("/api/v1/templates/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 500

    def test_422_invalid_name(self, client, admin_headers, override_service):
        r = client.put(
            "/api/v1/templates/3",
            json={"name": "bad/name"},
            headers=admin_headers,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------- DELETE /{id}


class TestDeleteTemplate:
    def test_204(self, client, admin_headers, override_service):
        r = client.delete("/api/v1/templates/3", headers=admin_headers)
        assert r.status_code == 204

    def test_404_when_not_found(self, client, admin_headers, override_service):
        override_service.delete_template_return = False
        r = client.delete("/api/v1/templates/3", headers=admin_headers)
        assert r.status_code == 404

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["delete_template"] = TemplateAccessError("nope")
        r = client.delete("/api/v1/templates/3", headers=admin_headers)
        assert r.status_code == 403

    def test_409_in_use(self, client, admin_headers, override_service):
        override_service.raise_on["delete_template"] = TemplateError("in use")
        r = client.delete("/api/v1/templates/3", headers=admin_headers)
        assert r.status_code == 409

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["delete_template"] = RuntimeError("boom")
        r = client.delete("/api/v1/templates/3", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- POST /{id}/clone


class TestCloneTemplate:
    PATH = "/api/v1/templates/5/clone"
    BODY = {"name": "cloned", "is_public": True}

    def test_201(self, client, admin_headers, override_service):
        original = _entity(id=5, name="orig")
        clone = _entity(id=6, name="cloned")
        override_service.entity = clone
        # The router does `get_template` first, then `create_custom_template`.
        # We want `get_template` to return the original and the next
        # `create_custom_template` to return the clone.
        override_service.get_template_return = original
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 201, r.text
        assert r.json()["id"] == 6
        # `create_custom_template` was called with the original's config
        last = next(
            c
            for c in reversed(override_service.calls)
            if c[0] == "create_custom_template"
        )
        assert last[1]["name"] == "cloned"
        assert last[1]["minecraft_version"] == "1.20.1"

    def test_404_when_original_missing(self, client, admin_headers, override_service):
        override_service.get_template_return = None
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 404

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["get_template"] = TemplateAccessError("nope")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 403

    def test_400_on_template_error(self, client, admin_headers, override_service):
        override_service.get_template_return = _entity(id=5)
        override_service.raise_on["create_custom_template"] = TemplateError("dup")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 400

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.get_template_return = _entity(id=5)
        override_service.raise_on["create_custom_template"] = RuntimeError("boom")
        r = client.post(self.PATH, json=self.BODY, headers=admin_headers)
        assert r.status_code == 500

    def test_422_invalid_name(self, client, admin_headers, override_service):
        r = client.post(self.PATH, json={"name": "bad/name"}, headers=admin_headers)
        assert r.status_code == 422
