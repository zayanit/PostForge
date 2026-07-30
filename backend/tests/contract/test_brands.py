from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.models.brand import Brand, BrandCreate
from backend.app.routes.brands import (
    get_brand_deletion,
    get_brand_storage,
    get_brand_store,
)
from backend.app.services.brand_deletion import (
    BrandConfirmationMismatchError,
    BrandDeletionCleanupError,
)
from backend.app.services.brand_store import (
    BrandAssetOperation,
    BrandCleanupRequiredError,
    BrandMutationInProgressError,
    BrandNameTakenError,
)


@dataclass
class FakeBrandStore:
    names: set[str] = field(default_factory=set)
    brands: list[Brand] = field(default_factory=list)
    logo_paths: dict[UUID, str | None] = field(default_factory=dict)
    owners: dict[UUID, str] = field(default_factory=dict)
    cleanup_required: set[UUID] = field(default_factory=set)
    asset_operations: set[UUID] = field(default_factory=set)
    operations: dict[UUID, BrandAssetOperation] = field(default_factory=dict)

    def create_brand(self, user_id: str, payload: BrandCreate) -> Brand:
        normalized_name = payload.name.casefold()
        if normalized_name in self.names:
            raise BrandNameTakenError

        self.names.add(normalized_name)
        brand = Brand(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            name=payload.name,
            logo_url=None,
            created_at=datetime(2026, 7, 25, tzinfo=UTC),
        )
        self.brands.insert(0, brand)
        self.owners[brand.id] = user_id
        return brand

    def list_brands(self, user_id: str) -> list[Brand]:
        return self.brands

    def get_brand(self, user_id: str, brand_id: UUID) -> Brand:
        for brand in self.brands:
            if brand.id == brand_id and self.owners.get(brand.id, user_id) == user_id:
                return brand
        raise LookupError("Brand not found.")

    def get_logo_path(self, user_id: str, brand_id: UUID) -> str | None:
        self.get_brand(user_id, brand_id)
        if brand_id in self.cleanup_required:
            raise BrandCleanupRequiredError
        return self.logo_paths.get(brand_id)

    def begin_brand_cleanup(self, user_id: str, brand_id: UUID) -> str | None:
        self.get_brand(user_id, brand_id)
        if brand_id in self.asset_operations:
            raise BrandMutationInProgressError
        self.cleanup_required.add(brand_id)
        brand = next(brand for brand in self.brands if brand.id == brand_id)
        updated_brand = brand.model_copy(update={"cleanup_state": "cleanup_required"})
        self.brands = [updated_brand if item.id == brand_id else item for item in self.brands]
        return self.logo_paths.get(brand_id)

    def _check_mutation(self, brand_id: UUID) -> None:
        if brand_id in self.cleanup_required:
            raise BrandCleanupRequiredError
        if brand_id in self.asset_operations:
            raise BrandMutationInProgressError

    def update_logo_path(
        self,
        user_id: str,
        brand_id: UUID,
        logo_path: str | None,
    ) -> Brand:
        brand = self.get_brand(user_id, brand_id)
        self._check_mutation(brand_id)
        self.logo_paths[brand_id] = logo_path
        logo_url = (
            f"https://example.supabase.co/storage/v1/object/public/brand-assets/{logo_path}"
            if logo_path
            else None
        )
        updated_brand = brand.model_copy(update={"logo_url": logo_url})
        self.brands = [updated_brand if item.id == brand_id else item for item in self.brands]
        return updated_brand

    def begin_logo_upload(
        self, user_id: str, brand_id: UUID, extension: str
    ) -> BrandAssetOperation:
        brand = self.get_brand(user_id, brand_id)
        self._check_mutation(brand_id)
        operation_id = uuid4()
        operation = BrandAssetOperation(
            id=operation_id,
            brand_id=brand_id,
            operation="upload",
            object_path=f"brands/{brand_id}/logos/{operation_id}.{extension}",
            previous_path=self.logo_paths.get(brand_id),
            state="in_progress",
            remote_status="pending",
        )
        self.asset_operations.add(brand_id)
        self.operations[operation_id] = operation
        return operation

    def get_asset_operation(
        self, user_id: str, brand_id: UUID
    ) -> BrandAssetOperation | None:
        self.get_brand(user_id, brand_id)
        return next(
            (
                operation
                for operation in self.operations.values()
                if operation.brand_id == brand_id
            ),
            None,
        )

    def begin_logo_remove(
        self, user_id: str, brand_id: UUID
    ) -> BrandAssetOperation | None:
        self.get_brand(user_id, brand_id)
        self._check_mutation(brand_id)
        path = self.logo_paths.get(brand_id)
        if path is None:
            return None
        operation_id = uuid4()
        operation = BrandAssetOperation(
            id=operation_id,
            brand_id=brand_id,
            operation="remove",
            object_path=path,
            previous_path=None,
            state="in_progress",
            remote_status="pending",
        )
        self.asset_operations.add(brand_id)
        self.operations[operation_id] = operation
        return operation

    def record_asset_remote_status(
        self, user_id: str, brand_id: UUID, operation_id: UUID, remote_status: str
    ) -> None:
        self.get_brand(user_id, brand_id)
        operation = self.operations[operation_id]
        self.operations[operation_id] = replace(
            operation,
            remote_status=remote_status,
            state=(
                operation.state
                if remote_status == "succeeded"
                else "cleanup_required"
            ),
        )

    def abandon_definitive_asset_failure(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> None:
        self.operations.pop(operation_id)
        self.asset_operations.discard(brand_id)

    def mark_asset_cleanup_required(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> None:
        operation = self.operations[operation_id]
        self.operations[operation_id] = replace(operation, state="cleanup_required")

    def publish_uploaded_logo(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> Brand:
        operation = self.operations[operation_id]
        self.logo_paths[brand_id] = operation.object_path
        brand = self.get_brand(user_id, brand_id)
        updated = brand.model_copy(
            update={
                "logo_url": (
                    "https://example.supabase.co/storage/v1/object/public/"
                    f"brand-assets/{operation.object_path}"
                )
            }
        )
        self.brands = [updated if item.id == brand_id else item for item in self.brands]
        return updated

    def complete_asset_operation(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> None:
        operation = self.operations.pop(operation_id)
        if operation.operation == "remove":
            self.logo_paths[brand_id] = None
        self.asset_operations.discard(brand_id)

    def delete_brand(self, user_id: str, brand_id: UUID) -> None:
        self.get_brand(user_id, brand_id)
        self._check_mutation(brand_id)
        self.brands = [brand for brand in self.brands if brand.id != brand_id]
        self.logo_paths.pop(brand_id, None)
        self.owners.pop(brand_id, None)

    def delete_brand_after_cleanup(self, user_id: str, brand_id: UUID) -> None:
        self.get_brand(user_id, brand_id)
        if brand_id in self.asset_operations:
            raise BrandMutationInProgressError
        if brand_id not in self.cleanup_required:
            raise BrandCleanupRequiredError
        self.brands = [brand for brand in self.brands if brand.id != brand_id]
        self.logo_paths.pop(brand_id, None)
        self.owners.pop(brand_id, None)

    def mark_cleanup_required(self, user_id: str, brand_id: UUID) -> Brand:
        brand = self.get_brand(user_id, brand_id)
        self.cleanup_required.add(brand_id)
        updated_brand = brand.model_copy(update={"cleanup_state": "cleanup_required"})
        self.brands = [updated_brand if item.id == brand_id else item for item in self.brands]
        return updated_brand


@dataclass
class FakeBrandStorage:
    uploads: list[tuple[str, bytes, str]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    fail_delete: bool = False

    async def upload_logo(self, path: str, data: bytes, content_type: str) -> None:
        self.uploads.append((path, data, content_type))

    async def delete_logo(self, path: str) -> None:
        self.deletes.append(path)
        if self.fail_delete:
            from backend.app.services.brand_storage import BrandStorageError

            raise BrandStorageError

    async def delete_brand_prefix(self, brand_id: UUID) -> None:
        await self.delete_logo(f"brands/{brand_id}/")

    async def brand_prefix_is_empty(self, brand_id: UUID) -> bool:
        return not self.fail_delete


@dataclass
class FakeBrandDeletion:
    store: FakeBrandStore
    storage: FakeBrandStorage

    async def delete(self, user_id: str, brand_id: UUID, confirm_name: str) -> None:
        brand = self.store.get_brand(user_id, brand_id)
        if brand.name != confirm_name:
            raise BrandConfirmationMismatchError
        if brand_id in self.store.asset_operations:
            raise BrandMutationInProgressError
        self.store.cleanup_required.add(brand_id)
        updated = brand.model_copy(update={"cleanup_state": "cleanup_required"})
        self.store.brands = [
            updated if item.id == brand_id else item for item in self.store.brands
        ]
        try:
            await self.storage.delete_brand_prefix(brand_id)
            if not await self.storage.brand_prefix_is_empty(brand_id):
                raise BrandDeletionCleanupError
        except Exception as exc:
            if isinstance(exc, BrandDeletionCleanupError):
                raise
            raise BrandDeletionCleanupError from exc
        self.store.delete_brand_after_cleanup(user_id, brand_id)


def _override_brand_dependencies(
    store: FakeBrandStore, storage: FakeBrandStorage
) -> None:
    app.dependency_overrides[get_brand_store] = lambda: store
    app.dependency_overrides[get_brand_storage] = lambda: storage
    app.dependency_overrides[get_brand_deletion] = lambda: FakeBrandDeletion(store, storage)


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
            "cleanup_state": "normal",
            "kit_status": "not_started",
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
                    kit_status="in_progress",
                    created_at=datetime(2026, 7, 26, tzinfo=UTC),
                ),
                Brand(
                    id=UUID("22222222-2222-2222-2222-222222222222"),
                    name="First Brand",
                    logo_url=None,
                    kit_status="complete",
                    created_at=datetime(2026, 7, 25, tzinfo=UTC),
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
                    "cleanup_state": "normal",
                    "kit_status": "in_progress",
                    "created_at": "2026-07-26T00:00:00Z",
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "name": "First Brand",
                    "logo_url": None,
                    "cleanup_state": "normal",
                    "kit_status": "complete",
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
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
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


def test_cleanup_required_brand_remains_visible_in_list_and_detail():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Cleanup Brand",
        logo_url=None,
        cleanup_state="cleanup_required",
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand], cleanup_required={brand.id})
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    app.dependency_overrides[get_brand_store] = lambda: store

    try:
        with TestClient(app) as client:
            list_response = client.get("/api/v1/brands")
            detail_response = client.get(f"/api/v1/brands/{brand.id}")

        assert list_response.status_code == 200
        assert list_response.json()["brands"][0]["cleanup_state"] == "cleanup_required"
        assert detail_response.status_code == 200
        assert detail_response.json()["cleanup_state"] == "cleanup_required"
        assert "deletion_state" not in detail_response.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("fence_field", "expected_code"),
    [
        ("cleanup_required", "BRAND_CLEANUP_REQUIRED"),
        ("asset_operations", "BRAND_MUTATION_IN_PROGRESS"),
    ],
)
def test_logo_and_brand_mutations_respect_brand_fences(
    fence_field: str,
    expected_code: str,
):
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand])
    getattr(store, fence_field).add(brand.id)
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        with TestClient(app) as client:
            upload_response = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo.png", b"\x89PNG\r\n\x1a\nvalid", "image/png")},
            )
            remove_response = client.delete(f"/api/v1/brands/{brand.id}/logo")
            delete_response = client.request(
                "DELETE",
                f"/api/v1/brands/{brand.id}",
                json={"confirm_name": brand.name},
            )

        for response in (upload_response, remove_response):
            assert response.status_code == 409
            assert response.json()["error"]["code"] == expected_code
        if fence_field == "cleanup_required":
            assert delete_response.status_code == 204
        else:
            assert delete_response.status_code == 409
            assert delete_response.json()["error"]["code"] == expected_code
        assert storage.uploads == []
        assert storage.deletes == (
            [f"brands/{brand.id}/"] if fence_field == "cleanup_required" else []
        )
        assert store.brands == ([] if fence_field == "cleanup_required" else [brand])
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
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

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
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

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
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        png = b"\x89PNG\r\n\x1a\nvalid"
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo.png", png, "image/png")},
            )

        assert response.status_code == 200
        logo_path = store.logo_paths[brand.id]
        assert logo_path is not None
        assert logo_path.startswith(f"brands/{brand.id}/logos/")
        assert logo_path.endswith(".png")
        assert response.json()["logo_url"].endswith(logo_path)
        assert storage.uploads == [(logo_path, png, "image/png")]
    finally:
        app.dependency_overrides.clear()


