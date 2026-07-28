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


SAFE_COLUMNS = (
    "id, provider, label, key_hint, lifecycle, is_active, is_valid, "
    "last_validated_at, last_validation_error, created_at"
)


class SecurityFixture(dict):
    def __repr__(self) -> str:
        return "<SecurityFixture redacted>"


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
) -> tuple[str, str]:
    password = "12345678"
    signup = client.post(
        f"{supabase_url}/auth/v1/signup",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    assert signup.status_code in {200, 201}
    token = client.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": supabase_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    assert token.status_code == 200
    return signup.json()["user"]["id"], token.json()["access_token"]


def _execute_as_authenticated(
    engine: Engine,
    access_token: str,
    statement: str,
    parameters: dict | None = None,
):
    claims = jwt.decode(access_token, options={"verify_signature": False})
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE authenticated"))
        connection.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)"),
            {"claims": json.dumps(claims)},
        )
        return connection.execute(text(statement), parameters or {}).mappings().all()


def _assert_permission_denied(operation) -> None:
    with pytest.raises(DBAPIError) as exc_info:
        operation()
    original = exc_info.value.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    assert sqlstate == "42501"


@pytest.fixture
def security_fixture():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine

    engine = get_engine()
    user_ids: list[str] = []
    brand_ids: list[str] = []
    with httpx.Client(timeout=30.0) as client:
        try:
            user_a, token_a = _signup_and_login(
                client,
                supabase_url,
                supabase_key,
                f"provider-rls-a-{uuid4().hex[:10]}@example.com",
            )
            user_b, token_b = _signup_and_login(
                client,
                supabase_url,
                supabase_key,
                f"provider-rls-b-{uuid4().hex[:10]}@example.com",
            )
            user_ids.extend((user_a, user_b))
            brand_a, brand_b = str(uuid4()), str(uuid4())
            key_a, key_b = str(uuid4()), str(uuid4())
            brand_ids.extend((brand_a, brand_b))
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO brands (id, owner_user_id, name) VALUES "
                        "(:brand_a, :user_a, 'Provider RLS A'), "
                        "(:brand_b, :user_b, 'Provider RLS B')"
                    ),
                    {
                        "brand_a": brand_a,
                        "user_a": user_a,
                        "brand_b": brand_b,
                        "user_b": user_b,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO provider_keys "
                        "(id, brand_id, provider, vault_secret_id, label, key_hint) "
                        "VALUES (:key_a, :brand_a, 'openai', :vault_a, 'A', '***a-_1'), "
                        "(:key_b, :brand_b, 'gemini', :vault_b, 'B', '***B_2-')"
                    ),
                    {
                        "key_a": key_a,
                        "brand_a": brand_a,
                        "vault_a": str(uuid4()),
                        "key_b": key_b,
                        "brand_b": brand_b,
                        "vault_b": str(uuid4()),
                    },
                )
            yield SecurityFixture({
                "engine": engine,
                "client": client,
                "supabase_url": supabase_url,
                "supabase_key": supabase_key,
                "user_a": user_a,
                "token_a": token_a,
                "token_b": token_b,
                "brand_a": brand_a,
                "key_a": key_a,
            })
        finally:
            if brand_ids:
                with engine.begin() as connection:
                    vault_ids = connection.execute(
                        text(
                            "SELECT vault_secret_id FROM provider_keys "
                            "WHERE brand_id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": brand_ids},
                    ).scalars().all()
                    if vault_ids:
                        connection.execute(
                            text(
                                "DELETE FROM vault.secrets "
                                "WHERE id = ANY(CAST(:ids AS uuid[]))"
                            ),
                            {"ids": vault_ids},
                        )
                    connection.execute(
                        text(
                            "DELETE FROM provider_keys "
                            "WHERE brand_id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": brand_ids},
                    )
            if brand_ids:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "DELETE FROM brands WHERE id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": brand_ids},
                    )
            for user_id in user_ids:
                client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )


def test_schema_constraints_indexes_triggers_and_forced_rls(security_fixture):
    engine = security_fixture["engine"]
    with engine.connect() as connection:
        enums = connection.execute(
            text(
                "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) "
                "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                "WHERE t.typname = ANY(:names) GROUP BY t.typname"
            ),
            {
                "names": [
                    "provider_t",
                    "provider_key_lifecycle_t",
                    "brand_deletion_state_t",
                ]
            },
        ).all()
        assert {name: list(values) for name, values in enums} == {
            "provider_t": ["openai", "gemini"],
            "provider_key_lifecycle_t": ["normal", "cleanup_required"],
            "brand_deletion_state_t": ["active", "cleanup_required"],
        }

        helper = connection.execute(
            text(
                "SELECT p.prosecdef, p.provolatile, p.proconfig, "
                "has_function_privilege('public', p.oid, 'EXECUTE') "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'private' AND p.proname = 'is_brand_owner' "
                "AND pg_get_function_identity_arguments(p.oid) = 'p_brand_id uuid'"
            )
        ).one()
        assert helper == (True, "s", ["search_path=\"\""], False)
        assert connection.execute(
            text(
                "SELECT has_schema_privilege('authenticated', 'private', 'USAGE') "
                "AND NOT has_schema_privilege('authenticated', 'private', 'CREATE') "
                "AND has_function_privilege(" 
                "'authenticated', 'private.is_brand_owner(uuid)', 'EXECUTE')"
            )
        ).scalar_one()

        table_security = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = ANY(:tables)"
            ),
            {
                "tables": [
                    "brands",
                    "provider_keys",
                    "provider_key_idempotency",
                    "brand_asset_operations",
                ]
            },
        ).all()
        assert set(table_security) == {
            ("brands", True, True),
            ("provider_keys", True, True),
            ("provider_key_idempotency", True, True),
            ("brand_asset_operations", True, True),
        }

        policies = connection.execute(
            text(
                "SELECT tablename, cmd FROM pg_policies "
                "WHERE tablename = ANY(:tables)"
            ),
            {
                "tables": [
                    "provider_keys",
                    "provider_key_idempotency",
                    "brand_asset_operations",
                ]
            },
        ).all()
        assert set(policies) == {
            ("provider_keys", "SELECT"),
            ("provider_keys", "INSERT"),
            ("provider_keys", "UPDATE"),
            ("provider_keys", "DELETE"),
            ("provider_key_idempotency", "ALL"),
            ("brand_asset_operations", "ALL"),
        }

        indexes = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'provider_keys'")
            ).scalars()
        )
        assert {
            "uq_provider_keys_vault_secret",
            "uq_provider_keys_one_active",
            "idx_provider_keys_brand_provider_created",
            "idx_provider_keys_cleanup",
        } <= indexes

        constraint_names = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = ANY(ARRAY["
                    "'brands'::regclass, 'provider_keys'::regclass, "
                    "'provider_key_idempotency'::regclass, "
                    "'brand_asset_operations'::regclass])"
                )
            ).scalars()
        )
        assert {
            "brands_logo_path_check",
            "brands_owner_user_id_fkey",
            "provider_keys_brand_id_fkey",
            "provider_keys_label_check",
            "provider_keys_key_hint_check",
            "provider_keys_cleanup_inactive",
            "provider_keys_invalid_inactive",
            "provider_keys_safe_validation_error",
            "provider_keys_validation_lease_pair",
            "provider_keys_cleanup_without_validation",
            "provider_keys_validation_result",
            "provider_key_idempotency_brand_id_fkey",
            "provider_key_idempotency_provider_key_id_fkey",
            "provider_key_idempotency_state_check",
            "uq_provider_key_idempotency_brand_request",
            "brand_asset_operations_brand_id_fkey",
            "brand_asset_operations_operation_check",
            "brand_asset_operations_state_check",
            "brand_asset_operations_remote_status_check",
            "uq_brand_asset_operations_brand",
        } <= constraint_names

        definitions = "\n".join(
            connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = ANY(ARRAY["
                    "'brands'::regclass, 'provider_keys'::regclass, "
                    "'provider_key_idempotency'::regclass, "
                    "'brand_asset_operations'::regclass])"
                )
            ).scalars()
        )
        for expected in (
            "ON DELETE RESTRICT",
            "ON DELETE CASCADE",
            "ON DELETE SET NULL",
            "INVALID_CREDENTIAL",
            "validation_token",
            "validation_lease_expires_at",
            "cleanup_required",
            "in_progress",
            "unknown",
        ):
            assert expected in definitions

        foreign_keys = dict(
            connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = ANY(:names)"
                ),
                {
                    "names": [
                        "brands_owner_user_id_fkey",
                        "provider_keys_brand_id_fkey",
                        "provider_key_idempotency_brand_id_fkey",
                        "provider_key_idempotency_provider_key_id_fkey",
                        "brand_asset_operations_brand_id_fkey",
                    ]
                },
            ).all()
        )
        assert "FOREIGN KEY (owner_user_id)" in foreign_keys["brands_owner_user_id_fkey"]
        assert "REFERENCES auth.users(id) ON DELETE RESTRICT" in foreign_keys[
            "brands_owner_user_id_fkey"
        ]
        assert "ON DELETE RESTRICT" in foreign_keys["provider_keys_brand_id_fkey"]
        assert "ON DELETE CASCADE" in foreign_keys[
            "provider_key_idempotency_brand_id_fkey"
        ]
        assert "ON DELETE SET NULL" in foreign_keys[
            "provider_key_idempotency_provider_key_id_fkey"
        ]
        assert "ON DELETE RESTRICT" in foreign_keys[
            "brand_asset_operations_brand_id_fkey"
        ]

        triggers = set(
            connection.execute(
                text(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE event_object_table = ANY(:tables)"
                ),
                {"tables": ["brands", "provider_keys", "brand_asset_operations"]},
            ).scalars()
        )
        assert {
            "trg_brands_cleanup_irreversible",
            "trg_provider_keys_cleanup_irreversible",
            "trg_provider_keys_updated_at",
            "trg_brand_asset_operations_updated_at",
        } <= triggers

        safe_grants = set(
            connection.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.column_privileges "
                    "WHERE grantee = 'authenticated' AND privilege_type = 'SELECT' "
                    "AND table_name IN ('brands', 'provider_keys')"
                )
            ).all()
        )
        assert safe_grants == {
            ("brands", column)
            for column in (
                "id",
                "name",
                "logo_path",
                "deletion_state",
                "created_at",
                "updated_at",
            )
        } | {
            ("provider_keys", column)
            for column in (
                "id",
                "provider",
                "label",
                "key_hint",
                "lifecycle",
                "is_active",
                "is_valid",
                "last_validated_at",
                "last_validation_error",
                "created_at",
            )
        }

        for role in ("anon", "authenticated"):
            for table in ("provider_key_idempotency", "brand_asset_operations"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not connection.execute(
                        text(
                            "SELECT has_table_privilege(:role, :table, :privilege)"
                        ),
                        {"role": role, "table": table, "privilege": privilege},
                    ).scalar_one()

        for role in ("anon", "authenticated"):
            assert not connection.execute(
                text("SELECT has_schema_privilege(:role, 'vault', 'USAGE')"),
                {"role": role},
            ).scalar_one()
            for relation, privilege in (
                ("vault.secrets", "SELECT"),
                ("vault.secrets", "DELETE"),
                ("vault.decrypted_secrets", "SELECT"),
            ):
                assert not connection.execute(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": role, "table": relation, "privilege": privilege},
                ).scalar_one()
            for function in (
                "vault.create_secret(text,text,text,uuid)",
                "vault.update_secret(uuid,text,text,text,uuid)",
            ):
                assert not connection.execute(
                    text(
                        "SELECT has_function_privilege(" 
                        ":role, :function, 'EXECUTE')"
                    ),
                    {"role": role, "function": function},
                ).scalar_one()

        assert connection.execute(
            text("SELECT has_schema_privilege('service_role', 'vault', 'USAGE')")
        ).scalar_one()
        assert not connection.execute(
            text("SELECT has_schema_privilege('service_role', 'vault', 'CREATE')")
        ).scalar_one()
        assert connection.execute(
            text(
                "SELECT has_function_privilege('service_role', "
                "'vault.create_secret(text,text,text,uuid)', 'EXECUTE')"
            )
        ).scalar_one()
        for relation, column in (
            ("vault.decrypted_secrets", "id"),
            ("vault.decrypted_secrets", "decrypted_secret"),
            ("vault.secrets", "id"),
        ):
            assert connection.execute(
                text(
                    "SELECT has_column_privilege('service_role', :table, :column, 'SELECT')"
                ),
                {"table": relation, "column": column},
            ).scalar_one()
        assert connection.execute(
            text("SELECT has_table_privilege('service_role', 'vault.secrets', 'DELETE')")
        ).scalar_one()


def test_owner_safe_reads_and_authenticated_dml_or_internal_reads_are_denied(
    security_fixture,
):
    fixture = security_fixture
    engine = fixture["engine"]
    own_rows = _execute_as_authenticated(
        engine,
        fixture["token_a"],
        f"SELECT {SAFE_COLUMNS} FROM provider_keys ORDER BY id",
    )
    assert [str(row["id"]) for row in own_rows] == [fixture["key_a"]]
    assert _execute_as_authenticated(
        engine,
        fixture["token_b"],
        f"SELECT {SAFE_COLUMNS} FROM provider_keys WHERE id = :key_id",
        {"key_id": fixture["key_a"]},
    ) == []

    for column in (
        "brand_id",
        "vault_secret_id",
        "validation_token",
        "validation_lease_expires_at",
        "last_used_at",
        "updated_at",
    ):
        _assert_permission_denied(
            lambda column=column: _execute_as_authenticated(
                engine, fixture["token_a"], f"SELECT {column} FROM provider_keys"
            )
        )

    statements = (
        (
            "INSERT INTO provider_keys "
            "(id, brand_id, provider, vault_secret_id, key_hint) "
            "VALUES (:id, :brand_id, 'openai', :vault_id, '***abcd')",
            {
                "id": str(uuid4()),
                "brand_id": fixture["brand_a"],
                "vault_id": str(uuid4()),
            },
        ),
        (
            "UPDATE provider_keys SET label = 'changed' WHERE id = :id",
            {"id": fixture["key_a"]},
        ),
        ("DELETE FROM provider_keys WHERE id = :id", {"id": fixture["key_a"]}),
    )
    for token in (fixture["token_a"], fixture["token_b"]):
        for statement, parameters in statements:
            _assert_permission_denied(
                lambda statement=statement, parameters=parameters, token=token: (
                    _execute_as_authenticated(engine, token, statement, parameters)
                )
            )


def test_backend_only_tables_vault_and_private_rpc_are_denied(security_fixture):
    fixture = security_fixture
    engine = fixture["engine"]
    for table in ("provider_key_idempotency", "brand_asset_operations"):
        statements = (
            f"SELECT * FROM {table}",
            f"INSERT INTO {table} (id, brand_id) VALUES (:id, :brand_id)",
            f"UPDATE {table} SET brand_id = :brand_id WHERE false",
            f"DELETE FROM {table} WHERE false",
        )
        for statement in statements:
            _assert_permission_denied(
                lambda statement=statement: _execute_as_authenticated(
                    engine,
                    fixture["token_a"],
                    statement,
                    {"id": str(uuid4()), "brand_id": fixture["brand_a"]},
                )
            )

    for statement in (
        "SELECT id FROM vault.secrets",
        "SELECT id, decrypted_secret FROM vault.decrypted_secrets",
        "SELECT vault.create_secret('denied', NULL, NULL, gen_random_uuid())",
        "SELECT vault.update_secret(gen_random_uuid(), 'denied', NULL, NULL, NULL)",
        "DELETE FROM vault.secrets WHERE false",
    ):
        _assert_permission_denied(
            lambda statement=statement: _execute_as_authenticated(
                engine, fixture["token_a"], statement
            )
        )

    client = fixture["client"]
    headers = {
        "apikey": fixture["supabase_key"],
        "Authorization": f"Bearer {fixture['token_a']}",
    }
    for table in ("provider_key_idempotency", "brand_asset_operations"):
        response = client.get(
            f"{fixture['supabase_url']}/rest/v1/{table}", headers=headers
        )
        assert response.status_code in {401, 403}
    helper_rpc = client.post(
        f"{fixture['supabase_url']}/rest/v1/rpc/is_brand_owner",
        headers={**headers, "Content-Type": "application/json"},
        json={"p_brand_id": fixture["brand_a"]},
    )
    assert helper_rpc.status_code == 404
    vault_profile = client.get(
        f"{fixture['supabase_url']}/rest/v1/secrets",
        headers={**headers, "Accept-Profile": "vault"},
    )
    assert vault_profile.status_code in {400, 401, 403, 404, 406}
    vault_rpc = client.post(
        f"{fixture['supabase_url']}/rest/v1/rpc/create_secret",
        headers={**headers, "Content-Type": "application/json"},
        json={"new_secret": "denied"},
    )
    assert vault_rpc.status_code == 404


def test_backend_role_has_required_application_and_vault_privileges(
    security_fixture,
):
    engine = security_fixture["engine"]
    with engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).one()
        assert role.rolname not in {"anon", "authenticated"}
        assert role.rolsuper or role.rolbypassrls

        for table in (
            "brands",
            "provider_keys",
            "provider_key_idempotency",
            "brand_asset_operations",
        ):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert connection.execute(
                    text(
                        "SELECT has_table_privilege(current_user, :table, :privilege)"
                    ),
                    {"table": table, "privilege": privilege},
                ).scalar_one()

        assert connection.execute(
            text("SELECT has_schema_privilege(current_user, 'vault', 'USAGE')")
        ).scalar_one()
        assert connection.execute(
            text(
                "SELECT has_function_privilege(current_user, "
                "'vault.create_secret(text,text,text,uuid)', 'EXECUTE')"
            )
        ).scalar_one()
        for relation, column in (
            ("vault.decrypted_secrets", "id"),
            ("vault.decrypted_secrets", "decrypted_secret"),
            ("vault.secrets", "id"),
        ):
            assert connection.execute(
                text(
                    "SELECT has_column_privilege(current_user, :table, :column, 'SELECT')"
                ),
                {"table": relation, "column": column},
            ).scalar_one()
        assert connection.execute(
            text("SELECT has_table_privilege(current_user, 'vault.secrets', 'DELETE')")
        ).scalar_one()
        if role.rolname != "postgres" and not role.rolsuper:
            assert not connection.execute(
                text("SELECT has_schema_privilege(current_user, 'vault', 'CREATE')")
            ).scalar_one()
            assert not connection.execute(
                text(
                    "SELECT has_function_privilege(current_user, "
                    "'vault.update_secret(uuid,text,text,text,uuid)', 'EXECUTE')"
                )
            ).scalar_one()
            for relation in ("vault.decrypted_secrets", "vault.secrets"):
                assert not connection.execute(
                    text("SELECT has_table_privilege(current_user, :table, 'SELECT')"),
                    {"table": relation},
                ).scalar_one()


