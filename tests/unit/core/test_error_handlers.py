"""Tests for the standard error envelope (Issue #76).

Validates that:
  * Domain exceptions are rendered with the new ``ErrorResponse``
    fields (``error``, ``message``, ``status_code``, ``timestamp``,
    ``request_id``) while keeping the legacy ``detail`` mirror.
  * ``RequestValidationError`` (422) populates ``details`` with
    per-field errors.
  * ``HTTPException`` falls back to a synthesised ``HTTP_<code>`` and
    unhandled exceptions become ``INTERNAL_ERROR`` (500).
  * The ``X-Request-ID`` request header is honored when present and
    surfaces in the response payload.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import (
    ConflictException,
)
from app.core.exceptions import (
    ServerNotFoundException as LegacyServerNotFoundException,
)
from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupNotFoundError,
)
from app.middleware.audit_middleware import AuditMiddleware
from app.servers.domain.exceptions import (
    JavaCompatibilityError,
    NoAvailablePortError,
    ServerAccessError,
    ServerJarDownloadError,
    ServerNameConflictError,
    ServerNotFoundError,
    ServerPortConflictError,
    UnsupportedMinecraftVersionError,
)
from app.templates.domain.exceptions import TemplateNotFoundError


class _ValidationBody(BaseModel):
    """Top-level model used by the validation-error tests.

    Declared at module scope (rather than inside ``_build_app``) so
    Pydantic v2's schema builder can resolve forward references — when
    defined locally, the validator was treating the whole request body
    as a single failing field rather than per-field errors.
    """

    name: str
    count: int


def _build_app() -> FastAPI:
    """Build a minimal app with the audit middleware + error handlers.

    The audit middleware is required so ``request.state.request_id`` is
    populated; without it the handlers would still respond but with
    ``request_id=None``.
    """
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(AuditMiddleware, enabled=True, exclude_health_checks=False)

    @app.get("/raise-server-not-found")
    def _server_nf():
        raise ServerNotFoundError("nope")

    @app.get("/raise-server-access")
    def _server_access():
        raise ServerAccessError("forbidden")

    @app.get("/raise-group-not-found")
    def _group_nf():
        raise GroupNotFoundError("missing")

    @app.get("/raise-group-access")
    def _group_access():
        raise GroupAccessError("forbidden")

    @app.get("/raise-group-exists")
    def _group_exists():
        raise GroupAlreadyExistsError("dup")

    @app.get("/raise-template-not-found")
    def _template_nf():
        raise TemplateNotFoundError("nope")

    # ---- Issue #33: server-creation actionable errors ----
    @app.get("/raise-server-name-conflict")
    def _server_name_conflict():
        raise ServerNameConflictError("dup-name")

    @app.get("/raise-server-port-conflict")
    def _server_port_conflict():
        raise ServerPortConflictError(
            port=25565,
            conflicting_server="other-server",
            suggested_ports=[25566, 25567, 25568],
        )

    @app.get("/raise-server-unsupported-version")
    def _server_unsupported_version():
        raise UnsupportedMinecraftVersionError(version="0.1", server_type="vanilla")

    @app.get("/raise-server-java-incompatible")
    def _server_java_incompatible():
        raise JavaCompatibilityError(
            minecraft_version="1.21.1",
            required_java=21,
            available_java=[17],
        )

    @app.get("/raise-server-jar-download-failed")
    def _server_jar_download_failed():
        raise ServerJarDownloadError(
            server_type="vanilla",
            version="1.21.6",
            reason="network",
            retry_hint="Check internet connectivity",
        )

    @app.get("/raise-server-no-port-available")
    def _server_no_port_available():
        raise NoAvailablePortError(start_port=25565)

    @app.get("/raise-legacy-not-found")
    def _legacy_nf():
        raise LegacyServerNotFoundException("42")

    @app.get("/raise-legacy-conflict")
    def _legacy_conflict():
        raise ConflictException("clash")

    @app.get("/raise-http-exception")
    def _http():
        raise HTTPException(status_code=418, detail="teapot")

    @app.get("/raise-unhandled")
    def _unhandled():
        raise RuntimeError("boom")

    @app.post("/validate")
    def _validate(body: _ValidationBody):
        return {"ok": True}

    return app


def _client() -> TestClient:
    return TestClient(_build_app())


class TestDomainExceptionHandlers:
    def test_server_not_found(self):
        c = _client()
        r = c.get("/raise-server-not-found")
        assert r.status_code == 404
        body = r.json()
        assert body["error"] == "SERVER_NOT_FOUND"
        assert body["status_code"] == 404
        assert body["message"] == "nope"
        # Legacy mirror retained for backward compatibility.
        assert body["detail"] == "nope"
        assert "timestamp" in body and body["timestamp"]
        # request_id was generated by the audit middleware
        assert body["request_id"]
        # Response header also carries the request ID
        assert r.headers.get("X-Request-ID") == body["request_id"]

    def test_server_access_denied(self):
        r = _client().get("/raise-server-access")
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "SERVER_ACCESS_DENIED"
        assert body["detail"] == "forbidden"

    def test_group_not_found(self):
        r = _client().get("/raise-group-not-found")
        assert r.status_code == 404
        body = r.json()
        assert body["error"] == "GROUP_NOT_FOUND"

    def test_group_access_denied(self):
        r = _client().get("/raise-group-access")
        assert r.status_code == 403
        assert r.json()["error"] == "GROUP_ACCESS_DENIED"

    def test_group_already_exists(self):
        r = _client().get("/raise-group-exists")
        assert r.status_code == 400
        assert r.json()["error"] == "GROUP_ALREADY_EXISTS"

    def test_template_not_found(self):
        r = _client().get("/raise-template-not-found")
        assert r.status_code == 404
        assert r.json()["error"] == "TEMPLATE_NOT_FOUND"


class TestServerCreationActionableErrors:
    """Verify Issue #33 server-creation exceptions surface ``extra_details``."""

    def test_server_name_conflict_returns_409_with_field_detail(self):
        r = _client().get("/raise-server-name-conflict")
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == "SERVER_NAME_CONFLICT"
        details = body.get("details") or []
        # The name field detail comes from ``ServerNameConflictError.extra_details``.
        assert any(
            d.get("field") == "name" and d.get("code") == "SERVER_NAME_TAKEN"
            for d in details
        )

    def test_server_port_conflict_returns_409_with_suggestions(self):
        r = _client().get("/raise-server-port-conflict")
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == "SERVER_PORT_CONFLICT"
        details = body.get("details") or []
        # First entry pinpoints the conflicting port.
        assert any(
            d.get("field") == "port" and d.get("code") == "PORT_IN_USE" for d in details
        )
        # Suggested ports are appended with the ``PORT_SUGGESTION`` code.
        suggestion_messages = [
            d.get("message") for d in details if d.get("code") == "PORT_SUGGESTION"
        ]
        assert suggestion_messages == ["25566", "25567", "25568"]

    def test_server_unsupported_version_returns_400(self):
        r = _client().get("/raise-server-unsupported-version")
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "SERVER_UNSUPPORTED_VERSION"
        details = body.get("details") or []
        assert any(d.get("code") == "VERSION_NOT_SUPPORTED" for d in details)
        assert any(d.get("code") == "RESOLUTION_STEP" for d in details)

    def test_server_java_incompatible_returns_400_with_available_versions(self):
        r = _client().get("/raise-server-java-incompatible")
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "SERVER_JAVA_INCOMPATIBLE"
        details = body.get("details") or []
        assert any(d.get("code") == "JAVA_REQUIRED" for d in details)
        # Available Java versions encoded as ``JAVA_AVAILABLE`` rows.
        available = [
            d.get("message") for d in details if d.get("code") == "JAVA_AVAILABLE"
        ]
        assert "17" in available

    def test_server_no_port_available_returns_409_with_resolution_hint(self):
        """Issue #32: ``NoAvailablePortError`` surfaces as 409 with structured details."""
        r = _client().get("/raise-server-no-port-available")
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == "SERVER_NO_PORT_AVAILABLE"
        details = body.get("details") or []
        # First detail pinpoints the exhausted range; second carries the
        # resolution hint (stop a server or widen the range).
        assert any(
            d.get("field") == "port" and d.get("code") == "NO_AVAILABLE_PORT"
            for d in details
        )
        assert any(d.get("code") == "RESOLUTION_STEP" for d in details)

    def test_server_jar_download_failed_returns_502_with_retry_hint(self):
        r = _client().get("/raise-server-jar-download-failed")
        assert r.status_code == 502
        body = r.json()
        assert body["error"] == "SERVER_JAR_DOWNLOAD_FAILED"
        details = body.get("details") or []
        # The structured reason + retry hint travel through ``details``.
        assert any(d.get("code") == "JAR_DOWNLOAD_REASON" for d in details)
        assert any(
            d.get("code") == "RESOLUTION_STEP"
            and "internet connectivity" in (d.get("message") or "")
            for d in details
        )


