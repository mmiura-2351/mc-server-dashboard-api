"""Integration tests for `app.groups.router`.

Drives the FastAPI app via `TestClient` and overrides
`get_group_service` with a hand-rolled fake whose methods either
return a pre-canned `GroupEntity` / view, or raise a configured
domain exception. This exercises the router's exception-to-HTTP
mapping without touching the SQLAlchemy stack.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from app.groups.api.dependencies import get_group_service
from app.groups.domain.entities import (
    AttachedGroupView,
    AttachedServerView,
    GroupEntity,
    GroupListPage,
)
from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupHasAttachmentsError,
    GroupNotFoundError,
    PlayerNotFoundInGroup,
    ServerGroupAttachmentExistsError,
    ServerGroupAttachmentNotFoundError,
    ServerNotFoundForAttachment,
)
from app.groups.models import GroupType
from app.main import app
from app.servers.models import ServerStatus

# ---------------------------------------------------------------- helpers


def _entity(
    *,
    id: int = 1,
    owner_id: int = 1,
    name: str = "g",
    type: GroupType = GroupType.op,
    description: Optional[str] = None,
    players: Optional[List[Dict[str, Any]]] = None,
) -> GroupEntity:
    now = datetime.now(timezone.utc)
    return GroupEntity(
        id=id,
        name=name,
        description=description,
        type=type,
        players=players or [],
        owner_id=owner_id,
        is_template=False,
        created_at=now,
        updated_at=now,
    )


class _FakeGroupService:
    """Hand-rolled stand-in for `GroupService` used by the router.

    Each method consults a per-method 'effect' attribute. If it's an
    Exception subclass instance, it's raised; otherwise it's returned.
    Default behaviour is a successful no-op returning a placeholder.
    """

    def __init__(self) -> None:
        # Returned by methods that produce a GroupEntity. Tests override.
        self.entity: GroupEntity = _entity()
        # Raised by any method whose name appears here.
        self.raise_on: Dict[str, BaseException] = {}
        # Captured call args for spy-style assertions.
        self.calls: List[tuple] = []
        # list_groups / list_attachments customisations
        self.list_entities: List[GroupEntity] = []
        self.attached_servers: List[AttachedServerView] = []
        self.attached_groups: List[AttachedGroupView] = []

    def _maybe_raise(self, method: str) -> None:
        if method in self.raise_on:
            raise self.raise_on[method]

    async def create_group(self, **kwargs) -> GroupEntity:
        self.calls.append(("create_group", kwargs))
        self._maybe_raise("create_group")
        return self.entity

    async def list_groups(self, **kwargs) -> GroupListPage:
        self.calls.append(("list_groups", kwargs))
        self._maybe_raise("list_groups")
        page = kwargs.get("page", 1)
        size = kwargs.get("size", 50)
        return GroupListPage(
            entities=self.list_entities,
            total=len(self.list_entities),
            page=page,
            size=size,
        )

    async def get_group(self, **kwargs) -> GroupEntity:
        self.calls.append(("get_group", kwargs))
        self._maybe_raise("get_group")
        return self.entity

    async def update_group(self, **kwargs) -> GroupEntity:
        self.calls.append(("update_group", kwargs))
        self._maybe_raise("update_group")
        return self.entity

    async def delete_group(self, **kwargs) -> None:
        self.calls.append(("delete_group", kwargs))
        self._maybe_raise("delete_group")

    async def add_player(self, **kwargs) -> GroupEntity:
        self.calls.append(("add_player", kwargs))
        self._maybe_raise("add_player")
        return self.entity

    async def remove_player(self, **kwargs) -> GroupEntity:
        self.calls.append(("remove_player", kwargs))
        self._maybe_raise("remove_player")
        return self.entity

    async def attach_group_to_server(self, **kwargs) -> None:
        self.calls.append(("attach_group_to_server", kwargs))
        self._maybe_raise("attach_group_to_server")

    async def detach_group_from_server(self, **kwargs) -> None:
        self.calls.append(("detach_group_from_server", kwargs))
        self._maybe_raise("detach_group_from_server")

    async def get_group_servers(self, **kwargs) -> List[AttachedServerView]:
        self.calls.append(("get_group_servers", kwargs))
        self._maybe_raise("get_group_servers")
        return self.attached_servers

    async def get_server_groups(self, **kwargs) -> List[AttachedGroupView]:
        self.calls.append(("get_server_groups", kwargs))
        self._maybe_raise("get_server_groups")
        return self.attached_groups


@pytest.fixture
def fake_service() -> _FakeGroupService:
    return _FakeGroupService()


@pytest.fixture
def override_service(fake_service: _FakeGroupService):
    """Install the fake under `get_group_service` for the test's lifetime."""

    def _provide() -> _FakeGroupService:
        return fake_service

    app.dependency_overrides[get_group_service] = _provide
    yield fake_service
    app.dependency_overrides.pop(get_group_service, None)