def test_provider_key_api_owner_and_hidden_brand_parity(security_fixture):
    from backend.app.main import app

    fixture = security_fixture
    nonexistent_brand = str(uuid4())
    raw_key = f"rls-api-secret-{uuid4().hex}-Q7_W"
    with TestClient(app) as client:
        owner_list = client.get(
            f"/api/v1/brands/{fixture['brand_a']}/keys",
            headers={"Authorization": f"Bearer {fixture['token_a']}"},
        )
        hidden_list = client.get(
            f"/api/v1/brands/{fixture['brand_a']}/keys",
            headers={"Authorization": f"Bearer {fixture['token_b']}"},
        )
        missing_list = client.get(
            f"/api/v1/brands/{nonexistent_brand}/keys",
            headers={"Authorization": f"Bearer {fixture['token_b']}"},
        )
        owner_add = client.post(
            f"/api/v1/brands/{fixture['brand_a']}/keys",
            headers={
                "Authorization": f"Bearer {fixture['token_a']}",
                "Idempotency-Key": str(uuid4()),
            },
            json={"provider": "gemini", "key": raw_key, "make_active": False},
        )
        hidden_add = client.post(
            f"/api/v1/brands/{fixture['brand_a']}/keys",
            headers={
                "Authorization": f"Bearer {fixture['token_b']}",
                "Idempotency-Key": str(uuid4()),
            },
            json={"provider": "openai", "key": raw_key},
        )
        missing_add = client.post(
            f"/api/v1/brands/{nonexistent_brand}/keys",
            headers={
                "Authorization": f"Bearer {fixture['token_b']}",
                "Idempotency-Key": str(uuid4()),
            },
            json={"provider": "openai", "key": raw_key},
        )

    assert owner_list.status_code == 200
    assert owner_list.json() == {
        "keys": [
            {
                "id": fixture["key_a"],
                "provider": "openai",
                "label": "A",
                "key_hint": "***a-_1",
                "is_active": False,
                "is_valid": None,
                "last_validated_at": None,
                "last_validation_error": None,
                "cleanup_state": "normal",
                "created_at": owner_list.json()["keys"][0]["created_at"],
            }
        ]
    }
    assert owner_add.status_code == 201
    assert owner_add.json()["key_hint"] == "***Q7_W"
    assert raw_key not in owner_add.text
    for hidden, missing in ((hidden_list, missing_list), (hidden_add, missing_add)):
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json()["error"]["code"] == missing.json()["error"]["code"] == "BRAND_NOT_FOUND"
        assert hidden.json()["error"]["message"] == missing.json()["error"]["message"] == "Brand not found."
    assert raw_key not in hidden_add.text + missing_add.text


