import os
import uuid

import httpx
import pytest


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for integration tests")
    return value


def test_signup_creates_profile_row_and_enforces_password_floor():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_secret_key = _required_env("SUPABASE_SECRET_KEY")

    email = f"phase3-{uuid.uuid4().hex[:12]}@example.com"
    short_password = "1234567"
    valid_password = "12345678"

    user_id: str | None = None

    with httpx.Client(timeout=30.0) as client:
        try:
            short_response = client.post(
                f"{supabase_url}/auth/v1/signup",
                headers={"apikey": supabase_secret_key, "Content-Type": "application/json"},
                json={"email": email, "password": short_password},
            )

            assert short_response.status_code == 422
            assert short_response.json().get("error_code") == "weak_password"

            valid_response = client.post(
                f"{supabase_url}/auth/v1/signup",
                headers={"apikey": supabase_secret_key, "Content-Type": "application/json"},
                json={"email": email, "password": valid_password},
            )

            assert valid_response.status_code in {200, 201}
            payload = valid_response.json()
            user_id = payload.get("user", {}).get("id")
            assert user_id

            duplicate_response = client.post(
                f"{supabase_url}/auth/v1/signup",
                headers={"apikey": supabase_secret_key, "Content-Type": "application/json"},
                json={"email": email, "password": valid_password},
            )

            assert duplicate_response.status_code >= 400

            profile_response = client.get(
                f"{supabase_url}/rest/v1/profiles",
                params={"select": "user_id,full_name,avatar_url", "user_id": f"eq.{user_id}"},
                headers={
                    "apikey": supabase_secret_key,
                    "Authorization": f"Bearer {supabase_secret_key}",
                },
            )

            assert profile_response.status_code == 200
            profiles = profile_response.json()
            assert profiles
            profile = profiles[0]

            assert profile["user_id"] == user_id
            assert profile["full_name"] is None
            assert profile["avatar_url"] is None
        finally:
            # Delete the test user (and its cascaded profile row) via the
            # GoTrue admin API so repeated runs don't accumulate stray users.
            if user_id:
                client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_secret_key,
                        "Authorization": f"Bearer {supabase_secret_key}",
                    },
                )
