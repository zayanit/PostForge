from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.models.brand import Brand, BrandCreate
from backend.app.routes.brands import get_brand_store
from backend.app.services.brand_store import BrandNameTakenError


@dataclass
class FakeBrandStore:
    names: set[str] = field(default_factory=set)
    brands: list[Brand] = field(default_factory=list)

    def create_brand(self, user_id: str, payload: BrandCreate) -> Brand:
        normalized_name = payload.name.casefold()
        if normalized_name in self.names:
            raise BrandNameTakenError

        self.names.add(normalized_name)
        brand = Brand(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            name=payload.name,
            logo_url=None,
            created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
        self.brands.insert(0, brand)
        return brand

    def list_brands(self, user_id: str) -> list[Brand]:
        return self.brands

    def get_brand(self, user_id: str, brand_id: UUID) -> Brand:
        for brand in self.brands:
            if brand.id == brand_id:
                return brand
        raise LookupError("Brand not found.")


@pytest.mark.parametrize("name", ["", " ", "A", "A" * 121])
def test_create_brand_rejects_invalid_names(name: str):
    store = FakeBrandStore()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/brands", json={"name": name})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.json()["error"]["request_id"]
        assert store.names == set()
    finally:
        app.dependency_overrides.clear()


def test_create_brand_rejects_case_and_whitespace_insensitive_duplicate():
    store = FakeBrandStore()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store

    try:
        with TestClient(app) as client:
            first_response = client.post("/api/v1/brands", json={"name": "Acme Coffee"})
            duplicate_response = client.post("/api/v1/brands", json={"name": "  acme coffee  "})

        assert first_response.status_code == 201
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"]["code"] == "BRAND_NAME_TAKEN"
        assert duplicate_response.json()["error"]["request_id"]
        assert store.names == {"acme coffee"}
    finally:
        app.dependency_overrides.clear()


def test_create_brand_returns_public_contract_shape():
    store = FakeBrandStore()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/brands", json={"name": "  Acme Coffee  "})

        assert response.status_code == 201
        assert response.json() == {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Acme Coffee",
            "logo_url": None,
            "created_at": "2026-07-25T00:00:00Z",
        }
    finally:
        app.dependency_overrides.clear()


def test_list_brands_returns_empty_and_populated_contract_shapes():
    store = FakeBrandStore()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store

    try:
        with TestClient(app) as client:
            empty_response = client.get("/api/v1/brands")

            store.brands = [
                Brand(
                    id=UUID("33333333-3333-3333-3333-333333333333"),
                    name="New Brand",
                    logo_url=None,
                    created_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
                ),
                Brand(
                    id=UUID("22222222-2222-2222-2222-222222222222"),
                    name="First Brand",
                    logo_url=None,
                    created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                ),
            ]
            populated_response = client.get("/api/v1/brands")

        assert empty_response.status_code == 200
        assert empty_response.json() == {"brands": []}
        assert populated_response.status_code == 200
        assert populated_response.json() == {
            "brands": [
                {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "name": "New Brand",
                    "logo_url": None,
                    "created_at": "2026-07-26T00:00:00Z",
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "name": "First Brand",
                    "logo_url": None,
                    "created_at": "2026-07-25T00:00:00Z",
                },
            ]
        }
    finally:
        app.dependency_overrides.clear()


def test_get_brand_returns_owned_brand_and_opaque_not_found_errors():
    owned_brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    store = FakeBrandStore(brands=[owned_brand])
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store

    try:
        with TestClient(app) as client:
            owned_response = client.get(f"/api/v1/brands/{owned_brand.id}")
            non_owned_response = client.get(
                "/api/v1/brands/33333333-3333-3333-3333-333333333333"
            )
            nonexistent_response = client.get(
                "/api/v1/brands/44444444-4444-4444-4444-444444444444"
            )

        assert owned_response.status_code == 200
        assert owned_response.json()["id"] == str(owned_brand.id)
        assert non_owned_response.status_code == 404
        assert nonexistent_response.status_code == 404

        non_owned_error = non_owned_response.json()["error"]
        nonexistent_error = nonexistent_response.json()["error"]
        assert non_owned_error["code"] == nonexistent_error["code"] == "BRAND_NOT_FOUND"
        assert non_owned_error["message"] == nonexistent_error["message"] == "Brand not found."
        assert set(non_owned_error) == set(nonexistent_error) == {
            "code",
            "message",
            "request_id",
        }
    finally:
        app.dependency_overrides.clear()
