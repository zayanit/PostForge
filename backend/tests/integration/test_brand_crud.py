from __future__ import annotations

import base64
import os
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n0YAAAAASUVORK5CYII="
)
JPEG = b"\xff\xd8\xff\xe0" + b"postforge-jpeg-fixture" + b"\xff\xd9"


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


def _hard_delete_owned_brands(user_id: str) -> None:
    from backend.app.config import get_engine

    with get_engine().begin() as connection:
        connection.execute(
            text(
                "DELETE FROM brand_asset_operations WHERE brand_id IN ("
                "SELECT id FROM brands WHERE owner_user_id = :owner_user_id)"
            ),
            {"owner_user_id": user_id},
        )
        connection.execute(
            text("DELETE FROM brands WHERE owner_user_id = :owner_user_id"),
            {"owner_user_id": user_id},
        )


def test_create_brand_against_real_supabase():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.main import app

    email = f"brand-create-{uuid4().hex[:12]}@example.com"
    password = "12345678"
    user_id: str | None = None
    brand_id: str | None = None

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
                empty_list_response = api_client.get(
                    "/api/v1/brands",
                    headers=headers,
                )
                create_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "  Acme Coffee  "},
                )
                assert create_response.status_code == 201
                created_brand = create_response.json()
                brand_id = created_brand["id"]
                single_list_response = api_client.get(
                    "/api/v1/brands",
                    headers=headers,
                )
                second_create_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "Beta Bakery"},
                )
                multi_list_response = api_client.get(
                    "/api/v1/brands",
                    headers=headers,
                )
                detail_response = api_client.get(
                    f"/api/v1/brands/{created_brand['id']}",
                    headers=headers,
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
                png_upload_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.png", PNG_A, "image/png")},
                )

                assert png_upload_response.status_code == 200
                png_url = png_upload_response.json()["logo_url"]
                assert png_url
                stored_png = supabase_client.get(
                    png_url,
                    params={"v": uuid4().hex},
                )
                assert stored_png.status_code == 200
                assert stored_png.content == PNG_A

                same_format_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.png", PNG_B, "image/png")},
                )
                assert same_format_response.status_code == 200
                replacement_png_url = same_format_response.json()["logo_url"]
                assert replacement_png_url != png_url
                assert f"brands/{brand_id}/logos/" in replacement_png_url
                replaced_png = supabase_client.get(
                    replacement_png_url,
                    params={"v": uuid4().hex},
                )
                assert replaced_png.status_code == 200
                assert replaced_png.content == PNG_B
                assert supabase_client.get(
                    png_url,
                    params={"v": uuid4().hex},
                ).status_code in {400, 404}

                different_format_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.jpg", JPEG, "image/jpeg")},
                )
                assert different_format_response.status_code == 200
                jpeg_url = different_format_response.json()["logo_url"]
                assert jpeg_url and jpeg_url != replacement_png_url
                stored_jpeg = supabase_client.get(
                    jpeg_url,
                    params={"v": uuid4().hex},
                )
                assert stored_jpeg.status_code == 200
                assert stored_jpeg.content == JPEG
                assert supabase_client.get(
                    replacement_png_url,
                    params={"v": uuid4().hex},
                ).status_code in {400, 404}

                unsupported_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.txt", b"text", "text/plain")},
                )
                spoofed_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.png", b"not a png", "image/png")},
                )
                oversized_response = api_client.post(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                    files={
                        "file": (
                            "logo.png",
                            b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024),
                            "image/png",
                        )
                    },
                )

                assert unsupported_response.status_code == 400
                assert spoofed_response.status_code == 400
                assert oversized_response.status_code == 413
                unchanged_jpeg = supabase_client.get(
                    jpeg_url,
                    params={"v": uuid4().hex},
                )
                assert unchanged_jpeg.status_code == 200
                assert unchanged_jpeg.content == JPEG
                assert supabase_client.get(
                    replacement_png_url,
                    params={"v": uuid4().hex},
                ).status_code in {400, 404}

                remove_response = api_client.delete(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                )
                repeat_remove_response = api_client.delete(
                    f"/api/v1/brands/{brand_id}/logo",
                    headers=headers,
                )
                assert remove_response.status_code == 204
                assert repeat_remove_response.status_code == 204
                assert supabase_client.get(
                    jpeg_url,
                    params={"v": uuid4().hex},
                ).status_code in {400, 404}

            assert empty_list_response.status_code == 200
            assert empty_list_response.json() == {"brands": []}
            assert created_brand["name"] == "Acme Coffee"
            assert created_brand["logo_url"] is None
            assert created_brand["cleanup_state"] == "normal"
            assert single_list_response.status_code == 200
            assert [brand["name"] for brand in single_list_response.json()["brands"]] == [
                "Acme Coffee"
            ]
            assert second_create_response.status_code == 201
            assert multi_list_response.status_code == 200
            assert [brand["name"] for brand in multi_list_response.json()["brands"]] == [
                "Beta Bakery",
                "Acme Coffee",
            ]
            assert detail_response.status_code == 200
            assert detail_response.json() == created_brand
            assert all(
                brand["cleanup_state"] == "normal"
                for brand in multi_list_response.json()["brands"]
            )
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
            assert {
                (brand["owner_user_id"], brand["name"])
                for brand in persisted_response.json()
            } == {
                (user_id, "Acme Coffee"),
                (user_id, "Beta Bakery"),
            }
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
                            f"brands/{brand_id}/logo.webp",
                        ]
                    },
                )
                assert cleanup_response.is_success
            if user_id:
                _hard_delete_owned_brands(user_id)
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )


def test_delete_brands_with_and_without_logo_against_real_supabase():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.main import app

    user_id: str | None = None
    logo_brand_id: str | None = None
    logo_url: str | None = None

    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-delete-{uuid4().hex[:12]}@example.com",
                "12345678",
            )
            headers = {"Authorization": f"Bearer {access_token}"}

            with TestClient(app) as api_client:
                logo_brand_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "Logo Brand"},
                )
                plain_brand_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "Plain Brand"},
                )
                assert logo_brand_response.status_code == 201
                assert plain_brand_response.status_code == 201
                logo_brand_id = logo_brand_response.json()["id"]
                plain_brand_id = plain_brand_response.json()["id"]

                upload_response = api_client.post(
                    f"/api/v1/brands/{logo_brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.png", PNG_A, "image/png")},
                )
                assert upload_response.status_code == 200
                logo_url = upload_response.json()["logo_url"]
                assert supabase_client.get(logo_url).status_code == 200

                delete_logo_brand_response = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{logo_brand_id}",
                    headers=headers,
                    json={"confirm_name": "Logo Brand"},
                )
                delete_plain_brand_response = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{plain_brand_id}",
                    headers=headers,
                    json={"confirm_name": "Plain Brand"},
                )
                assert delete_logo_brand_response.status_code == 204
                assert delete_plain_brand_response.status_code == 204
                assert api_client.get(
                    f"/api/v1/brands/{logo_brand_id}", headers=headers
                ).status_code == 404
                assert api_client.get(
                    f"/api/v1/brands/{plain_brand_id}", headers=headers
                ).status_code == 404

            persisted_response = supabase_client.get(
                f"{supabase_url}/rest/v1/brands",
                params={"select": "id", "owner_user_id": f"eq.{user_id}"},
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                },
            )
            assert persisted_response.status_code == 200
            assert persisted_response.json() == []
            assert logo_url is not None
            assert supabase_client.get(
                logo_url,
                params={"v": uuid4().hex},
            ).status_code in {400, 404}
        finally:
            if logo_brand_id:
                cleanup_response = supabase_client.request(
                    "DELETE",
                    f"{supabase_url}/storage/v1/object/brand-assets",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                    },
                    json={"prefixes": [f"brands/{logo_brand_id}/logo.png"]},
                )
                assert cleanup_response.is_success
            if user_id:
                _hard_delete_owned_brands(user_id)
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )


def test_list_and_open_fifty_brands_within_target_time():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.main import app

    user_id: str | None = None

    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-scale-{uuid4().hex[:12]}@example.com",
                "12345678",
            )
            headers = {"Authorization": f"Bearer {access_token}"}

            with TestClient(app) as api_client:
                brand_ids: list[str] = []
                for index in range(50):
                    create_response = api_client.post(
                        "/api/v1/brands",
                        headers=headers,
                        json={"name": f"Scale Brand {index + 1:02d}"},
                    )
                    assert create_response.status_code == 201
                    brand_ids.append(create_response.json()["id"])

                started_at = time.perf_counter()
                list_response = api_client.get("/api/v1/brands", headers=headers)
                detail_response = api_client.get(
                    f"/api/v1/brands/{brand_ids[24]}",
                    headers=headers,
                )
                elapsed = time.perf_counter() - started_at

            assert list_response.status_code == 200
            assert len(list_response.json()["brands"]) == 50
            assert detail_response.status_code == 200
            assert detail_response.json()["id"] == brand_ids[24]
            assert elapsed < 10
        finally:
            if user_id:
                _hard_delete_owned_brands(user_id)
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )


def test_cleanup_state_mutation_fences_and_authenticated_delete_restriction():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine
    from backend.app.main import app

    user_id: str | None = None
    active_brand_id: str | None = None
    cleanup_brand_id: str | None = None
    operation_id = str(uuid4())

    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-fences-{uuid4().hex[:12]}@example.com",
                "12345678",
            )
            headers = {"Authorization": f"Bearer {access_token}"}

            with TestClient(app) as api_client:
                active_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "Active Brand"},
                )
                cleanup_response = api_client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "Cleanup Brand"},
                )
                assert (
                    active_response.status_code
                    == cleanup_response.status_code
                    == 201
                )
                active_brand_id = active_response.json()["id"]
                cleanup_brand_id = cleanup_response.json()["id"]
                assert active_response.json()["cleanup_state"] == "normal"

                engine = get_engine()
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            UPDATE brands
                            SET deletion_state = 'cleanup_required'
                            WHERE id = :brand_id
                            """
                        ),
                        {"brand_id": cleanup_brand_id},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO brand_asset_operations (
                                id, brand_id, operation, state, remote_status
                            )
                            VALUES (
                                :id, :brand_id, 'upload', 'in_progress', 'pending'
                            )
                            """
                        ),
                        {"id": operation_id, "brand_id": active_brand_id},
                    )

                list_response = api_client.get("/api/v1/brands", headers=headers)
                cleanup_detail = api_client.get(
                    f"/api/v1/brands/{cleanup_brand_id}", headers=headers
                )
                cleanup_upload = api_client.post(
                    f"/api/v1/brands/{cleanup_brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.png", PNG_A, "image/png")},
                )
                cleanup_remove = api_client.delete(
                    f"/api/v1/brands/{cleanup_brand_id}/logo", headers=headers
                )
                cleanup_delete = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{cleanup_brand_id}",
                    headers=headers,
                    json={"confirm_name": "Cleanup Brand"},
                )
                active_upload = api_client.post(
                    f"/api/v1/brands/{active_brand_id}/logo",
                    headers=headers,
                    files={"file": ("logo.png", PNG_A, "image/png")},
                )
                active_delete = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{active_brand_id}",
                    headers=headers,
                    json={"confirm_name": "Active Brand"},
                )

                assert list_response.status_code == 200
                states = {
                    brand["id"]: brand["cleanup_state"]
                    for brand in list_response.json()["brands"]
                }
                assert states == {
                    active_brand_id: "normal",
                    cleanup_brand_id: "cleanup_required",
                }
                assert cleanup_detail.status_code == 200
                assert cleanup_detail.json()["cleanup_state"] == "cleanup_required"
                assert "deletion_state" not in cleanup_detail.json()
                for response in (cleanup_upload, cleanup_remove):
                    assert response.status_code == 409
                    assert response.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
                assert cleanup_delete.status_code == 204
                for response in (active_upload, active_delete):
                    assert response.status_code == 409
                    assert (
                        response.json()["error"]["code"]
                        == "BRAND_MUTATION_IN_PROGRESS"
                    )

                authenticated_delete = supabase_client.delete(
                    f"{supabase_url}/rest/v1/brands",
                    params={"id": f"eq.{active_brand_id}"},
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                assert authenticated_delete.status_code in {401, 403}
                assert api_client.get(
                    f"/api/v1/brands/{active_brand_id}", headers=headers
                ).status_code == 200

                auth_user_delete = supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )
                assert not auth_user_delete.is_success
                with engine.connect() as connection:
                    assert connection.execute(
                        text("SELECT count(*) FROM brands WHERE owner_user_id = :user_id"),
                        {"user_id": user_id},
                    ).scalar_one() == 1
        finally:
            if active_brand_id:
                with get_engine().begin() as connection:
                    connection.execute(
                        text("DELETE FROM brand_asset_operations WHERE id = :id"),
                        {"id": operation_id},
                    )
            if user_id:
                _hard_delete_owned_brands(user_id)
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )


def test_brand_storage_failure_persists_cleanup_required_retry_anchor():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("SUPABASE_JWT_SECRET")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine
    from backend.app.main import app
    from backend.app.routes.brands import get_brand_deletion, get_brand_storage
    from backend.app.services.brand_deletion import BrandDeletion
    from backend.app.services.brand_storage import BrandStorageError
    from backend.app.services.brand_store import get_brand_store

    class ControllableStorage:
        fail_delete = True

        async def delete_brand_prefix(self, brand_id) -> None:
            if self.fail_delete:
                raise BrandStorageError

        async def brand_prefix_is_empty(self, brand_id) -> bool:
            return not self.fail_delete

    user_id: str | None = None
    brand_id = str(uuid4())
    logo_path = f"brands/{brand_id}/logo.png"
    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-cleanup-anchor-{uuid4().hex[:12]}@example.com",
                "12345678",
            )
            with get_engine().begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO brands (id, owner_user_id, name, logo_path) "
                        "VALUES (:id, :owner_user_id, 'Cleanup Anchor', :logo_path)"
                    ),
                    {
                        "id": brand_id,
                        "owner_user_id": user_id,
                        "logo_path": logo_path,
                    },
                )

            storage = ControllableStorage()
            app.dependency_overrides[get_brand_storage] = lambda: storage
            app.dependency_overrides[get_brand_deletion] = lambda: BrandDeletion(
                get_engine(), get_brand_store(), storage
            )
            with TestClient(app) as api_client:
                response = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"confirm_name": "Cleanup Anchor"},
                )

            assert response.status_code == 503
            assert response.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
            with get_engine().connect() as connection:
                retained = connection.execute(
                    text(
                        "SELECT deletion_state, logo_path FROM brands WHERE id = :id"
                    ),
                    {"id": brand_id},
                ).one()
            assert retained.deletion_state == "cleanup_required"
            assert retained.logo_path == logo_path

            storage.fail_delete = False
            with TestClient(app) as api_client:
                retry = api_client.request(
                    "DELETE",
                    f"/api/v1/brands/{brand_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"confirm_name": "Cleanup Anchor"},
                )
            assert retry.status_code == 204
            with get_engine().connect() as connection:
                assert connection.execute(
                    text("SELECT count(*) FROM brands WHERE id = :id"),
                    {"id": brand_id},
                ).scalar_one() == 0
        finally:
            app.dependency_overrides.clear()
            if user_id:
                _hard_delete_owned_brands(user_id)
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )
