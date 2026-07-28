from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError


class SecretFixture(str):
    def __repr__(self) -> str:
        return "<SecretFixture redacted>"


class ProviderFixture(dict):
    def __repr__(self) -> str:
        return "<ProviderFixture redacted>"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.fail(f"{name} is required; provider-key integration tests must execute")
    return value


def _signup_and_login(
    client: httpx.Client, supabase_url: str, supabase_key: str
) -> tuple[str, str]:
    email = f"provider-keys-{uuid4().hex[:12]}@example.com"
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


@pytest.fixture
def provider_fixture():
    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine

    engine = get_engine()
    user_id: str | None = None
    brand_id = uuid4()
    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client, supabase_url, supabase_key
            )
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO brands (id, owner_user_id, name) "
                        "VALUES (:id, :owner, 'Provider Keys Integration')"
                    ),
                    {"id": brand_id, "owner": user_id},
                )
            yield ProviderFixture({
                "engine": engine,
                "brand_id": brand_id,
                "headers": {"Authorization": f"Bearer {access_token}"},
            })
        finally:
            with engine.begin() as connection:
                vault_ids = connection.execute(
                    text(
                        "SELECT vault_secret_id FROM provider_keys "
                        "WHERE brand_id = :brand_id"
                    ),
                    {"brand_id": brand_id},
                ).scalars().all()
                if vault_ids:
                    connection.execute(
                        text("DELETE FROM vault.secrets WHERE id = ANY(:ids)"),
                        {"ids": vault_ids},
                    )
                connection.execute(
                    text("DELETE FROM provider_keys WHERE brand_id = :brand_id"),
                    {"brand_id": brand_id},
                )
                connection.execute(
                    text(
                        "DELETE FROM provider_key_idempotency "
                        "WHERE brand_id = :brand_id"
                    ),
                    {"brand_id": brand_id},
                )
                connection.execute(
                    text("DELETE FROM brands WHERE id = :brand_id"),
                    {"brand_id": brand_id},
                )
            if user_id:
                supabase_client.delete(
                    f"{supabase_url}/auth/v1/admin/users/{user_id}",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                    },
                )


