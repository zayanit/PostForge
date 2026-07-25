from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


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


def _visible_brand_ids(engine: Engine, access_token: str, brand_id: str) -> list[str]:
    claims = jwt.decode(access_token, options={"verify_signature": False})
    assert claims["role"] == "authenticated"

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE authenticated"))
        connection.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)"),
            {"claims": json.dumps(claims)},
        )
        rows = connection.execute(
            text("SELECT id FROM brands WHERE id = :brand_id"),
            {"brand_id": brand_id},
        ).scalars().all()

    return [str(row) for row in rows]


def test_brand_reads_are_owner_scoped_at_api_and_database_layers():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine
    from backend.app.main import app

    password = "12345678"
    user_a_id: str | None = None
    user_b_id: str | None = None

    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_a_id, token_a = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-rls-a-{uuid4().hex[:10]}@example.com",
                password,
            )
            user_b_id, token_b = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-rls-b-{uuid4().hex[:10]}@example.com",
                password,
            )

            with TestClient(app) as api_client:
                create_response = api_client.post(
                    "/api/v1/brands",
                    headers={"Authorization": f"Bearer {token_a}"},
                    json={"name": "Owner A Brand"},
                )
                assert create_response.status_code == 201
                brand_id = create_response.json()["id"]

                owner_response = api_client.get(
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {token_a}"},
                )
                non_owner_response = api_client.get(
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {token_b}"},
                )
                nonexistent_response = api_client.get(
                    f"/api/v1/brands/{uuid4()}",
                    headers={"Authorization": f"Bearer {token_b}"},
                )

            assert owner_response.status_code == 200
            assert non_owner_response.status_code == 404
            assert nonexistent_response.status_code == 404
            assert non_owner_response.json()["error"]["code"] == "BRAND_NOT_FOUND"
            assert nonexistent_response.json()["error"]["code"] == "BRAND_NOT_FOUND"
            assert non_owner_response.json()["error"]["message"] == "Brand not found."
            assert nonexistent_response.json()["error"]["message"] == "Brand not found."

            engine = get_engine()
            assert _visible_brand_ids(engine, token_a, brand_id) == [brand_id]
            assert _visible_brand_ids(engine, token_b, brand_id) == []
        finally:
            for user_id in (user_a_id, user_b_id):
                if user_id:
                    supabase_client.delete(
                        f"{supabase_url}/auth/v1/admin/users/{user_id}",
                        headers={
                            "apikey": supabase_key,
                            "Authorization": f"Bearer {supabase_key}",
                        },
                    )
