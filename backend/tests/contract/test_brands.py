from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.models.brand import Brand, BrandCreate
from backend.app.routes.brands import get_brand_storage, get_brand_store
from backend.app.services.brand_store import BrandNameTakenError


@dataclass
class FakeBrandStore:
    names: set[str] = field(default_factory=set)
    brands: list[Brand] = field(default_factory=list)
    logo_paths: dict[UUID, str | None] = field(default_factory=dict)

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

    def get_logo_path(self, user_id: str, brand_id: UUID) -> str | None:
        self.get_brand(user_id, brand_id)
        return self.logo_paths.get(brand_id)

    def update_logo_path(
        self,
        user_id: str,
        brand_id: UUID,
        logo_path: str | None,
    ) -> Brand:
        brand = self.get_brand(user_id, brand_id)
        self.logo_paths[brand_id] = logo_path
        logo_url = (
            f"https://example.supabase.co/storage/v1/object/public/brand-assets/{logo_path}"
            if logo_path
            else None
        )
        updated_brand = brand.model_copy(update={"logo_url": logo_url})
        self.brands = [updated_brand if item.id == brand_id else item for item in self.brands]
        return updated_brand


@dataclass
class FakeBrandStorage:
    uploads: list[tuple[str, bytes, str]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)

    async def upload_logo(self, path: str, data: bytes, content_type: str) -> None:
        self.uploads.append((path, data, content_type))

    async def delete_logo(self, path: str) -> None:
        self.deletes.append(path)


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


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"plain text", "text/plain"),
        (b"not actually a png", "image/png"),
    ],
)
def test_upload_logo_rejects_unsupported_or_spoofed_content(
    content: bytes,
    content_type: str,
):
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store
    app.dependency_overrides[get_brand_storage] = lambda: storage

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo", content, content_type)},
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
        assert storage.uploads == []
        assert store.logo_paths == {}
    finally:
        app.dependency_overrides.clear()


def test_upload_logo_rejects_files_over_five_megabytes():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store
    app.dependency_overrides[get_brand_storage] = lambda: storage

    try:
        oversized_png = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024)
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo.png", oversized_png, "image/png")},
            )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
        assert storage.uploads == []
        assert store.logo_paths == {}
    finally:
        app.dependency_overrides.clear()


def test_upload_logo_returns_updated_brand():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store
    app.dependency_overrides[get_brand_storage] = lambda: storage

    try:
        png = b"\x89PNG\r\n\x1a\nvalid"
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo.png", png, "image/png")},
            )

        assert response.status_code == 200
        assert response.json()["logo_url"].endswith(f"brands/{brand.id}/logo.png")
        assert storage.uploads == [
            (f"brands/{brand.id}/logo.png", png, "image/png")
        ]
        assert store.logo_paths[brand.id] == f"brands/{brand.id}/logo.png"
    finally:
        app.dependency_overrides.clear()


def test_delete_logo_without_existing_logo_is_idempotent():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store
    app.dependency_overrides[get_brand_storage] = lambda: storage

    try:
        with TestClient(app) as client:
            response = client.delete(f"/api/v1/brands/{brand.id}/logo")

        assert response.status_code == 204
        assert response.content == b""
        assert storage.deletes == []
        assert store.logo_paths.get(brand.id) is None
    finally:
        app.dependency_overrides.clear()