class TestLegacyAPIExceptionHandler:
    def test_legacy_not_found_emits_structured_envelope(self):
        r = _client().get("/raise-legacy-not-found")
        assert r.status_code == 404
        body = r.json()
        # Legacy APIException subclass carries error_code via ClassVar.
        assert body["error"] == "SERVER_NOT_FOUND"
        assert "Server with ID 42 not found" in body["detail"]
        assert body["detail"] == body["message"]

    def test_legacy_conflict(self):
        r = _client().get("/raise-legacy-conflict")
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == "RESOURCE_CONFLICT"
        assert body["detail"] == "clash"


class TestValidationErrorHandler:
    def test_field_errors_present_in_details(self):
        c = _client()
        # ``count`` wrong type and ``extra_unused`` ignored.
        # Provide both keys so Pydantic produces a per-field error
        # rather than a single "body required" entry.
        r = c.post("/validate", json={"name": "ok", "count": "not-a-number"})
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "VALIDATION_ERROR"
        assert body["status_code"] == 422
        details = body.get("details") or []
        assert len(details) >= 1
        fields = {d.get("field") for d in details}
        assert "count" in fields
        for d in details:
            assert isinstance(d.get("message"), str) and d["message"]

    def test_missing_body_yields_validation_error(self):
        c = _client()
        # Empty body — single error pointing at body
        r = c.post("/validate", json={})
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "VALIDATION_ERROR"
        details = body.get("details") or []
        assert len(details) >= 1
        # Each detail still carries a message + code
        for d in details:
            assert d.get("message")

    def test_legacy_detail_remains_list_of_dicts_for_422(self):
        """422 ``detail`` must stay in FastAPI's legacy ``list[dict]`` shape.

        Existing frontend code iterates over ``response.detail`` (e.g.
        ``response.detail.map(err => err.msg)``); mirroring ``message``
        (a string) into ``detail`` like every other status would break
        those callers. Guard against the regression.
        """
        c = _client()
        r = c.post("/validate", json={"name": "ok", "count": "not-a-number"})
        assert r.status_code == 422
        body = r.json()

        # detail is a list of dicts (legacy FastAPI format) — NOT a string.
        legacy_detail = body.get("detail")
        assert isinstance(legacy_detail, list), (
            f"422 detail must be list[dict] for back-compat, got {type(legacy_detail)}"
        )
        assert len(legacy_detail) >= 1
        for entry in legacy_detail:
            assert isinstance(entry, dict)
            # Each legacy entry carries the FastAPI default keys.
            assert "loc" in entry
            assert "msg" in entry
            assert "type" in entry
            # ``loc`` is a list (JSON has no tuples) starting with the scope.
            assert isinstance(entry["loc"], list)

        # The new structured ``details`` field is populated in parallel.
        new_details = body.get("details") or []
        assert len(new_details) >= 1
        new_fields = {d.get("field") for d in new_details}
        assert "count" in new_fields

    def test_422_detail_matches_fastapi_default_shape(self):
        """422 ``detail`` entries should round-trip FastAPI's error dicts.

        Smoke check: confirm the ``loc`` list and ``msg`` value for the
        offending field match what FastAPI's default handler would have
        produced (modulo stringification of indices).
        """
        c = _client()
        r = c.post("/validate", json={"name": "ok"})  # ``count`` missing
        assert r.status_code == 422
        legacy_detail = r.json()["detail"]
        assert isinstance(legacy_detail, list)
        # Locate the missing-``count`` entry.
        count_entry = next(
            (e for e in legacy_detail if e.get("loc", [])[-1] == "count"),
            None,
        )
        assert count_entry is not None
        assert count_entry["loc"][0] == "body"
        assert "count" in count_entry["loc"]
        assert isinstance(count_entry["msg"], str) and count_entry["msg"]
        assert isinstance(count_entry["type"], str)


