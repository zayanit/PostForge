from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for integration tests")
    return value


def _signup_and_login(client: httpx.Client, supabase_url: str, supabase_key: str, email: str, password: str):
    signup_response = client.post(
        f"{supabase_url}/auth/v1/signup",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    assert signup_response.status_code in {200, 201}
    signup_payload = signup_response.json()
    user_id = signup_payload["user"]["id"]

    token_response = client.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": supabase_key, "Content-Type": "application/x-www-form-urlencoded"},
        data={"email": email, "password": password},
    )
    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]

    return user_id, access_token


def test_profiles_row_level_security_blocks_cross_user_access():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")

    email_a = f"rls-a-{uuid4().hex[:10]}@example.com"
    email_b = f"rls-b-{uuid4().hex[:10]}@example.com"
    password = "12345678"

    with httpx.Client(timeout=30.0) as client:
        user_a_id, token_a = _signup_and_login(client, supabase_url, supabase_key, email_a, password)
        _user_b_id, token_b = _signup_and_login(client, supabase_url, supabase_key, email_b, password)

        own_read = client.get(
            f"{supabase_url}/rest/v1/profiles",
            params={"select": "user_id,full_name,avatar_url", "user_id": f"eq.{user_a_id}"},
            headers={"apikey": supabase_key, "Authorization": f"Bearer {token_a}"},
        )
        assert own_read.status_code == 200
        own_rows = own_read.json()
        assert len(own_rows) == 1
        assert own_rows[0]["user_id"] == user_a_id

        cross_read = client.get(
            f"{supabase_url}/rest/v1/profiles",
            params={"select": "user_id,full_name,avatar_url", "user_id": f"eq.{user_a_id}"},
            headers={"apikey": supabase_key, "Authorization": f"Bearer {token_b}"},
        )
        assert cross_read.status_code == 200
        assert cross_read.json() == []

        cross_write = client.patch(
            f"{supabase_url}/rest/v1/profiles",
            params={"user_id": f"eq.{user_a_id}"},
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {token_b}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json={"full_name": "Hacked Name"},
        )
        assert cross_write.status_code in {200, 204}

        reread = client.get(
            f"{supabase_url}/rest/v1/profiles",
            params={"select": "user_id,full_name,avatar_url", "user_id": f"eq.{user_a_id}"},
            headers={"apikey": supabase_key, "Authorization": f"Bearer {token_a}"},
        )
        assert reread.status_code == 200
        assert reread.json()[0]["full_name"] is None