def test_provider_key_data_api_exposes_only_owner_safe_columns(security_fixture):
    fixture = security_fixture
    client = fixture["client"]

    def headers(token: str) -> dict[str, str]:
        return {
            "apikey": fixture["supabase_key"],
            "Authorization": f"Bearer {token}",
        }

    safe_select = (
        "id,provider,label,key_hint,lifecycle,is_active,is_valid,"
        "last_validated_at,last_validation_error,created_at"
    )
    owner = client.get(
        f"{fixture['supabase_url']}/rest/v1/provider_keys",
        headers=headers(fixture["token_a"]),
        params={"select": safe_select},
    )
    non_owner = client.get(
        f"{fixture['supabase_url']}/rest/v1/provider_keys",
        headers=headers(fixture["token_b"]),
        params={"select": safe_select},
    )
    internal = client.get(
        f"{fixture['supabase_url']}/rest/v1/provider_keys",
        headers=headers(fixture["token_a"]),
        params={"select": "brand_id,vault_secret_id,validation_token,last_used_at"},
    )
    vault = client.get(
        f"{fixture['supabase_url']}/rest/v1/decrypted_secrets",
        headers={**headers(fixture["token_a"]), "Accept-Profile": "vault"},
    )

    assert owner.status_code == 200
    assert [row["id"] for row in owner.json()] == [fixture["key_a"]]
    assert non_owner.status_code == 200
    assert all(row["id"] != fixture["key_a"] for row in non_owner.json())
    assert internal.status_code in {400, 401, 403}
    assert vault.status_code in {400, 401, 403, 404, 406}
