from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
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
        current = self.kit.answers if self.kit else BrandKitUpsert.model_validate(
            {"name": payload.name}
        ).answers
        answers = current.model_copy(
            update=payload.answers.model_dump(exclude_unset=True)
        )
        is_complete = (
            answers.tone is not None
            and answers.audience is not None
            and bool(answers.colors)
        )
        kit_status = "complete" if is_complete else (
            "in_progress"
            if any((answers.tagline, answers.tone, answers.audience, answers.colors, answers.avoid_words))
            else "not_started"
        )
        self.kit = _kit(
            answers=answers,
            status=kit_status,
            summary=derive_summary(payload.name, answers) if is_complete else None,
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


def test_put_zero_answers_returns_not_started_without_derived_fields():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            response = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": {}},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "not_started"
        assert response.json()["summary"] is None
        assert response.json()["completed_at"] is None
    finally:
        app.dependency_overrides.clear()


def test_answer_save_transitions_to_in_progress_and_preserves_omitted_values():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            first = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": {"tagline": "Hello"}},
            )
            second = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": {"tone": "friendly"}},
            )

        assert first.json()["status"] == "in_progress"
        assert second.json()["answers"]["tagline"] == "Hello"
        assert second.json()["answers"]["tone"] == "friendly"
    finally:
        app.dependency_overrides.clear()


def test_explicit_empty_values_clear_answers_and_derived_fields():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            complete = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": COMPLETE_ANSWERS},
            )
            cleared = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={
                    "name": "My Brand",
                    "answers": {"tone": None, "colors": []},
                },
            )

        assert complete.json()["status"] == "complete"
        assert cleared.json()["status"] == "in_progress"
        assert cleared.json()["answers"]["tone"] is None
        assert cleared.json()["answers"]["colors"] == []
        assert cleared.json()["summary"] is None
        assert cleared.json()["completed_at"] is None
    finally:
        app.dependency_overrides.clear()


def test_invalid_completion_is_rejected_without_replacing_saved_response():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            saved = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "My Brand", "answers": {"tagline": "Keep me"}},
            )
            invalid = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={
                    "name": "My Brand",
                    "answers": {"colors": ["not-a-color"]},
                },
            )

        assert saved.status_code == 200
        assert invalid.status_code == 400
        assert store.saved_payloads[-1].answers.tagline == "Keep me"
    finally:
        app.dependency_overrides.clear()


def test_repeated_puts_keep_a_single_logical_kit_payload():
    store = FakeBrandKitStore()
    try:
        with _client(store) as client:
            for _ in range(2):
                response = client.put(
                    f"/api/v1/brands/{BRAND_ID}/kit",
                    json={"name": "My Brand", "answers": {"tagline": "Hello"}},
                )
                assert response.status_code == 200

        assert len(store.saved_payloads) == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("authorization", [None, "Basic malformed", "Bearer "])
def test_kit_requires_a_valid_authorization_header(authorization: str | None):
    headers = {} if authorization is None else {"Authorization": authorization}
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/brands/{BRAND_ID}/kit", headers=headers)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        assert response.json()["error"]["message"] == "Sign in required."
        assert set(response.json()["error"]) == {"code", "message", "request_id"}
    finally:
        app.dependency_overrides.clear()


def test_kit_store_errors_are_opaque_for_non_owner_and_missing_brands():
    class UnauthorizedStore(FakeBrandKitStore):
        def get_kit(self, user_id: str, brand_id: UUID) -> BrandKit:
            raise LookupError("Brand not found.")

        def upsert_kit(
            self, user_id: str, brand_id: UUID, payload: BrandKitUpsert
        ) -> BrandKit:
            raise LookupError("Brand not found.")

    try:
        with _client(UnauthorizedStore()) as client:
            get_response = client.get(f"/api/v1/brands/{BRAND_ID}/kit")
            put_response = client.put(
                f"/api/v1/brands/{BRAND_ID}/kit",
                json={"name": "Private Brand", "answers": {}},
            )

        for response in (get_response, put_response):
            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "BRAND_NOT_FOUND"
            assert error["message"] == "Brand not found."
            assert "Private Brand" not in response.text
    finally:
        app.dependency_overrides.clear()
