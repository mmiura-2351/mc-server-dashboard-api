"""Tests for :mod:`app.core.pagination` (Issue #76)."""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.pagination import (
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    build_pagination_meta,
    pagination_params,
)


class _Item(BaseModel):
    id: int
    name: str


class TestBuildPaginationMeta:
    def test_first_page_has_no_prev(self):
        meta = build_pagination_meta(total=25, page=1, size=10)
        assert meta.total == 25
        assert meta.page == 1
        assert meta.size == 10
        assert meta.total_pages == 3
        assert meta.has_next is True
        assert meta.has_prev is False

    def test_middle_page(self):
        meta = build_pagination_meta(total=25, page=2, size=10)
        assert meta.has_next is True
        assert meta.has_prev is True

    def test_last_page_has_no_next(self):
        meta = build_pagination_meta(total=25, page=3, size=10)
        assert meta.total_pages == 3
        assert meta.has_next is False
        assert meta.has_prev is True

    def test_empty_total_zero_pages(self):
        meta = build_pagination_meta(total=0, page=1, size=10)
        assert meta.total_pages == 0
        assert meta.has_next is False
        # ``has_prev`` is False on an empty result even when page > 1
        # would normally be "prev" — keep the empty-collection invariant
        # consistent.
        assert meta.has_prev is False

    def test_exact_multiple(self):
        meta = build_pagination_meta(total=20, page=2, size=10)
        assert meta.total_pages == 2
        assert meta.has_next is False
        assert meta.has_prev is True

    def test_single_page(self):
        meta = build_pagination_meta(total=5, page=1, size=10)
        assert meta.total_pages == 1
        assert meta.has_next is False
        assert meta.has_prev is False

    def test_degenerate_inputs_clamped(self):
        # Defensive: function tolerates 0/negative values rather than
        # bubbling a 500 to the caller.
        meta = build_pagination_meta(total=-3, page=0, size=0)
        assert meta.total == 0
        assert meta.page == 1
        assert meta.size == 1
        assert meta.total_pages == 0


class TestPaginationParams:
    def test_defaults(self):
        params = PaginationParams()
        assert params.page == 1
        assert params.size == 50

    def test_validation_rejects_below_min(self):
        with pytest.raises(ValueError):
            PaginationParams(page=0, size=10)
        with pytest.raises(ValueError):
            PaginationParams(page=1, size=0)

    def test_validation_rejects_above_max(self):
        with pytest.raises(ValueError):
            PaginationParams(page=1, size=101)


class TestPaginationParamsDependency:
    def test_dependency_yields_validated_object(self):
        app = FastAPI()

        @app.get("/list")
        def _list(
            params: PaginationParams = Depends(pagination_params),
        ) -> Dict[str, Any]:
            return {"page": params.page, "size": params.size}

        client = TestClient(app)
        # Defaults
        r = client.get("/list")
        assert r.status_code == 200
        assert r.json() == {"page": 1, "size": 50}
        # Explicit values
        r = client.get("/list?page=3&size=20")
        assert r.status_code == 200
        assert r.json() == {"page": 3, "size": 20}
        # Out-of-range page → 422 from FastAPI Query validation
        r = client.get("/list?page=0")
        assert r.status_code == 422
        # Out-of-range size → 422
        r = client.get("/list?size=500")
        assert r.status_code == 422


class TestPaginatedResponseGeneric:
    def test_generic_serialises_items(self):
        items = [_Item(id=1, name="a"), _Item(id=2, name="b")]
        resp = PaginatedResponse[_Item](
            items=items,
            pagination=build_pagination_meta(total=2, page=1, size=10),
        )
        payload = resp.model_dump()
        assert [i["id"] for i in payload["items"]] == [1, 2]
        assert payload["pagination"]["total"] == 2
        assert payload["pagination"]["has_next"] is False

    def test_pagination_meta_round_trip(self):
        meta = PaginationMeta(
            total=12,
            page=2,
            size=5,
            total_pages=3,
            has_next=True,
            has_prev=True,
        )
        round_tripped = PaginationMeta.model_validate(meta.model_dump())
        assert round_tripped == meta