def test_delete_logo_without_existing_logo_is_idempotent():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        with TestClient(app) as client:
            response = client.delete(f"/api/v1/brands/{brand.id}/logo")

        assert response.status_code == 204
        assert response.content == b""
        assert storage.deletes == []
        assert store.logo_paths.get(brand.id) is None
    finally:
        app.dependency_overrides.clear()


def test_replacement_cleanup_failure_is_durable_and_retry_completes_it():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url="https://example.supabase.co/old.png",
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    old_path = f"brands/{brand.id}/logo.png"
    store = FakeBrandStore(brands=[brand], logo_paths={brand.id: old_path})
    storage = FakeBrandStorage(fail_delete=True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        png = b"\x89PNG\r\n\x1a\nvalid"
        with TestClient(app) as client:
            failed = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo.png", png, "image/png")},
            )
            assert failed.status_code == 502
            operation = next(iter(store.operations.values()))
            assert operation.remote_status == "succeeded"
            assert operation.state == "cleanup_required"
            assert store.logo_paths[brand.id] == operation.object_path

            storage.fail_delete = False
            retried = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={"file": ("logo.png", png, "image/png")},
            )

        assert retried.status_code == 200
        assert store.operations == {}
        assert old_path in storage.deletes
        assert operation.object_path in storage.deletes
    finally:
        app.dependency_overrides.clear()


