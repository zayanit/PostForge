from __future__ import annotations

import os
import sys
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for integration tests")
    return value


def _signup_and_login(
    client: httpx.Client, supabase_url: str, supabase_key: str, email: str
) -> tuple[str, str]:
    signup = client.post(
        f"{supabase_url}/auth/v1/signup",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": "12345678"},
    )
    assert signup.status_code in {200, 201}
    user_id = signup.json()["user"]["id"]
    try:
        token = client.post(
            f"{supabase_url}/auth/v1/token?grant_type=password",
            headers={"apikey": supabase_key, "Content-Type": "application/json"},
            json={"email": email, "password": "12345678"},
        )
        assert token.status_code == 200
        return user_id, token.json()["access_token"]
    except Exception:
        try:
            _delete_supabase_user(client, supabase_url, supabase_key, user_id)
        except Exception:
            pass
        raise


def _delete_supabase_user(
    client: httpx.Client,
    supabase_url: str,
    supabase_key: str,
    user_id: str,
) -> None:
    response = client.delete(
        f"{supabase_url}/auth/v1/admin/users/{user_id}",
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        },
    )
    response.raise_for_status()


def test_real_supabase_create_save_read_edit_and_single_kit_row():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine
    from backend.app.main import app

    user_id: str | None = None
    brand_id: str | None = None
    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-kit-{uuid4().hex[:12]}@example.com",
            )
            headers = {"Authorization": f"Bearer {access_token}"}
            with TestClient(app) as client:
                create = client.post(
                    "/api/v1/brands", headers=headers, json={"name": "My Brand"}
                )
                assert create.status_code == 201
                brand_id = create.json()["id"]

                saved = client.put(
                    f"/api/v1/brands/{brand_id}/kit",
                    headers=headers,
                    json={
                        "name": "My Brand",
                        "answers": {
                            "tone": "professional",
                            "audience": "Small business owners aged 25-45",
                            "colors": ["#FF5733", "#3498DB"],
                        },
                    },
                )
                read = client.get(f"/api/v1/brands/{brand_id}/kit", headers=headers)
                edited = client.put(
                    f"/api/v1/brands/{brand_id}/kit",
                    headers=headers,
                    json={
                        "name": "My Brand Updated",
                        "answers": {
                            "tagline": "Better work, every day",
                            "tone": "friendly",
                            "audience": "Growing teams",
                            "colors": ["#123456"],
                            "avoid_words": "cheap",
                        },
                    },
                )

            assert saved.status_code == 200
            assert saved.json()["status"] == "complete"
            assert read.status_code == 200
            assert read.json() == saved.json()
            assert edited.status_code == 200
            assert edited.json()["brand_name"] == "My Brand Updated"
            assert edited.json()["answers"]["tone"] == "friendly"
            assert edited.json()["summary"].startswith("Brand: My Brand Updated\n")
            assert edited.json()["completed_at"] == saved.json()["completed_at"]

            with get_engine().connect() as connection:
                assert connection.execute(
                    text("SELECT count(*) FROM brand_kits WHERE brand_id = :brand_id"),
                    {"brand_id": brand_id},
                ).scalar_one() == 1
        finally:
            original_failure = sys.exc_info()[0] is not None
            cleanup_errors: list[Exception] = []
            if brand_id:
                try:
                    with get_engine().begin() as connection:
                        connection.execute(
                            text("DELETE FROM brands WHERE id = :brand_id"),
                            {"brand_id": brand_id},
                        )
                except Exception as exc:
                    cleanup_errors.append(exc)
            if user_id:
                try:
                    _delete_supabase_user(
                        supabase_client, supabase_url, supabase_key, user_id
                    )
                except Exception as exc:
                    cleanup_errors.append(exc)
            if cleanup_errors and not original_failure:
                raise cleanup_errors[0]