def test_real_vault_add_list_activation_idempotency_and_retired_receipt(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    brand_id = fixture["brand_id"]
    openai_request = uuid4()
    gemini_request = uuid4()
    replacement_request = uuid4()
    openai_key = SecretFixture(f"openai-integration-{uuid4().hex}-A1B2")
    gemini_key = SecretFixture(f"gemini-integration-{uuid4().hex}-C3_D")
    replacement_key = SecretFixture(f"openai-replacement-{uuid4().hex}-E5-F")

    with TestClient(app) as client:
        empty = client.get(
            f"/api/v1/brands/{brand_id}/keys", headers=fixture["headers"]
        )
        first = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={**fixture["headers"], "Idempotency-Key": str(openai_request)},
            json={
                "provider": "openai",
                "key": str(openai_key),
                "label": "Inactive OpenAI",
                "make_active": False,
            },
        )
        gemini = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={**fixture["headers"], "Idempotency-Key": str(gemini_request)},
            json={"provider": "gemini", "key": str(gemini_key)},
        )
        replacement = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={
                **fixture["headers"],
                "Idempotency-Key": str(replacement_request),
            },
            json={"provider": "openai", "key": str(replacement_key)},
        )
        retry = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={**fixture["headers"], "Idempotency-Key": str(openai_request)},
            json={"provider": "gemini", "key": str(replacement_key)},
        )
        listed = client.get(
            f"/api/v1/brands/{brand_id}/keys", headers=fixture["headers"]
        )

    assert empty.status_code == 200 and empty.json() == {"keys": []}
    assert first.status_code == gemini.status_code == replacement.status_code == 201
    assert first.json()["key_hint"] == "***A1B2"
    assert gemini.json()["key_hint"] == "***C3_D"
    assert replacement.json()["key_hint"] == "***E5-F"
    assert first.json()["is_active"] is False
    assert gemini.json()["is_active"] is True
    assert replacement.json()["is_active"] is True
    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert listed.status_code == 200
    keys = listed.json()["keys"]
    assert [(key["provider"], key["id"]) for key in keys] == [
        ("openai", replacement.json()["id"]),
        ("openai", first.json()["id"]),
        ("gemini", gemini.json()["id"]),
    ]
    serialized = "".join(response.text for response in (first, gemini, replacement, retry, listed))
    for raw_key in (openai_key, gemini_key, replacement_key):
        assert raw_key not in serialized

    engine = fixture["engine"]
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, provider, vault_secret_id, key_hint, is_active "
                "FROM provider_keys WHERE brand_id = :brand_id "
                "ORDER BY provider, created_at DESC, id DESC"
            ),
            {"brand_id": brand_id},
        ).mappings().all()
        assert len(rows) == 3
        assert sum(row["is_active"] for row in rows if row["provider"] == "openai") == 1
        assert sum(row["is_active"] for row in rows if row["provider"] == "gemini") == 1
        assert connection.execute(
            text(
                "SELECT count(*) FROM provider_key_idempotency "
                "WHERE brand_id = :brand_id"
            ),
            {"brand_id": brand_id},
        ).scalar_one() == 3
        decrypted_matches = connection.execute(
            text(
                "SELECT count(*) FROM provider_keys pk "
                "JOIN vault.decrypted_secrets ds ON ds.id = pk.vault_secret_id "
                "WHERE pk.brand_id = :brand_id AND ds.decrypted_secret = ANY(:values)"
            ),
            {
                "brand_id": brand_id,
                "values": [str(openai_key), str(gemini_key), str(replacement_key)],
            },
        ).scalar_one()
        assert decrypted_matches == 3

    retired_id = UUID(first.json()["id"])
    with engine.begin() as connection:
        vault_id = connection.execute(
            text("SELECT vault_secret_id FROM provider_keys WHERE id = :id"),
            {"id": retired_id},
        ).scalar_one()
        connection.execute(text("DELETE FROM vault.secrets WHERE id = :id"), {"id": vault_id})
        connection.execute(text("DELETE FROM provider_keys WHERE id = :id"), {"id": retired_id})
        receipt = connection.execute(
            text(
                "SELECT state, provider_key_id FROM provider_key_idempotency "
                "WHERE brand_id = :brand_id AND request_id = :request_id"
            ),
            {"brand_id": brand_id, "request_id": openai_request},
        ).one()
        assert receipt.state == "active"
        assert receipt.provider_key_id is None

    with TestClient(app) as client:
        retired = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={**fixture["headers"], "Idempotency-Key": str(openai_request)},
            json={"provider": "openai", "key": str(openai_key)},
        )
    assert retired.status_code == 409
    assert retired.json()["error"]["code"] == "IDEMPOTENCY_KEY_RETIRED"


class _CommitOutcomeUnknownContext:
    def __init__(self, engine, state):
        self._context = engine.begin()
        self._state = state

    def __enter__(self):
        return self._context.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        result = self._context.__exit__(exc_type, exc_value, traceback)
        if exc_type is None and not self._state["raised"]:
            self._state["raised"] = True
            raise SQLAlchemyError("commit result unavailable to client")
        return result


class _CommitOutcomeUnknownEngine:
    def __init__(self, engine):
        self._engine = engine
        self._state = {"raised": False}

    def begin(self):
        return _CommitOutcomeUnknownContext(self._engine, self._state)


