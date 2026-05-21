"""Pure-function tests for `_can_access` / `_can_modify`.

These helpers used to live as `TemplateService._can_access_template`
and `TemplateService._can_modify_template` on the legacy service. The
new application service keeps them at module scope so unit tests can
exercise them without instantiating the service or its Ports.
"""

import pytest

from app.templates.application.service import _can_access, _can_modify
from tests.unit.templates.fakes import make_template_entity


@pytest.mark.parametrize(
    "is_public,viewer_id,owner_id,viewer_is_admin,expected",
    [
        # admins see everything
        (False, 99, 1, True, True),
        (True, 99, 1, True, True),
        # owner always sees own private template
        (False, 1, 1, False, True),
        # non-owner sees public
        (True, 99, 1, False, True),
        # non-owner blocked from private
        (False, 99, 1, False, False),
    ],
)
def test_can_access(
    is_public: bool,
    viewer_id: int,
    owner_id: int,
    viewer_is_admin: bool,
    expected: bool,
) -> None:
    entity = make_template_entity(id=1, created_by=owner_id, is_public=is_public)
    assert _can_access(entity, viewer_id, viewer_is_admin) is expected


@pytest.mark.parametrize(
    "viewer_id,owner_id,viewer_is_admin,expected",
    [
        # admin can modify anyone's
        (99, 1, True, True),
        # owner can modify own
        (1, 1, False, True),
        # non-owner non-admin cannot modify, even if public
        (99, 1, False, False),
    ],
)
def test_can_modify(
    viewer_id: int, owner_id: int, viewer_is_admin: bool, expected: bool
) -> None:
    # is_public flag is irrelevant for modify permission
    entity = make_template_entity(id=1, created_by=owner_id, is_public=True)
    assert _can_modify(entity, viewer_id, viewer_is_admin) is expected
