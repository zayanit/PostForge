from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Container
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import (
    DBAPIError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)


def _assert_not_exposed(
    observable: Container[str], *prohibited_values: str
) -> None:
    if any(value in observable for value in prohibited_values):
        raise AssertionError("sensitive value was exposed")


class SecretFixture(str):
    def __repr__(self) -> str:
        return "<SecretFixture redacted>"


class ProviderFixture(dict):
    def __repr__(self) -> str:
        return "<ProviderFixture redacted>"


class MockProviderValidator:
    def __init__(
        self,
        *results: tuple[str, str],
        expected_secret: SecretFixture,
        block_first: bool = False,
    ) -> None:
        self._results = list(results)
        self._expected_secret = expected_secret
        self._block_first = block_first
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.connection_counts: list[int] = []
        self.engine = None

    def __repr__(self) -> str:
        return "<MockProviderValidator redacted>"

    async def _validate(self, *args, **kwargs):
        values = [*args, *kwargs.values()]
        assert any(value == self._expected_secret for value in values)
        call_index = self.calls
        self.calls += 1
        if self.engine is not None:
            self.connection_counts.append(self.engine.pool.checkedout())
        self.entered.set()
        if self._block_first and call_index == 0:
            released = await asyncio.to_thread(self.release.wait, 10)
            assert released
        outcome, code = self._results[min(call_index, len(self._results) - 1)]
        return SimpleNamespace(
            outcome=outcome,
            code=code,
            provider_request_id="mock-provider-request",
        )

    async def validate(self, *args, **kwargs):
        return await self._validate(*args, **kwargs)

    async def validate_key(self, *args, **kwargs):
        return await self._validate(*args, **kwargs)

    async def __call__(self, *args, **kwargs):
        return await self._validate(*args, **kwargs)


def _provider_validator_dependency():
    from backend.app.routes import provider_keys as provider_key_routes

    dependency = getattr(provider_key_routes, "get_provider_validator", None)
    assert dependency is not None, "validation provider dependency is not implemented"
    return dependency


def _add_real_key(
    client: TestClient,
    fixture: ProviderFixture,
    raw_key: SecretFixture,
    *,
    make_active: bool = True,
) -> UUID:
    response = client.post(
        f"/api/v1/brands/{fixture['brand_id']}/keys",
        headers={**fixture["headers"], "Idempotency-Key": str(uuid4())},
        json={
            "provider": "openai",
            "key": str(raw_key),
            "make_active": make_active,
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def _validation_state(engine, key_id: UUID):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT is_valid, last_validated_at, last_validation_error, "
                "is_active, validation_token, validation_lease_expires_at "
                "FROM provider_keys WHERE id = :key_id"
            ),
            {"key_id": key_id},
        ).one()


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
    _assert_not_exposed(serialized, openai_key, gemini_key, replacement_key)

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


def test_validation_cleanup_conflicts_return_fixed_errors_without_provider_call(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    engine = fixture["engine"]
    key_cleanup_secret = SecretFixture(f"validation-key-cleanup-{uuid4().hex}-A1B2")
    brand_cleanup_secret = SecretFixture(f"validation-brand-cleanup-{uuid4().hex}-C3_D")
    validator = MockProviderValidator(
        expected_secret=key_cleanup_secret,
    )
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator

    try:
        with TestClient(app) as client:
            key_cleanup_id = _add_real_key(
                client, fixture, key_cleanup_secret, make_active=False
            )
            brand_cleanup_id = _add_real_key(
                client, fixture, brand_cleanup_secret, make_active=False
            )
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE provider_keys SET lifecycle = 'cleanup_required' "
                        "WHERE id = :key_id"
                    ),
                    {"key_id": key_cleanup_id},
                )
            key_cleanup = client.post(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_cleanup_id}/validate",
                headers=fixture["headers"],
            )

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE brands SET deletion_state = 'cleanup_required' "
                        "WHERE id = :brand_id"
                    ),
                    {"brand_id": fixture["brand_id"]},
                )
            brand_cleanup = client.post(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{brand_cleanup_id}/validate",
                headers=fixture["headers"],
            )
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert key_cleanup.status_code == 409
    assert key_cleanup.json()["error"]["code"] == "KEY_CLEANUP_REQUIRED"
    assert brand_cleanup.status_code == 409
    assert brand_cleanup.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
    assert validator.calls == 0


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


