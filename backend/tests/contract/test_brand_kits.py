from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.models.brand_kit import BrandKit, BrandKitUpsert
from backend.app.routes.brand_kits import get_brand_kit_store
from backend.app.services.brand_kit_store import derive_summary
from backend.app.services.brand_store import BrandNameTakenError


BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
OWNER_USER_ID = "11111111-1111-1111-1111-111111111111"
COMPLETE_ANSWERS = {
    "tagline": "Innovation for everyone",
    "tone": "professional",
    "audience": "Small business owners aged 25-45",
    "colors": ["#FF5733", "#3498DB"],
    "avoid_words": "cheap, discount",
}
COMPLETE_SUMMARY = "\n".join(
    (
        "Brand: My Brand",
        "Tagline: Innovation for everyone",
        "Tone: professional",
        "Audience: Small business owners aged 25-45",
        "Colors: #FF5733, #3498DB",
        "Avoid words: cheap, discount",
    )
)
COMPLETED_AT = datetime(2026, 7, 29, tzinfo=UTC)


def _kit(*, answers=None, status="not_started", summary=None) -> BrandKit:
    return BrandKit.model_validate(
        {
            "brand_id": BRAND_ID,
            "brand_name": "My Brand",
            "answers": answers or {},
            "summary": summary,
            "status": status,
            "completed_at": COMPLETED_AT if status == "complete" else None,
            "updated_at": COMPLETED_AT if status == "complete" else None,
        }
    )


@dataclass
class FakeBrandKitStore:
    kit: BrandKit | None = None
    saved_payloads: list[BrandKitUpsert] = None

    def __post_init__(self) -> None:
        if self.saved_payloads is None:
            self.saved_payloads = []

    def get_kit(self, user_id: str, brand_id: UUID) -> BrandKit:
        return self.kit or _kit()

    def upsert_kit(
        self, user_id: str, brand_id: UUID, payload: BrandKitUpsert
    ) -> BrandKit:
        self.saved_payloads.append(payload)
        self.kit = _kit(
            answers=payload.answers,
            status="complete",
            summary=derive_summary(payload.name, payload.answers),
        )
        return self.kit


class DuplicateNameStore(FakeBrandKitStore):
    def upsert_kit(
        self, user_id: str, brand_id: UUID, payload: BrandKitUpsert
    ) -> BrandKit:
        raise BrandNameTakenError


def _client(store: FakeBrandKitStore) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=OWNER_USER_ID,
        email="owner@example.com",
        access_token="redacted",
    )
    app.dependency_overrides[get_brand_kit_store] = lambda: store
    return TestClient(app)


def test_get_without_row_returns_exact_not_started_shape():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            response = client.get(f"/api/v1/brands/{BRAND_ID}/kit")

        assert response.status_code == 200
        assert response.json() == {
            "brand_id": str(BRAND_ID),
            "brand_name": "My Brand",
            "answers": {
                "tagline": None,
                "tone": None,
                "audience": None,
                "colors": [],
                "avoid_words": None,
            },
            "summary": None,
            "status": "not_started",
            "completed_at": None,
            "updated_at": None,
        }
    finally:
        app.dependency_overrides.clear()


def test_put_complete_answers_returns_exact_public_shape():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            response = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": COMPLETE_ANSWERS},
            )

        assert response.status_code == 200
        assert response.json() == {
            "brand_id": str(BRAND_ID),
            "brand_name": "My Brand",
            "answers": COMPLETE_ANSWERS,
            "summary": COMPLETE_SUMMARY,
            "status": "complete",
            "completed_at": "2026-07-29T00:00:00Z",
            "updated_at": "2026-07-29T00:00:00Z",
        }
        assert store.saved_payloads[0].name == "My Brand"
    finally:
        app.dependency_overrides.clear()


def test_put_complete_answers_allows_optional_fields_to_be_omitted():
    store = FakeBrandKitStore()
    answers = {
        "tone": "professional",
        "audience": COMPLETE_ANSWERS["audience"],
        "colors": COMPLETE_ANSWERS["colors"],
    }
    try:
        with _client(store) as client:
            response = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": answers},
            )

        assert response.status_code == 200
        assert response.json()["answers"] == {
            "tagline": None,
            "tone": "professional",
            "audience": COMPLETE_ANSWERS["audience"],
            "colors": COMPLETE_ANSWERS["colors"],
            "avoid_words": None,
        }
        assert response.json()["summary"] == "\n".join(
            (
                "Brand: My Brand",
                "Tagline: None specified",
                "Tone: professional",
                "Audience: Small business owners aged 25-45",
                "Colors: #FF5733, #3498DB",
                "Avoid words: None specified",
            )
        )
        assert response.json()["status"] == "complete"
        assert set(response.json()) == {
            "brand_id",
            "brand_name",
            "answers",
            "summary",
            "status",
            "completed_at",
            "updated_at",
        }
    finally:
        app.dependency_overrides.clear()


def test_put_maps_duplicate_brand_name_to_conflict():
    try:
        with _client(DuplicateNameStore()) as client:
            response = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "Existing Brand", "answers": COMPLETE_ANSWERS},
            )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BRAND_NAME_TAKEN"
        assert response.json()["error"]["request_id"]
    finally:
        app.dependency_overrides.clear()