def test_ambiguous_commit_retry_reconciles_one_vault_secret_and_row(provider_fixture):
    from backend.app.main import app
    from backend.app.routes.provider_keys import get_provider_key_store
    from backend.app.services.provider_key_store import ProviderKeyStore

    fixture = provider_fixture
    brand_id = fixture["brand_id"]
    request_id = uuid4()
    raw_key = SecretFixture(f"ambiguous-commit-{uuid4().hex}-A1B2")
    store = ProviderKeyStore(_CommitOutcomeUnknownEngine(fixture["engine"]))
    app.dependency_overrides[get_provider_key_store] = lambda: store

    try:
        with TestClient(app) as client:
            first = client.post(
                f"/api/v1/brands/{brand_id}/keys",
                headers={
                    **fixture["headers"],
                    "Idempotency-Key": str(request_id),
                },
                json={"provider": "openai", "key": str(raw_key)},
            )
            retry = client.post(
                f"/api/v1/brands/{brand_id}/keys",
                headers={
                    **fixture["headers"],
                    "Idempotency-Key": str(request_id),
                },
                json={"provider": "gemini", "key": "different-A1B2"},
            )
    finally:
        app.dependency_overrides.pop(get_provider_key_store, None)

    assert first.status_code == 502
    assert first.json()["error"]["code"] == "VAULT_UNAVAILABLE"
    assert retry.status_code == 201
    assert retry.json()["key_hint"] == "***A1B2"

    with fixture["engine"].connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, vault_secret_id FROM provider_keys "
                "WHERE brand_id = :brand_id"
            ),
            {"brand_id": brand_id},
        ).one()
        assert connection.execute(
            text(
                "SELECT count(*) FROM provider_key_idempotency "
                "WHERE brand_id = :brand_id AND request_id = :request_id"
            ),
            {"brand_id": brand_id, "request_id": request_id},
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM vault.secrets WHERE id = :id"),
            {"id": row.vault_secret_id},
        ).scalar_one() == 1


def test_real_add_validation_and_cleanup_fences_create_no_secret(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    brand_id = fixture["brand_id"]
    raw_key = SecretFixture(f"fenced-provider-{uuid4().hex}-Z9_Y")
    engine = fixture["engine"]
    invalid_bodies = [
        {"provider": "openai", "key": ""},
        {"provider": "openai", "key": "abcd"},
        {"provider": "openai", "key": "invalid!?"},
        {"provider": "unknown", "key": str(raw_key)},
        {"provider": "gemini", "key": str(raw_key), "label": "x" * 101},
    ]
    with engine.connect() as connection:
        before = connection.execute(text("SELECT count(*) FROM vault.secrets")).scalar_one()
    with TestClient(app) as client:
        for body in invalid_bodies:
            response = client.post(
                f"/api/v1/brands/{brand_id}/keys",
                headers={**fixture["headers"], "Idempotency-Key": str(uuid4())},
                json=body,
            )
            assert response.status_code == 400
        cleanup_key_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_keys "
                    "(id, brand_id, provider, vault_secret_id, key_hint, lifecycle) "
                    "VALUES (:id, :brand_id, 'openai', :vault_id, '***K3_Y', "
                    "'cleanup_required')"
                ),
                {
                    "id": cleanup_key_id,
                    "brand_id": brand_id,
                    "vault_id": uuid4(),
                },
            )
        pending_key_cleanup = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={**fixture["headers"], "Idempotency-Key": str(uuid4())},
            json={"provider": "openai", "key": str(raw_key)},
        )
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM provider_keys WHERE id = :id"),
                {"id": cleanup_key_id},
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE brands SET deletion_state = 'cleanup_required' "
                    "WHERE id = :brand_id"
                ),
                {"brand_id": brand_id},
            )
        fenced = client.post(
            f"/api/v1/brands/{brand_id}/keys",
            headers={**fixture["headers"], "Idempotency-Key": str(uuid4())},
            json={"provider": "openai", "key": str(raw_key)},
        )
    assert pending_key_cleanup.status_code == 409
    assert pending_key_cleanup.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
    assert fenced.status_code == 409
    assert fenced.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM vault.secrets")).scalar_one() == before
        assert connection.execute(
            text("SELECT count(*) FROM provider_keys WHERE brand_id = :brand_id"),
            {"brand_id": brand_id},
        ).scalar_one() == 0


def test_real_vault_and_metadata_work_roll_back_together(provider_fixture):
    fixture = provider_fixture
    engine = fixture["engine"]
    vault_id = None
    raw_key = SecretFixture(f"rollback-provider-{uuid4().hex}-R0_L")

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            vault_id = connection.execute(
                text("SELECT vault.create_secret(:secret, NULL, '')"),
                {"secret": str(raw_key)},
            ).scalar_one()
            connection.execute(text("SELECT 1 / 0"))

    assert vault_id is not None
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM vault.secrets WHERE id = :id"),
            {"id": vault_id},
        ).scalar_one() == 0