def test_validation_claim_atomically_decrypts_and_releases_connection_for_provider_await(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"validation-claim-{uuid4().hex}-A1B2")
    validator = MockProviderValidator(
        ("valid", "VALID"), expected_secret=raw_key, block_first=True
    )
    validator.engine = fixture["engine"]
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator

    try:
        with TestClient(app) as client:
            key_id = _add_real_key(client, fixture, raw_key, make_active=False)
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    client.post,
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                assert validator.entered.wait(5)
                with fixture["engine"].connect() as connection:
                    claim = connection.execute(
                        text(
                            "SELECT pk.validation_token IS NOT NULL AS has_token, "
                            "pk.validation_lease_expires_at > clock_timestamp() AS live_lease, "
                            "EXISTS (SELECT 1 FROM vault.decrypted_secrets ds "
                            "WHERE ds.id = pk.vault_secret_id "
                            "AND ds.decrypted_secret = :secret) AS decrypted "
                            "FROM provider_keys pk WHERE pk.id = :key_id"
                        ),
                        {"key_id": key_id, "secret": str(raw_key)},
                    ).one()
                assert claim == (True, True, True)
                assert validator.connection_counts == [0]
                validator.release.set()
                response = pending.result(timeout=5)
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert response.status_code == 200
    assert response.json()["code"] == "VALID"
    state = _validation_state(fixture["engine"], key_id)
    assert state.is_valid is True
    assert state.last_validated_at is not None
    assert state.last_validation_error is None
    assert state.validation_token is None
    assert state.validation_lease_expires_at is None


