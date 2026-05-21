"""Pure-function tests for `_check_group_access` / `_can_manage_server_groups`.

Phase 1 visibility is pass-through (`_check_group_access` returns
None), so the only behavioural rule that needs coverage is
`_can_manage_server_groups` ("admin OR server owner").

These helpers live at module scope on the application service so
tests can exercise them without instantiating the service or its Ports.
"""

import pytest

from app.groups.application.service import (
    _can_manage_server_groups,
    _check_group_access,
)
from app.servers.domain.entities import ServerEntity
from app.servers.models import ServerType
from tests.unit.groups.fakes import make_group_entity


def _server(owner_id: int) -> ServerEntity:
    return ServerEntity(
        id=1,
        name="s",
        directory_path="./servers/s",
        minecraft_version="1.20.1",
        server_type=ServerType.vanilla,
        port=25565,
        max_memory=1024,
        max_players=20,
        owner_id=owner_id,
    )


@pytest.mark.parametrize(
    "viewer_id,viewer_is_admin,owner_id,expected",
    [
        # admin always allowed
        (99, True, 1, True),
        # owner always allowed
        (1, False, 1, True),
        # non-owner non-admin blocked
        (99, False, 1, False),
    ],
)
def test_can_manage_server_groups(
    viewer_id: int,
    viewer_is_admin: bool,
    owner_id: int,
    expected: bool,
) -> None:
    server = _server(owner_id)
    assert _can_manage_server_groups(viewer_id, viewer_is_admin, server) is expected


def test_check_group_access_is_phase1_passthrough() -> None:
    """The Phase 1 rule is "every authenticated user can see every
    group". The helper exists to make the contract upgradeable; for
    now it must return `None` regardless of who is asking about which
    group."""
    group = make_group_entity(id=1, owner_id=42)
    assert _check_group_access(99, group) is None
    assert _check_group_access(42, group) is None
