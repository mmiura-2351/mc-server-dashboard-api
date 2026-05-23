"""Generic pagination primitives shared by API endpoints (Issue #76).

Backwards-compatibility note: existing list endpoints continue to expose
their legacy keys (``servers``, ``backups``, ``templates`` …) alongside
the new ``pagination`` block. New endpoints should adopt
:class:`PaginatedResponse` directly.

The contract: ``page`` is 1-based, ``size`` defaults to 50 with an
upper bound of 100. ``size`` is the API-facing name; internal code may
freely use ``page_size`` so long as the wire surface keeps ``size``
(accepting both via Query ``alias`` where the legacy name leaked).
"""

from __future__ import annotations

from typing import Generic, List, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PaginationParams",
    "PaginationMeta",
    "PaginatedResponse",
    "build_pagination_meta",
    "pagination_params",
]


T = TypeVar("T")


class PaginationParams(BaseModel):
    """Validated page / size pair (1-based, max 100)."""

    page: int = Field(1, ge=1, description="1-based page number")
    size: int = Field(50, ge=1, le=100, description="Items per page (max 100)")


class PaginationMeta(BaseModel):
    """Metadata block embedded in paginated responses."""

    total: int = Field(..., ge=0, description="Total number of matching items")
    page: int = Field(..., ge=1, description="Current 1-based page")
    size: int = Field(..., ge=1, description="Page size used to slice the result set")
    total_pages: int = Field(
        ..., ge=0, description="Total number of pages (0 when empty)"
    )
    has_next: bool = Field(..., description="Whether a subsequent page exists")
    has_prev: bool = Field(..., description="Whether a previous page exists")


class PaginatedResponse(BaseModel, Generic[T]):
    """Canonical generic paginated payload (``items`` + ``pagination``)."""

    items: List[T]
    pagination: PaginationMeta

    model_config = ConfigDict(arbitrary_types_allowed=True)


def build_pagination_meta(total: int, page: int, size: int) -> PaginationMeta:
    """Compute :class:`PaginationMeta` from totals + cursor.

    Both ``page`` and ``size`` are assumed validated (``>=1``) by the
    Query dependency; this helper is forgiving and clamps degenerate
    inputs rather than raising, so it stays safe to call from response
    construction sites where surfacing a 500 would obscure the real
    error.
    """
    if size <= 0:
        size = 1
    if page <= 0:
        page = 1
    if total < 0:
        total = 0
    total_pages = (total + size - 1) // size if total > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1 and total_pages > 0
    return PaginationMeta(
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
        has_next=has_next,
        has_prev=has_prev,
    )


def pagination_params(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(50, ge=1, le=100, description="Items per page (max 100)"),
) -> PaginationParams:
    """FastAPI dependency yielding a validated :class:`PaginationParams`."""
    return PaginationParams(page=page, size=size)