def test_overlapping_validation_makes_one_provider_request(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"validation-overlap-{uuid4().hex}-C3_D")
    validator = MockProviderValidator(
        ("valid", "VALID"), expected_secret=raw_key, block_first=True
    )
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator

    try:
        with TestClient(app) as first_client, TestClient(app) as second_client:
            key_id = _add_real_key(first_client, fixture, raw_key)
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    first_client.post,
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                assert validator.entered.wait(5)
                overlap = second_client.post(
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                assert validator.calls == 1
                validator.release.set()
                completed = pending.result(timeout=5)
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert overlap.status_code == completed.status_code == 200
    assert overlap.json()["outcome"] == "temporary"
    assert overlap.json()["code"] == "VALIDATION_IN_PROGRESS"
    assert completed.json()["code"] == "VALID"


def test_database_clock_expiry_allows_new_claim_and_stale_token_cannot_overwrite(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"validation-stale-{uuid4().hex}-E5-F")
    validator = MockProviderValidator(
        ("invalid", "INVALID_CREDENTIAL"),
        ("valid", "VALID"),
        expected_secret=raw_key,
        block_first=True,
    )
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator

    try:
        with TestClient(app) as first_client, TestClient(app) as second_client:
            key_id = _add_real_key(first_client, fixture, raw_key)
            with ThreadPoolExecutor(max_workers=1) as executor:
                stale_request = executor.submit(
                    first_client.post,
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                assert validator.entered.wait(5)
                with fixture["engine"].begin() as connection:
                    first_token = connection.execute(
                        text(
                            "UPDATE provider_keys "
                            "SET validation_lease_expires_at = clock_timestamp() - interval '1 second' "
                            "WHERE id = :key_id RETURNING validation_token"
                        ),
                        {"key_id": key_id},
                    ).scalar_one()
                fresh = second_client.post(
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                assert fresh.status_code == 200
                assert fresh.json()["code"] == "VALID"
                assert validator.calls == 2
                with fixture["engine"].connect() as connection:
                    assert connection.execute(
                        text(
                            "SELECT validation_token IS DISTINCT FROM :first_token "
                            "FROM provider_keys WHERE id = :key_id"
                        ),
                        {"key_id": key_id, "first_token": first_token},
                    ).scalar_one()
                validator.release.set()
                stale = stale_request.result(timeout=5)
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert stale.status_code == 200
    assert stale.json()["outcome"] == "temporary"
    assert stale.json()["code"] == "VALIDATION_SUPERSEDED"
    state = _validation_state(fixture["engine"], key_id)
    assert state.is_valid is True
    assert state.is_active is True
    assert state.last_validation_error is None


@pytest.mark.parametrize(
    ("outcome", "code", "expected_valid", "expected_active", "expected_error"),
    [
        ("valid", "VALID", True, True, None),
        ("invalid", "INVALID_CREDENTIAL", False, False, "INVALID_CREDENTIAL"),
    ],
)
def test_completed_validation_persists_only_valid_or_invalid_result(
    provider_fixture,
    outcome,
    code,
    expected_valid,
    expected_active,
    expected_error,
):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"validation-result-{uuid4().hex}-G7_H")
    validator = MockProviderValidator((outcome, code), expected_secret=raw_key)
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator
    try:
        with TestClient(app) as client:
            key_id = _add_real_key(client, fixture, raw_key)
            response = client.post(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                headers=fixture["headers"],
            )
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert response.status_code == 200
    assert response.json()["outcome"] == outcome
    state = _validation_state(fixture["engine"], key_id)
    assert state.is_valid is expected_valid
    assert state.is_active is expected_active
    assert state.last_validation_error == expected_error
    assert state.last_validated_at is not None
    assert state.validation_token is None


def test_temporary_validation_is_a_persistence_noop(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"validation-temporary-{uuid4().hex}-J8_K")
    validator = MockProviderValidator(
        ("temporary", "PROVIDER_UNAVAILABLE"), expected_secret=raw_key
    )
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator
    try:
        with TestClient(app) as client:
            key_id = _add_real_key(client, fixture, raw_key)
            with fixture["engine"].begin() as connection:
                connection.execute(
                    text(
                        "UPDATE provider_keys SET is_valid = true, "
                        "last_validated_at = clock_timestamp() - interval '1 day' "
                        "WHERE id = :key_id"
                    ),
                    {"key_id": key_id},
                )
            before = _validation_state(fixture["engine"], key_id)[:4]
            response = client.post(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                headers=fixture["headers"],
            )
            after = _validation_state(fixture["engine"], key_id)
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert response.status_code == 200
    assert response.json()["outcome"] == "temporary"
    assert after[:4] == before
    assert after.validation_token is None
    assert after.validation_lease_expires_at is None


def test_absent_vault_secret_fences_key_without_provider_call(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"validation-missing-{uuid4().hex}-L9_M")
    validator = MockProviderValidator(("valid", "VALID"), expected_secret=raw_key)
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator
    try:
        with TestClient(app) as client:
            key_id = _add_real_key(client, fixture, raw_key)
            with fixture["engine"].begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM vault.secrets WHERE id = ("
                        "SELECT vault_secret_id FROM provider_keys WHERE id = :key_id)"
                    ),
                    {"key_id": key_id},
                )
            response = client.post(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                headers=fixture["headers"],
            )
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "KEY_CLEANUP_REQUIRED"
    assert validator.calls == 0
    with fixture["engine"].connect() as connection:
        row = connection.execute(
            text(
                "SELECT lifecycle, is_active, validation_token, "
                "validation_lease_expires_at FROM provider_keys WHERE id = :key_id"
            ),
            {"key_id": key_id},
        ).one()
    assert row == ("cleanup_required", False, None, None)


def test_database_pool_lock_and_statement_waits_are_bounded(provider_fixture):
    from backend.app.main import app
    from backend.app.config import load_settings

    fixture = provider_fixture
    engine = fixture["engine"]
    assert engine.pool._timeout <= 2
    with engine.connect() as connection:
        assert connection.execute(text("SHOW lock_timeout")).scalar_one() == "2s"
        assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "2s"

    started = time.monotonic()
    with pytest.raises(DBAPIError):
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_sleep(3)"))
    assert time.monotonic() - started < 3

    pool_engine = create_engine(
        load_settings().database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
        hide_parameters=True,
    )
    try:
        with pool_engine.connect():
            started = time.monotonic()
            with pytest.raises(SQLAlchemyTimeoutError):
                pool_engine.connect()
            assert time.monotonic() - started < 1
    finally:
        pool_engine.dispose()

    raw_key = SecretFixture(f"validation-lock-{uuid4().hex}-N0_P")
    validator = MockProviderValidator(("valid", "VALID"), expected_secret=raw_key)
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator
    try:
        with TestClient(app) as client:
            key_id = _add_real_key(client, fixture, raw_key)
            with engine.connect() as blocker:
                transaction = blocker.begin()
                blocker.execute(
                    text("SELECT id FROM brands WHERE id = :brand_id FOR UPDATE"),
                    {"brand_id": fixture["brand_id"]},
                )
                started = time.monotonic()
                response = client.post(
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                elapsed = time.monotonic() - started
                transaction.rollback()
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert elapsed < 4
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "VAULT_UNAVAILABLE"
    assert validator.calls == 0
    state = _validation_state(engine, key_id)
    assert state.validation_token is None
    assert state.validation_lease_expires_at is None
