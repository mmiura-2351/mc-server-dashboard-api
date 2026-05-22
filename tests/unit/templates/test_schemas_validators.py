"""Unit tests for `app.templates.schemas` validators.

Covers field validators on create/update/clone request models in
isolation (no FastAPI / DB).
"""

import pytest
from pydantic import ValidationError

from app.servers.models import ServerType
from app.templates.schemas import (
    TemplateCloneRequest,
    TemplateCreateCustomRequest,
    TemplateCreateFromServerRequest,
    TemplateFilterRequest,
    TemplateUpdateRequest,
)

# Shared list of forbidden characters per the schema validators.
INVALID_CHARS = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]


class TestTemplateCreateFromServerRequest:
    def test_minimal_valid(self):
        req = TemplateCreateFromServerRequest(name="My Template")
        assert req.name == "My Template"
        assert req.description is None
        assert req.is_public is False

    def test_whitespace_only_name_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreateFromServerRequest(name="    ")
        assert "empty" in str(exc.value).lower()

    def test_empty_name_rejected_by_min_length(self):
        with pytest.raises(ValidationError):
            TemplateCreateFromServerRequest(name="")

    @pytest.mark.parametrize("bad_char", INVALID_CHARS)
    def test_invalid_chars_rejected(self, bad_char):
        with pytest.raises(ValidationError) as exc:
            TemplateCreateFromServerRequest(name=f"bad{bad_char}name")
        assert "invalid characters" in str(exc.value)

    def test_name_stripped(self):
        req = TemplateCreateFromServerRequest(name="  ok  ")
        assert req.name == "ok"

    def test_max_length(self):
        TemplateCreateFromServerRequest(name="a" * 100)
        with pytest.raises(ValidationError):
            TemplateCreateFromServerRequest(name="a" * 101)

    def test_description_max_length(self):
        TemplateCreateFromServerRequest(name="ok", description="d" * 500)
        with pytest.raises(ValidationError):
            TemplateCreateFromServerRequest(name="ok", description="d" * 501)


class TestTemplateCreateCustomRequest:
    def test_minimal_valid(self):
        req = TemplateCreateCustomRequest(
            name="Custom",
            minecraft_version="1.20.1",
            server_type=ServerType.vanilla,
        )
        assert req.minecraft_version == "1.20.1"
        assert req.server_type == ServerType.vanilla
        assert req.configuration == {}
        assert req.default_groups is None
        assert req.is_public is False

    def test_invalid_name_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreateCustomRequest(
                name="bad/name",
                minecraft_version="1.20.1",
                server_type=ServerType.vanilla,
            )
        assert "invalid characters" in str(exc.value)

    def test_minecraft_version_three_part(self):
        req = TemplateCreateCustomRequest(
            name="ok",
            minecraft_version="1.20.4",
            server_type=ServerType.paper,
        )
        assert req.minecraft_version == "1.20.4"

    def test_minecraft_version_two_part(self):
        req = TemplateCreateCustomRequest(
            name="ok",
            minecraft_version="1.20",
            server_type=ServerType.paper,
        )
        assert req.minecraft_version == "1.20"

    def test_minecraft_version_stripped(self):
        req = TemplateCreateCustomRequest(
            name="ok",
            minecraft_version="  1.20.1  ",
            server_type=ServerType.vanilla,
        )
        assert req.minecraft_version == "1.20.1"

    def test_minecraft_version_empty_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreateCustomRequest(
                name="ok",
                minecraft_version="   ",
                server_type=ServerType.vanilla,
            )
        assert "empty" in str(exc.value).lower()

    def test_minecraft_version_invalid_format_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TemplateCreateCustomRequest(
                name="ok",
                minecraft_version="abc",
                server_type=ServerType.vanilla,
            )
        assert "version" in str(exc.value).lower()

    def test_minecraft_version_too_many_parts_rejected(self):
        with pytest.raises(ValidationError):
            TemplateCreateCustomRequest(
                name="ok",
                minecraft_version="1.20.1.5",
                server_type=ServerType.vanilla,
            )

    def test_passes_through_configuration(self):
        req = TemplateCreateCustomRequest(
            name="ok",
            minecraft_version="1.20.1",
            server_type=ServerType.paper,
            configuration={"motd": "Hello"},
            default_groups={"op_groups": [1, 2], "whitelist_groups": [3]},
            is_public=True,
        )
        assert req.configuration == {"motd": "Hello"}
        assert req.default_groups == {"op_groups": [1, 2], "whitelist_groups": [3]}
        assert req.is_public is True


class TestTemplateUpdateRequest:
    def test_all_none_is_valid(self):
        req = TemplateUpdateRequest()
        assert req.name is None
        assert req.description is None
        assert req.configuration is None

    def test_none_name_passes(self):
        req = TemplateUpdateRequest(is_public=True)
        assert req.name is None
        assert req.is_public is True

    def test_whitespace_only_name_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TemplateUpdateRequest(name="  ")
        assert "empty" in str(exc.value).lower()

    @pytest.mark.parametrize("bad_char", INVALID_CHARS)
    def test_invalid_chars_rejected(self, bad_char):
        with pytest.raises(ValidationError) as exc:
            TemplateUpdateRequest(name=f"bad{bad_char}")
        assert "invalid characters" in str(exc.value)

    def test_name_stripped(self):
        req = TemplateUpdateRequest(name="  rename  ")
        assert req.name == "rename"

    def test_empty_string_rejected_by_min_length(self):
        with pytest.raises(ValidationError):
            TemplateUpdateRequest(name="")


class TestTemplateCloneRequest:
    def test_valid(self):
        req = TemplateCloneRequest(name="Cloned")
        assert req.name == "Cloned"
        assert req.is_public is False

    def test_invalid_chars_rejected(self):
        with pytest.raises(ValidationError):
            TemplateCloneRequest(name="bad/name")

    def test_name_stripped(self):
        req = TemplateCloneRequest(name="  Cloned  ", description="copy")
        assert req.name == "Cloned"
        assert req.description == "copy"

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            TemplateCloneRequest(name="")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError):
            TemplateCloneRequest(name="   ")


class TestTemplateFilterRequest:
    def test_defaults(self):
        req = TemplateFilterRequest()
        assert req.minecraft_version is None
        assert req.server_type is None
        assert req.is_public is None
        assert req.page == 1
        assert req.size == 50

    def test_page_lower_bound(self):
        with pytest.raises(ValidationError):
            TemplateFilterRequest(page=0)

    def test_size_upper_bound(self):
        TemplateFilterRequest(size=100)  # max OK
        with pytest.raises(ValidationError):
            TemplateFilterRequest(size=101)

    def test_size_lower_bound(self):
        with pytest.raises(ValidationError):
            TemplateFilterRequest(size=0)
