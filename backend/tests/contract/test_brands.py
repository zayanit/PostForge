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

    def create_brand(self, user_id: str, payload: BrandCreate) -> Brand:
        normalized_name = payload.name.casefold()
        if normalized_name in self.names:
            raise BrandNameTakenError

        self.names.add(normalized_name)
        return Brand(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            name=payload.name,
            logo_url=None,
            created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        )


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