class TestHTTPExceptionFallback:
    def test_unknown_http_exception(self):
        r = _client().get("/raise-http-exception")
        assert r.status_code == 418
        body = r.json()
        assert body["error"] == "HTTP_418"
        assert body["detail"] == "teapot"
        assert body["message"] == "teapot"


class TestUnhandledExceptionFallback:
    def test_500_uses_internal_error_code(self):
        # Disable raise_server_exceptions so TestClient returns the
        # exception handler's 500 response rather than re-raising.
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/raise-unhandled")
        assert r.status_code == 500
        body = r.json()
        assert body["error"] == "INTERNAL_ERROR"
        assert body["message"] == "An internal server error occurred"
        assert body["detail"] == body["message"]


class TestRequestIDPropagation:
    def test_inbound_request_id_header_is_honored(self):
        r = _client().get(
            "/raise-server-not-found",
            headers={"X-Request-ID": "my-trace-1234"},
        )
        assert r.status_code == 404
        body = r.json()
        assert body["request_id"] == "my-trace-1234"
        assert r.headers.get("X-Request-ID") == "my-trace-1234"

    def test_blank_request_id_header_falls_back_to_uuid(self):
        r = _client().get(
            "/raise-server-not-found",
            headers={"X-Request-ID": "   "},
        )
        body = r.json()
        # UUID4 is 36 chars
        assert body["request_id"] and body["request_id"] != "   "
        assert len(body["request_id"]) == 36

    def test_oversized_request_id_header_is_rejected(self):
        long_id = "x" * 200
        r = _client().get(
            "/raise-server-not-found",
            headers={"X-Request-ID": long_id},
        )
        body = r.json()
        assert body["request_id"] != long_id
        assert len(body["request_id"]) == 36
