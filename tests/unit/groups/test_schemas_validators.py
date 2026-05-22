"""Unit tests for `app.groups.schemas` validators.

Covers field validators and ``model_post_init`` rules in isolation
(no FastAPI / DB) so schema errors are caught at the boundary before
hitting the application service.
"""

import pytest
from pydantic import ValidationError

from app.groups.models import GroupType
from app.groups.schemas import (
    GroupCreateRequest,
    GroupUpdateRequest,
    PlayerAddRequest,
    PlayerRemoveRequest,
    ServerAttachRequest,
    ServerDetachRequest,
)


class TestGroupCreateRequestName:
    """`GroupCreateRequest.name` allows alnum / space / hyphen / underscore."""

    def test_valid_name_passes(self):
        req = GroupCreateRequest(
            name="my-group_1", group_type=GroupType.op, description="desc"
        )
        assert req.name == "my-group_1"
        assert req.description == "desc"

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError) as exc:
            GroupCreateRequest(name="   ", group_type=GroupType.op)
        # min_length=1 check trims; either way, validator surfaces error
        assert "empty" in str(exc.value).lower() or "string" in str(exc.value).lower()

    def test_empty_rejected_by_min_length(self):
        with pytest.raises(ValidationError):
            GroupCreateRequest(name="", group_type=GroupType.op)

    def test_invalid_chars_rejected(self):
        with pytest.raises(ValidationError) as exc:
            GroupCreateRequest(name="bad!name", group_type=GroupType.op)
        assert "invalid characters" in str(exc.value)

    def test_max_length_boundary(self):
        # 100 chars OK
        req = GroupCreateRequest(name="a" * 100, group_type=GroupType.whitelist)
        assert len(req.name) == 100
        # 101 chars fails
        with pytest.raises(ValidationError):
            GroupCreateRequest(name="a" * 101, group_type=GroupType.whitelist)

    def test_name_stripped(self):
        req = GroupCreateRequest(name="  good  ", group_type=GroupType.op)
        assert req.name == "good"

    def test_description_max_length(self):
        # 500 chars OK, 501 fails
        GroupCreateRequest(
            name="ok",
            group_type=GroupType.op,
            description="d" * 500,
        )
        with pytest.raises(ValidationError):
            GroupCreateRequest(
                name="ok",
                group_type=GroupType.op,
                description="d" * 501,
            )


class TestGroupUpdateRequest:
    """`GroupUpdateRequest` fields are all-optional and pass `None` through."""

    def test_all_none_is_valid(self):
        req = GroupUpdateRequest()
        assert req.name is None
        assert req.description is None

    def test_none_name_passes(self):
        req = GroupUpdateRequest(description="new desc")
        assert req.name is None
        assert req.description == "new desc"

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError) as exc:
            GroupUpdateRequest(name="   ")
        assert "empty" in str(exc.value).lower()

    def test_strips_name(self):
        req = GroupUpdateRequest(name="  new  ")
        assert req.name == "new"

    def test_empty_string_rejected_by_min_length(self):
        with pytest.raises(ValidationError):
            GroupUpdateRequest(name="")


class TestPlayerAddRequest:
    """`PlayerAddRequest` exclusive `uuid` / `username` / `player_name`."""

    def test_uuid_only_passes(self):
        req = PlayerAddRequest(uuid="11111111-2222-3333-4444-555555555555")
        assert req.uuid == "11111111-2222-3333-4444-555555555555"
        assert req.username is None

    def test_username_only_passes(self):
        req = PlayerAddRequest(username="Notch")
        assert req.username == "Notch"
        assert req.uuid is None

    def test_player_name_alias_promoted_to_username(self):
        req = PlayerAddRequest(player_name="Steve")
        # model_post_init copies player_name -> username
        assert req.username == "Steve"
        assert req.player_name == "Steve"

    def test_player_name_does_not_override_username(self):
        req = PlayerAddRequest(username="Notch", player_name="Steve")
        assert req.username == "Notch"

    def test_both_uuid_and_username_passes(self):
        # The validator only requires at least one; both is acceptable.
        req = PlayerAddRequest(
            uuid="11111111-2222-3333-4444-555555555555",
            username="Notch",
        )
        assert req.uuid is not None
        assert req.username == "Notch"

    def test_all_none_raises(self):
        with pytest.raises(ValidationError):
            PlayerAddRequest()

    def test_uuid_without_hyphens_passes(self):
        req = PlayerAddRequest(uuid="1" * 32)
        assert req.uuid == "1" * 32

    def test_invalid_uuid_format_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PlayerAddRequest(uuid="not-a-valid-uuid-zzzzzzzzzzzzzzzzzzz")
        assert "uuid" in str(exc.value).lower()

    def test_invalid_username_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PlayerAddRequest(username="bad name!")
        assert "username" in str(exc.value).lower()

    def test_username_too_long_rejected(self):
        # 17 chars > max 16
        with pytest.raises(ValidationError):
            PlayerAddRequest(username="a" * 17)

    def test_invalid_player_name_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PlayerAddRequest(player_name="bad name!")
        assert "username" in str(exc.value).lower()

    def test_uuid_too_short_rejected_by_min_length(self):
        with pytest.raises(ValidationError):
            PlayerAddRequest(uuid="abc")


class TestPlayerRemoveRequest:
    """`PlayerRemoveRequest.uuid` is required."""

    def test_valid_dashed_uuid(self):
        req = PlayerRemoveRequest(uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert req.uuid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_valid_unhyphenated_uuid(self):
        req = PlayerRemoveRequest(uuid="a" * 32)
        assert req.uuid == "a" * 32

    def test_missing_uuid_rejected(self):
        with pytest.raises(ValidationError):
            PlayerRemoveRequest()  # type: ignore[call-arg]

    def test_invalid_uuid_rejected(self):
        # 32 chars but contains non-hex
        with pytest.raises(ValidationError):
            PlayerRemoveRequest(uuid="z" * 32)

    def test_uuid_too_short_rejected(self):
        with pytest.raises(ValidationError):
            PlayerRemoveRequest(uuid="abc")


class TestServerAttachRequest:
    """`ServerAttachRequest` priority boundaries."""

    def test_defaults_priority_to_zero(self):
        req = ServerAttachRequest(server_id=1)
        assert req.priority == 0

    def test_priority_zero_passes(self):
        req = ServerAttachRequest(server_id=1, priority=0)
        assert req.priority == 0

    def test_priority_one_hundred_passes(self):
        req = ServerAttachRequest(server_id=1, priority=100)
        assert req.priority == 100

    def test_priority_negative_rejected(self):
        with pytest.raises(ValidationError):
            ServerAttachRequest(server_id=1, priority=-1)

    def test_priority_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ServerAttachRequest(server_id=1, priority=101)

    def test_server_id_must_be_at_least_one(self):
        with pytest.raises(ValidationError):
            ServerAttachRequest(server_id=0)


class TestServerDetachRequest:
    """`ServerDetachRequest.server_id` must be >= 1."""

    def test_valid(self):
        req = ServerDetachRequest(server_id=5)
        assert req.server_id == 5

    def test_zero_rejected(self):
        with pytest.raises(ValidationError):
            ServerDetachRequest(server_id=0)
