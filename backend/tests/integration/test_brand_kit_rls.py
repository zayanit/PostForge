from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for integration tests")
    return value


def test_brand_kit_rls_is_forced_and_owner_scoped():
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine

    with get_engine().connect() as connection:
        policy = connection.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (
                         SELECT 1 FROM pg_policies
                         WHERE schemaname = 'public'
                           AND tablename = 'brand_kits'
                           AND policyname = 'brand_kits_owner'
                           AND qual LIKE '%is_brand_owner%'
                           AND with_check LIKE '%is_brand_owner%'
                       ) AS owner_policy
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'brand_kits'
                """
            )
        ).mappings().one()

    assert policy["relrowsecurity"] is True
    assert policy["relforcerowsecurity"] is True
    assert policy["owner_policy"] is True


def test_brand_kit_rls_has_backend_dml_privileges():
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine

    with get_engine().connect() as connection:
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege(current_user, 'public.brand_kits', 'SELECT')
                   AND has_table_privilege(current_user, 'public.brand_kits', 'INSERT')
                   AND has_table_privilege(current_user, 'public.brand_kits', 'UPDATE')
                   AND has_table_privilege(current_user, 'public.brand_kits', 'DELETE')
                   AS has_dml
                """
            )
        ).scalar_one()

    assert privileges is True


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
    token = client.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": "12345678"},
    )
    assert token.status_code == 200
    return user_id, token.json()["access_token"]


def _as_authenticated(connection, access_token: str) -> None:
    claims = jwt.decode(access_token, options={"verify_signature": False})
    connection.execute(text("SET LOCAL ROLE authenticated"))
    connection.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(claims)},
    )


def test_authenticated_roles_can_only_read_and_write_their_own_kit_rows():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine

    engine = get_engine()
    user_a_id = user_b_id = None
    brand_a = str(uuid4())
    brand_b = str(uuid4())
    with httpx.Client(timeout=30.0) as client:
        try:
            user_a_id, token_a = _signup_and_login(
                client, supabase_url, supabase_key, f"kit-rls-a-{uuid4().hex[:10]}@example.com"
            )
            user_b_id, token_b = _signup_and_login(
                client, supabase_url, supabase_key, f"kit-rls-b-{uuid4().hex[:10]}@example.com"
            )
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO brands (id, owner_user_id, name) VALUES "
                        "(:brand_a, :user_a, 'Kit RLS A'), (:brand_b, :user_b, 'Kit RLS B')"
                    ),
                    {"brand_a": brand_a, "user_a": user_a_id, "brand_b": brand_b, "user_b": user_b_id},
                )
                _as_authenticated(connection, token_a)
                connection.execute(
                    text(
                        "INSERT INTO brand_kits (brand_id, tagline) "
                        "VALUES (:brand_id, 'Owner answer')"
                    ),
                    {"brand_id": brand_a},
                )
                visible_to_a = connection.execute(
                    text("SELECT brand_id FROM brand_kits ORDER BY brand_id")
                ).scalars().all()
                assert [str(brand_id) for brand_id in visible_to_a] == [brand_a]
                connection.execute(
                    text("UPDATE brand_kits SET tagline = 'Updated answer' WHERE brand_id = :brand_id"),
                    {"brand_id": brand_a},
                )

            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    _as_authenticated(connection, token_a)
                    connection.execute(
                        text("INSERT INTO brand_kits (brand_id, tagline) VALUES (:brand_id, 'No access')"),
                        {"brand_id": brand_b},
                    )

            with engine.begin() as connection:
                _as_authenticated(connection, token_b)
                visible_to_b = connection.execute(
                    text("SELECT brand_id FROM brand_kits")
                ).scalars().all()
                assert visible_to_b == []
                update_result = connection.execute(
                    text(
                        "UPDATE brand_kits SET tagline = 'Cross-owner update' "
                        "WHERE brand_id = :brand_id"
                    ),
                    {"brand_id": brand_a},
                )
                delete_result = connection.execute(
                    text("DELETE FROM brand_kits WHERE brand_id = :brand_id"),
                    {"brand_id": brand_a},
                )
                assert update_result.rowcount == 0
                assert delete_result.rowcount == 0

            with engine.begin() as connection:
                _as_authenticated(connection, token_a)
                owner_tagline = connection.execute(
                    text("SELECT tagline FROM brand_kits WHERE brand_id = :brand_id"),
                    {"brand_id": brand_a},
                ).scalar_one()
                assert owner_tagline == "Updated answer"
        finally:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM brands WHERE id IN (:brand_a, :brand_b)"),
                    {"brand_a": brand_a, "brand_b": brand_b},
                )
            for user_id in (user_a_id, user_b_id):
                if user_id:
                    client.delete(
                        f"{supabase_url}/auth/v1/admin/users/{user_id}",
                        headers={
                            "apikey": supabase_key,
                            "Authorization": f"Bearer {supabase_key}",
                        },
                    )
