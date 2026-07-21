from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.models.profile import Profile, ProfileUpdate
from backend.app.routes.me import get_profile_store


@dataclass
class FakeProfileStore:
    profile: Profile

    def get_profile(self, user_id: str, email: str) -> Profile:
        assert str(self.profile.user_id) == user_id
        return self.profile

    def update_profile(self, user_id: str, email: str, payload: ProfileUpdate) -> Profile:
        data = payload.model_dump(exclude_unset=True)
        if "full_name" in data:
            self.profile = self.profile.model_copy(update={"full_name": data["full_name"]})
        if "avatar_url" in data:
            self.profile = self.profile.model_copy(update={"avatar_url": data["avatar_url"]})
        return self.profile


def test_me_get_and_patch_keep_previous_values_on_validation_error():
    profile = Profile(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        email="jane@example.com",
        full_name="Jane Doe",
        avatar_url="https://example.com/avatar.png",
        created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    store = FakeProfileStore(profile=profile)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=str(profile.user_id),
        email=profile.email,
        access_token="eyJ...",
    )
    app.dependency_overrides[get_profile_store] = lambda: store

    try:
        with TestClient(app) as client:
            get_response = client.get("/api/v1/me")
            assert get_response.status_code == 200
            assert get_response.json()["full_name"] == "Jane Doe"

            patch_response = client.patch("/api/v1/me", json={"full_name": " "})
            assert patch_response.status_code == 400
            assert patch_response.json()["error"]["code"] == "VALIDATION_ERROR"

            avatar_response = client.patch("/api/v1/me", json={"avatar_url": "https://"})
            assert avatar_response.status_code == 400
            assert avatar_response.json()["error"]["code"] == "VALIDATION_ERROR"

            reread_response = client.get("/api/v1/me")
            assert reread_response.status_code == 200
            assert reread_response.json()["full_name"] == "Jane Doe"
            assert reread_response.json()["avatar_url"] == "https://example.com/avatar.png"
    finally:
        app.dependency_overrides.clear()