def test_delete_brand_with_exact_confirmation_removes_brand_and_logo():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url="https://example.supabase.co/logo.png",
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    logo_path = f"brands/{brand.id}/logo.png"
    store = FakeBrandStore(brands=[brand], logo_paths={brand.id: logo_path})
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        with TestClient(app) as client:
            response = client.request(
                "DELETE",
                f"/api/v1/brands/{brand.id}",
                json={"confirm_name": brand.name},
            )

        assert response.status_code == 204
        assert response.content == b""
        assert store.brands == []
        assert storage.deletes == [f"brands/{brand.id}/"]
    finally:
        app.dependency_overrides.clear()


def test_delete_brand_storage_failure_retains_cleanup_required_brand():
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url="https://example.supabase.co/logo.png",
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    logo_path = f"brands/{brand.id}/logo.png"
    store = FakeBrandStore(brands=[brand], logo_paths={brand.id: logo_path})
    storage = FakeBrandStorage(fail_delete=True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        with TestClient(app) as client:
            response = client.request(
                "DELETE",
                f"/api/v1/brands/{brand.id}",
                json={"confirm_name": brand.name},
            )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
        assert response.json()["error"]["message"] == (
            "Brand cleanup did not complete. Retry deletion."
        )
        assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
        assert len(store.brands) == 1
        assert store.brands[0].cleanup_state == "cleanup_required"
        assert store.logo_paths[brand.id] == logo_path
        assert storage.deletes == [f"brands/{brand.id}/"]

        storage.fail_delete = False
        with TestClient(app) as client:
            retry = client.request(
                "DELETE",
                f"/api/v1/brands/{brand.id}",
                json={"confirm_name": brand.name},
            )

        assert retry.status_code == 204
        assert retry.content == b""
        assert store.brands == []
        assert storage.deletes == [f"brands/{brand.id}/", f"brands/{brand.id}/"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("payload", [{}, {"confirm_name": "acme coffee"}])
def test_delete_brand_rejects_missing_or_wrong_confirmation_without_mutation(
    payload: dict[str, str],
):
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Acme Coffee",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(brands=[brand])
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        with TestClient(app) as client:
            response = client.request(
                "DELETE",
                f"/api/v1/brands/{brand.id}",
                json=payload,
            )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFIRMATION_MISMATCH"
        assert store.brands == [brand]
        assert storage.deletes == []
    finally:
        app.dependency_overrides.clear()


def test_delete_brand_returns_opaque_not_found_for_non_owner_and_nonexistent_brand():
    owner_id = "11111111-1111-1111-1111-111111111111"
    brand = Brand(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="Another Owner Brand",
        logo_url=None,
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    store = FakeBrandStore(
        brands=[brand],
        owners={brand.id: "99999999-9999-9999-9999-999999999999"},
        cleanup_required={brand.id},
        asset_operations={brand.id},
    )
    storage = FakeBrandStorage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=owner_id,
        email="owner@example.com",
        access_token="eyJ...",
    )
    _override_brand_dependencies(store, storage)

    try:
        with TestClient(app) as client:
            non_owner_upload_response = client.post(
                f"/api/v1/brands/{brand.id}/logo",
                files={
                    "file": (
                        "logo.png",
                        b"\x89PNG\r\n\x1a\nvalid",
                        "image/png",
                    )
                },
            )
            non_owner_remove_response = client.delete(
                f"/api/v1/brands/{brand.id}/logo"
            )
            non_owner_response = client.request(
                "DELETE",
                f"/api/v1/brands/{brand.id}",
                json={"confirm_name": brand.name},
            )
            nonexistent_response = client.request(
                "DELETE",
                "/api/v1/brands/44444444-4444-4444-4444-444444444444",
                json={"confirm_name": brand.name},
            )

        assert non_owner_response.status_code == nonexistent_response.status_code == 404
        for response in (
            non_owner_upload_response,
            non_owner_remove_response,
            non_owner_response,
            nonexistent_response,
        ):
            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "BRAND_NOT_FOUND"
            assert error["message"] == "Brand not found."
        assert store.brands == [brand]
        assert storage.deletes == []
    finally:
        app.dependency_overrides.clear()
