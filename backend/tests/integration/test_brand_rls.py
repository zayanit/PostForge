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
from sqlalchemy.exc import DBAPIError


PNG = b"\x89PNG\r\n\x1a\nowner-a-logo"


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


def _cross_owner_mutation_results(
    engine: Engine,
    access_token: str,
    brand_id: str,
) -> tuple[list[str], list[str]]:
    claims = jwt.decode(access_token, options={"verify_signature": False})

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE authenticated"))
        connection.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)"),
            {"claims": json.dumps(claims)},
        )
        updated = connection.execute(
            text(
                """
                UPDATE brands
                SET name = 'Unauthorized Update'
                WHERE id = :brand_id
                RETURNING id
                """
            ),
            {"brand_id": brand_id},
        ).scalars().all()
        deleted = connection.execute(
            text("DELETE FROM brands WHERE id = :brand_id RETURNING id"),
            {"brand_id": brand_id},
        ).scalars().all()

    return [str(row) for row in updated], [str(row) for row in deleted]


def _assert_cross_owner_insert_is_blocked(
    engine: Engine,
    access_token: str,
    owner_user_id: str,
) -> None:
    claims = jwt.decode(access_token, options={"verify_signature": False})

    with pytest.raises(DBAPIError) as exc_info:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE authenticated"))
            connection.execute(
                text("SELECT set_config('request.jwt.claims', :claims, true)"),
                {"claims": json.dumps(claims)},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO brands (owner_user_id, name)
                    VALUES (:owner_user_id, 'Unauthorized Insert')
                    """
                ),
                {"owner_user_id": owner_user_id},
            )

    original = exc_info.value.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    assert sqlstate == "42501"


def test_brand_operations_are_owner_scoped_at_api_and_database_layers():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine
    from backend.app.main import app

    password = "12345678"
    user_a_id: str | None = None
    user_b_id: str | None = None
    brand_id: str | None = None

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
                owner_upload_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers={"Authorization": f"Bearer {token_a}"},
                    files={"file": ("logo.png", PNG, "image/png")},
                )
                assert owner_upload_response.status_code == 200
                logo_url = owner_upload_response.json()["logo_url"]

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
                non_owner_upload_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers={"Authorization": f"Bearer {token_b}"},
                    files={
                        "file": (
                            "logo.jpg",
                            b"\xff\xd8\xffnon-owner",
                            "image/jpeg",
                        )
                    },
                )
                malformed_non_owner_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers={"Authorization": f"Bearer {token_b}"},
                    files={"file": ("logo.png", b"not a png", "image/png")},
                )
                non_owner_delete_response = api_client.delete(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers={"Authorization": f"Bearer {token_b}"},
                )
                non_owner_brand_delete_response = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {token_b}"},
                    json={"confirm_name": "Owner A Brand"},
                )
                owner_reread_response = api_client.get(
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {token_a}"},
                )

            assert owner_response.status_code == 200
            assert non_owner_response.status_code == 404
            assert nonexistent_response.status_code == 404
            assert non_owner_response.json()["error"]["code"] == "BRAND_NOT_FOUND"
            assert nonexistent_response.json()["error"]["code"] == "BRAND_NOT_FOUND"
            assert non_owner_response.json()["error"]["message"] == "Brand not found."
            assert nonexistent_response.json()["error"]["message"] == "Brand not found."
            for response in (
                non_owner_upload_response,
                malformed_non_owner_response,
                non_owner_delete_response,
                non_owner_brand_delete_response,
            ):
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "BRAND_NOT_FOUND"
                assert response.json()["error"]["message"] == "Brand not found."

            assert owner_reread_response.status_code == 200
            assert owner_reread_response.json()["logo_url"] == logo_url
            stored_logo = supabase_client.get(
                logo_url,
                params={"v": uuid4().hex},
            )
            assert stored_logo.status_code == 200
            assert stored_logo.content == PNG
            alternate_logo_url = logo_url.removesuffix("logo.png") + "logo.jpg"
            assert supabase_client.get(
                alternate_logo_url,
                params={"v": uuid4().hex},
            ).status_code in {400, 404}

            engine = get_engine()
            assert _visible_brand_ids(engine, token_a, brand_id) == [brand_id]
            assert _visible_brand_ids(engine, token_b, brand_id) == []
            assert _cross_owner_mutation_results(engine, token_b, brand_id) == ([], [])
            _assert_cross_owner_insert_is_blocked(engine, token_b, user_a_id)

            with TestClient(app) as api_client:
                post_rls_owner_response = api_client.get(
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {token_a}"},
                )
            assert post_rls_owner_response.status_code == 200
            assert post_rls_owner_response.json()["name"] == "Owner A Brand"
            assert post_rls_owner_response.json()["logo_url"] == logo_url
        finally:
            if brand_id:
                cleanup_response = supabase_client.request(
                    "DELETE",
                    f"{supabase_url}/storage/v1/object/brand-assets",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "prefixes": [
                            f"brands/{brand_id}/logo.png",
                            f"brands/{brand_id}/logo.jpg",
                        ]
                    },
                )
                assert cleanup_response.is_success
            for user_id in (user_a_id, user_b_id):
                if user_id:
                    supabase_client.delete(
                        f"{supabase_url}/auth/v1/admin/users/{user_id}",
                        headers={
                            "apikey": supabase_key,
                            "Authorization": f"Bearer {supabase_key}",
                        },
                    )
