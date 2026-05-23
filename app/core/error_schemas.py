"""Standardised error payload shapes (Issue #76 — Phase 1).

The project keeps the legacy ``{"detail": "..."}`` shape so existing
frontend code does not break; this module **adds** structured fields
(``error`` code, ``message``, ``status_code``, ``details``,
``request_id``, ``timestamp``) alongside ``detail`` rather than
replacing it. New consumers should read ``error`` as the machine
identifier and treat ``detail`` as deprecated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ErrorDetail", "ErrorResponse"]


class ErrorDetail(BaseModel):
    """A single field-level error inside an :class:`ErrorResponse`.

    Returned in the ``details`` list for validation failures (422)
    where multiple fields may be invalid simultaneously.
    """

    field: Optional[str] = Field(None, description="Dotted path to the offending field")
    message: str = Field(..., description="Human-readable description")
    code: Optional[str] = Field(
        None, description="Machine-readable code (e.g. ``value_error.missing``)"
    )


class ErrorResponse(BaseModel):
    """Standard error payload.

    The shape is intentionally additive over the legacy
    ``{"detail": "..."}`` response. ``error`` is the canonical
    machine-readable identifier (``SCREAMING_SNAKE_CASE`` domain code);
    ``detail`` is preserved to keep older callers working.
    """

    error: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable message")
    status_code: int = Field(..., description="HTTP status code")
    details: Optional[List[ErrorDetail]] = Field(
        None, description="Field-level errors (typically 422)"
    )
    request_id: Optional[str] = Field(
        None, description="Correlation ID for log triangulation"
    )
    timestamp: datetime = Field(..., description="Server time at response generation")
    detail: Optional[Union[str, List[Dict[str, Any]]]] = Field(
        None,
        description=(
            "Legacy ``detail`` field. For most errors this mirrors "
            "``message`` (string). For 422 ``RequestValidationError`` "
            "responses this is the legacy FastAPI ``list[dict]`` shape "
            "so existing clients that iterate over per-field errors "
            "(e.g. ``response.detail.map(...)``) keep working unchanged."
        ),
    )

    model_config = ConfigDict()