# ---------------------------------------------------------------- POST /api/v1/groups


class TestCreateGroup:
    def test_201_on_success(self, client, admin_headers, override_service):
        override_service.entity = _entity(id=42, name="alpha", owner_id=99)
        r = client.post(
            "/api/v1/groups",
            json={"name": "alpha", "group_type": "op"},
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] == 42
        assert body["name"] == "alpha"
        assert body["type"] == "op"

    def test_400_on_duplicate_name(self, client, admin_headers, override_service):
        override_service.raise_on["create_group"] = GroupAlreadyExistsError("dup")
        r = client.post(
            "/api/v1/groups",
            json={"name": "alpha", "group_type": "op"},
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert "dup" in r.json()["detail"]

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["create_group"] = RuntimeError("boom")
        r = client.post(
            "/api/v1/groups",
            json={"name": "alpha", "group_type": "op"},
            headers=admin_headers,
        )
        assert r.status_code == 500
        assert "boom" in r.json()["detail"]

    def test_401_without_auth(self, client, override_service):
        r = client.post("/api/v1/groups", json={"name": "a", "group_type": "op"})
        assert r.status_code == 401

    def test_422_invalid_payload(self, client, admin_headers, override_service):
        r = client.post(
            "/api/v1/groups",
            json={"name": "bad!chars", "group_type": "op"},
            headers=admin_headers,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------- GET /api/v1/groups


class TestListGroups:
    def test_200_returns_groups(self, client, admin_headers, override_service):
        override_service.list_entities = [
            _entity(id=1, name="a"),
            _entity(id=2, name="b", type=GroupType.whitelist),
        ]
        r = client.get("/api/v1/groups", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert {g["name"] for g in body["groups"]} == {"a", "b"}

    def test_200_with_group_type_filter(self, client, admin_headers, override_service):
        override_service.list_entities = []
        r = client.get("/api/v1/groups?group_type=whitelist", headers=admin_headers)
        assert r.status_code == 200
        # Last call was list_groups with group_type=whitelist
        last = override_service.calls[-1]
        assert last[0] == "list_groups"
        assert last[1]["group_type"] == GroupType.whitelist

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["list_groups"] = RuntimeError("boom")
        r = client.get("/api/v1/groups", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- GET /{group_id}


class TestGetGroup:
    def test_200(self, client, admin_headers, override_service):
        override_service.entity = _entity(id=7, name="seven")
        r = client.get("/api/v1/groups/7", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["id"] == 7

    def test_404_not_found(self, client, admin_headers, override_service):
        override_service.raise_on["get_group"] = GroupNotFoundError("missing")
        r = client.get("/api/v1/groups/7", headers=admin_headers)
        assert r.status_code == 404

    def test_403_access_denied(self, client, admin_headers, override_service):
        override_service.raise_on["get_group"] = GroupAccessError("nope")
        r = client.get("/api/v1/groups/7", headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["get_group"] = RuntimeError("boom")
        r = client.get("/api/v1/groups/7", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- PUT /{group_id}


class TestUpdateGroup:
    def test_200(self, client, admin_headers, override_service):
        override_service.entity = _entity(id=3, name="renamed")
        r = client.put(
            "/api/v1/groups/3",
            json={"name": "renamed"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "renamed"

    def test_404_not_found(self, client, admin_headers, override_service):
        override_service.raise_on["update_group"] = GroupNotFoundError("nope")
        r = client.put("/api/v1/groups/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 404

    def test_400_already_exists(self, client, admin_headers, override_service):
        override_service.raise_on["update_group"] = GroupAlreadyExistsError("dup")
        r = client.put("/api/v1/groups/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 400

    def test_403_access_denied(self, client, admin_headers, override_service):
        override_service.raise_on["update_group"] = GroupAccessError("nope")
        r = client.put("/api/v1/groups/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["update_group"] = RuntimeError("boom")
        r = client.put("/api/v1/groups/3", json={"name": "x"}, headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- DELETE /{group_id}


class TestDeleteGroup:
    def test_204(self, client, admin_headers, override_service):
        r = client.delete("/api/v1/groups/3", headers=admin_headers)
        assert r.status_code == 204

    def test_404(self, client, admin_headers, override_service):
        override_service.raise_on["delete_group"] = GroupNotFoundError("nope")
        r = client.delete("/api/v1/groups/3", headers=admin_headers)
        assert r.status_code == 404

    def test_400_has_attachments(self, client, admin_headers, override_service):
        override_service.raise_on["delete_group"] = GroupHasAttachmentsError("nope")
        r = client.delete("/api/v1/groups/3", headers=admin_headers)
        assert r.status_code == 400

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["delete_group"] = GroupAccessError("nope")
        r = client.delete("/api/v1/groups/3", headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["delete_group"] = RuntimeError("boom")
        r = client.delete("/api/v1/groups/3", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- POST /{group_id}/players


class TestAddPlayer:
    UUID = "11111111-2222-3333-4444-555555555555"

    def test_200_with_uuid(self, client, admin_headers, override_service):
        r = client.post(
            "/api/v1/groups/1/players",
            json={"uuid": self.UUID},
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_200_with_username(self, client, admin_headers, override_service):
        r = client.post(
            "/api/v1/groups/1/players",
            json={"username": "Notch"},
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_404(self, client, admin_headers, override_service):
        override_service.raise_on["add_player"] = GroupNotFoundError("nope")
        r = client.post(
            "/api/v1/groups/1/players",
            json={"username": "Notch"},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_403(self, client, admin_headers, override_service):
        override_service.raise_on["add_player"] = GroupAccessError("nope")
        r = client.post(
            "/api/v1/groups/1/players",
            json={"username": "Notch"},
            headers=admin_headers,
        )
        assert r.status_code == 403

    def test_400_on_value_error(self, client, admin_headers, override_service):
        override_service.raise_on["add_player"] = ValueError("nope")
        r = client.post(
            "/api/v1/groups/1/players",
            json={"username": "Notch"},
            headers=admin_headers,
        )
        assert r.status_code == 400

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["add_player"] = RuntimeError("boom")
        r = client.post(
            "/api/v1/groups/1/players",
            json={"username": "Notch"},
            headers=admin_headers,
        )
        assert r.status_code == 500

    def test_422_payload_missing_required(self, client, admin_headers, override_service):
        # Neither uuid nor username/player_name -> 422 from validator
        r = client.post("/api/v1/groups/1/players", json={}, headers=admin_headers)
        assert r.status_code == 422


# ---------------------------------------------------------------- DELETE /{group_id}/players/{uuid}


class TestRemovePlayer:
    UUID = "11111111-2222-3333-4444-555555555555"

    def test_200(self, client, admin_headers, override_service):
        r = client.delete(f"/api/v1/groups/1/players/{self.UUID}", headers=admin_headers)
        assert r.status_code == 200

    def test_404_group(self, client, admin_headers, override_service):
        override_service.raise_on["remove_player"] = GroupNotFoundError("nope")
        r = client.delete(f"/api/v1/groups/1/players/{self.UUID}", headers=admin_headers)
        assert r.status_code == 404

    def test_404_player(self, client, admin_headers, override_service):
        override_service.raise_on["remove_player"] = PlayerNotFoundInGroup("nope")
        r = client.delete(f"/api/v1/groups/1/players/{self.UUID}", headers=admin_headers)
        assert r.status_code == 404

    def test_403(self, client, admin_headers, override_service):
        override_service.raise_on["remove_player"] = GroupAccessError("nope")
        r = client.delete(f"/api/v1/groups/1/players/{self.UUID}", headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["remove_player"] = RuntimeError("boom")
        r = client.delete(f"/api/v1/groups/1/players/{self.UUID}", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- POST /{group_id}/servers


class TestAttachGroupToServer:
    def test_200(self, client, admin_headers, override_service):
        r = client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5, "priority": 10},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "attached" in r.json()["message"]

    def test_passes_admin_flag_for_admin(self, client, admin_headers, override_service):
        client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=admin_headers,
        )
        last = override_service.calls[-1]
        assert last[0] == "attach_group_to_server"
        assert last[1]["actor_is_admin"] is True

    def test_passes_admin_flag_for_regular_user(
        self, client, user_headers, override_service
    ):
        client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=user_headers,
        )
        last = override_service.calls[-1]
        assert last[1]["actor_is_admin"] is False

    def test_404_server(self, client, admin_headers, override_service):
        override_service.raise_on["attach_group_to_server"] = ServerNotFoundForAttachment(
            "nope"
        )
        r = client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_404_group(self, client, admin_headers, override_service):
        override_service.raise_on["attach_group_to_server"] = GroupNotFoundError("nope")
        r = client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_400_already_attached(self, client, admin_headers, override_service):
        override_service.raise_on["attach_group_to_server"] = (
            ServerGroupAttachmentExistsError("nope")
        )
        r = client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=admin_headers,
        )
        assert r.status_code == 400

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["attach_group_to_server"] = GroupAccessError("nope")
        r = client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=admin_headers,
        )
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["attach_group_to_server"] = RuntimeError("boom")
        r = client.post(
            "/api/v1/groups/1/servers",
            json={"server_id": 5},
            headers=admin_headers,
        )
        assert r.status_code == 500


# ---------------------------------------------------------------- DELETE /{group_id}/servers/{server_id}


class TestDetachGroupFromServer:
    def test_200(self, client, admin_headers, override_service):
        r = client.delete("/api/v1/groups/1/servers/5", headers=admin_headers)
        assert r.status_code == 200
        assert "detached" in r.json()["message"]

    def test_404_server(self, client, admin_headers, override_service):
        override_service.raise_on["detach_group_from_server"] = (
            ServerNotFoundForAttachment("nope")
        )
        r = client.delete("/api/v1/groups/1/servers/5", headers=admin_headers)
        assert r.status_code == 404

    def test_404_group(self, client, admin_headers, override_service):
        override_service.raise_on["detach_group_from_server"] = GroupNotFoundError("nope")
        r = client.delete("/api/v1/groups/1/servers/5", headers=admin_headers)
        assert r.status_code == 404

    def test_404_attachment(self, client, admin_headers, override_service):
        override_service.raise_on["detach_group_from_server"] = (
            ServerGroupAttachmentNotFoundError("nope")
        )
        r = client.delete("/api/v1/groups/1/servers/5", headers=admin_headers)
        assert r.status_code == 404

    def test_403_access(self, client, admin_headers, override_service):
        override_service.raise_on["detach_group_from_server"] = GroupAccessError("nope")
        r = client.delete("/api/v1/groups/1/servers/5", headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["detach_group_from_server"] = RuntimeError("boom")
        r = client.delete("/api/v1/groups/1/servers/5", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- GET /{group_id}/servers


class TestGetGroupServers:
    def test_200_serialises_views(self, client, admin_headers, override_service):
        now = datetime.now(timezone.utc)
        override_service.attached_servers = [
            AttachedServerView(
                id=10,
                name="srv-A",
                status=ServerStatus.stopped,
                priority=3,
                attached_at=now,
            )
        ]
        r = client.get("/api/v1/groups/1/servers", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["group_id"] == 1
        assert body["servers"][0]["name"] == "srv-A"
        assert body["servers"][0]["status"] == "stopped"
        assert body["servers"][0]["priority"] == 3

    def test_404(self, client, admin_headers, override_service):
        override_service.raise_on["get_group_servers"] = GroupNotFoundError("nope")
        r = client.get("/api/v1/groups/1/servers", headers=admin_headers)
        assert r.status_code == 404

    def test_403(self, client, admin_headers, override_service):
        override_service.raise_on["get_group_servers"] = GroupAccessError("nope")
        r = client.get("/api/v1/groups/1/servers", headers=admin_headers)
        assert r.status_code == 403

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["get_group_servers"] = RuntimeError("boom")
        r = client.get("/api/v1/groups/1/servers", headers=admin_headers)
        assert r.status_code == 500


# ---------------------------------------------------------------- GET /servers/{server_id}


class TestGetServerGroups:
    def test_200_serialises_views(self, client, admin_headers, override_service):
        now = datetime.now(timezone.utc)
        override_service.attached_groups = [
            AttachedGroupView(
                id=21,
                name="ops",
                description="d",
                type=GroupType.op,
                priority=5,
                attached_at=now,
                player_count=3,
            )
        ]
        r = client.get("/api/v1/groups/servers/9", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["server_id"] == 9
        assert body["groups"][0]["type"] == "op"
        assert body["groups"][0]["player_count"] == 3

    def test_404(self, client, admin_headers, override_service):
        override_service.raise_on["get_server_groups"] = ServerNotFoundForAttachment(
            "nope"
        )
        r = client.get("/api/v1/groups/servers/9", headers=admin_headers)
        assert r.status_code == 404

    def test_500_on_unexpected(self, client, admin_headers, override_service):
        override_service.raise_on["get_server_groups"] = RuntimeError("boom")
        r = client.get("/api/v1/groups/servers/9", headers=admin_headers)
        assert r.status_code == 500
