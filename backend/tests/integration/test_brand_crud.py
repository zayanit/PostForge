from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for integration tests")
    return value


def _signup_and_login(
    client: httpx.Client,
    supabase_url: str,
    supabase_key: str,
    email: str,
    password: str,
) -> tuple[str, str]:
    signup_response = client.post(
        f"{supabase_url}/auth/v1/signup",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    assert signup_response.status_code in {200, 201}
    user_id = signup_response.json()["user"]["id"]

    token_response = client.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    assert token_response.status_code == 200
    return user_id, token_response.json()["access_token"]


def test_create_brand_against_real_supabase():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.main import app

    email = f"brand-create-{uuid4().hex[:12]}@example.com"
    password = "12345678"
    user_id: str | None = None

    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                email,
                password,
            )
            headers = {"Authorization": f"Bearer {access_token}"}

            with TestClient(app) as api_client:
                create_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "  Acme Coffee  "},
                )
                duplicate_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "acme coffee"},
                )
                empty_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": " "},
                )
                long_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "A" * 121},
                )

            assert create_response.status_code == 201
            assert create_response.json()["name"] == "Acme Coffee"
            assert create_response.json()["logo_url"] is None
            assert duplicate_response.status_code == 409
            assert duplicate_response.json()["error"]["code"] == "BRAND_NAME_TAKEN"
            assert empty_response.status_code == 400
            assert empty_response.json()["error"]["code"] == "VALIDATION_ERROR"
            assert long_response.status_code == 400
            assert long_response.json()["error"]["code"] == "VALIDATION_ERROR"

            persisted_response = supabase_client.get(
                f"{supabase_url}/rest/v1/brands",
                params={"select": "owner_user_id,name", "owner_user_id": f"eq.{user_id}"},
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                },
            )
            assert persisted_response.status_code == 200
            assert persisted_response.json() == [
                {"owner_user_id": user_id, "name": "Acme Coffee"}
            ]
        finally:
            if user_id:
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )
