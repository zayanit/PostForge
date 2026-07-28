from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from starlette.responses import Response

from backend.app import auth, config, main
from backend.app.auth import CurrentUser, get_current_user
from backend.app.models.provider_key import ProviderKey, ProviderKeyAdd
from backend.app.routes.provider_keys import get_provider_key_store
from backend.app.services.brand_store import BrandCleanupRequiredError
from backend.app.services.provider_key_store import (
    IdempotencyKeyRetiredError,
    VaultUnavailableError,
)


def _request(path: str = "/api/v1/brands/brand-id/keys/key-id/validate") -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


def test_validation_route_gets_absolute_deadline_before_request_handling():
    request = _request()
    observed: dict[str, float | None] = {}
    before = time.monotonic()

    async def call_next(incoming: Request) -> Response:
        observed["deadline"] = main.get_validation_deadline(incoming)
        return Response(status_code=204)

    response = asyncio.run(main.request_context_middleware(request, call_next))

    assert response.status_code == 204
    assert observed["deadline"] is not None
    assert before + 14.9 <= observed["deadline"] <= before + 15.1


def test_non_validation_route_has_no_validation_deadline():
    request = _request("/api/v1/brands/brand-id/keys")

    async def call_next(incoming: Request) -> Response:
        assert main.get_validation_deadline(incoming) is None
        return Response(status_code=204)

    asyncio.run(main.request_context_middleware(request, call_next))


@pytest.mark.parametrize(
    ("status_code", "code", "message"),
    [
        (409, "KEY_CLEANUP_REQUIRED", "Key cleanup is required. Retry deletion."),
        (409, "BRAND_CLEANUP_REQUIRED", "Brand cleanup is required. Retry deletion."),
        (503, "KEY_CLEANUP_REQUIRED", "Key cleanup did not complete. Retry deletion."),
        (503, "BRAND_CLEANUP_REQUIRED", "Brand cleanup did not complete. Retry deletion."),
    ],
)
def test_fixed_cleanup_errors_have_safe_message_and_request_id_parity(
    status_code: int,
    code: str,
    message: str,
):
    request = _request()
    request.state.request_id = "11111111-1111-1111-1111-111111111111"

    response = main.safe_error_response(request, status_code, code)
    body = json.loads(response.body)

    assert response.status_code == status_code
    assert body == {
        "error": {
            "code": code,
            "message": message,
            "request_id": "11111111-1111-1111-1111-111111111111",
        }
    }
    assert response.headers["X-Request-Id"] == body["error"]["request_id"]


def test_json_log_formatter_allows_only_audited_safe_fields():
    raw_key = "provider-secret-A1B2"
    record = logging.LogRecord(
        "provider_keys",
        logging.INFO,
        __file__,
        1,
        "provider validation failed: %s",
        (raw_key,),
        None,
    )
    record.event = "provider_key_validation"
    record.request_id = "request-id"
    record.provider = "openai"
    record.code = "VALID"
    record.duration_ms = 42
    record.provider_request_id = "provider-request-id"
    record.body = {"key": raw_key}
    record.label = "Production Key"
    record.key_hint = "***A1B2"
    record.vault_secret_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    record.sql_parameters = {"secret": raw_key}
    record.provider_body = f'{{"key":"{raw_key}"}}'
    record.authorization = f"Bearer {raw_key}"
    record.exception = f"failed with {raw_key}"
    record.user_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    record.email = "owner@example.com"

    rendered = main._JsonLogFormatter().format(record)

    assert json.loads(rendered) == {
        "level": "INFO",
        "logger": "provider_keys",
        "event": "provider_key_validation",
        "request_id": "request-id",
        "provider": "openai",
        "code": "VALID",
        "duration_ms": 42,
        "provider_request_id": "provider-request-id",
    }
    for secret in (
        raw_key,
        "Production Key",
        "***A1B2",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "Bearer",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "owner@example.com",
    ):
        assert secret not in rendered


def test_engine_hides_parameters_and_bounds_database_waits(monkeypatch: pytest.MonkeyPatch):
    create_engine = Mock(return_value=Mock())
    monkeypatch.setattr(config, "create_engine", create_engine)
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: SimpleNamespace(database_url="postgresql://backend:secret@db/postgres"),
    )
    config.get_engine.cache_clear()

    try:
        config.get_engine()
    finally:
        config.get_engine.cache_clear()

    _, kwargs = create_engine.call_args
    assert kwargs["hide_parameters"] is True
    assert kwargs["pool_timeout"] == 2
    assert kwargs["connect_args"]["connect_timeout"] == 2
    assert "statement_timeout=2000" in kwargs["connect_args"]["options"]
    assert "lock_timeout=2000" in kwargs["connect_args"]["options"]


def test_database_privilege_assertion_fails_closed_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: SimpleNamespace(database_url=None),
    )
    get_engine = Mock(side_effect=RuntimeError("DATABASE_URL is required"))
    monkeypatch.setattr(config, "get_engine", get_engine)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        config.assert_database_role_privileges()

    get_engine.assert_called_once_with()


def test_startup_invokes_database_privilege_assertion(monkeypatch: pytest.MonkeyPatch):
    assertion = Mock()
    monkeypatch.setattr(main, "assert_database_role_privileges", assertion)

    async def start_and_stop() -> None:
        async with main._lifespan(main.app):
            pass

    asyncio.run(start_and_stop())

    assertion.assert_called_once_with()


def test_database_privilege_assertion_rejects_client_or_underprivileged_role(
    monkeypatch: pytest.MonkeyPatch,
):
    connection = Mock()
    connection.execute.return_value.mappings.return_value.one.return_value = {
        "role_name": "authenticated",
        "is_superuser": False,
        "role_is_private": False,
        "can_bypass_forced_rls": False,
        "application_dml": False,
        "vault_schema_usage": False,
        "vault_create": False,
        "vault_decrypt": False,
        "vault_secret_select": False,
        "vault_secret_delete": False,
        "vault_least_privilege": False,
    }
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://db/postgres",
            supabase_url="https://hosted.supabase.co",
        ),
    )
    monkeypatch.setattr(config, "get_engine", lambda: engine)

    with pytest.raises(RuntimeError, match="database role lacks required backend privileges"):
        config.assert_database_role_privileges()


@pytest.mark.parametrize(
    ("role_name", "is_superuser"),
    [("postgres", True), ("service_role", False)],
)
def test_hosted_database_privilege_assertion_rejects_broad_or_client_roles(
    monkeypatch: pytest.MonkeyPatch,
    role_name: str,
    is_superuser: bool,
):
    privileges = {
        "role_name": role_name,
        "is_superuser": is_superuser,
        "role_is_private": role_name != "service_role",
        "can_bypass_forced_rls": True,
        "application_dml": True,
        "vault_schema_usage": True,
        "vault_create": True,
        "vault_decrypt": True,
        "vault_secret_select": True,
        "vault_secret_delete": True,
        "vault_least_privilege": False,
    }
    connection = Mock()
    connection.execute.return_value.mappings.return_value.one.return_value = privileges
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://db/postgres",
            supabase_url="https://hosted.supabase.co",
        ),
    )
    monkeypatch.setattr(config, "get_engine", lambda: engine)

    with pytest.raises(RuntimeError, match="database role lacks required backend privileges"):
        config.assert_database_role_privileges()


def test_local_postgres_privilege_assertion_allows_documented_exception(
    monkeypatch: pytest.MonkeyPatch,
):
    privileges = {
        "role_name": "postgres",
        "is_superuser": False,
        "role_is_private": True,
        "can_bypass_forced_rls": True,
        "application_dml": True,
        "vault_schema_usage": True,
        "vault_create": True,
        "vault_decrypt": True,
        "vault_secret_select": True,
        "vault_secret_delete": True,
        "vault_least_privilege": False,
    }
    connection = Mock()
    connection.execute.return_value.mappings.return_value.one.return_value = privileges
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://localhost/postgres",
            supabase_url="https://hosted.supabase.co",
        ),
    )
    monkeypatch.setattr(config, "get_engine", lambda: engine)

    config.assert_database_role_privileges()


def test_jwks_timeout_uses_remaining_validation_budget_only(
    monkeypatch: pytest.MonkeyPatch,
):
    created_timeouts: list[float] = []

    class FakeJWKClient:
        def __init__(self, uri: str, **kwargs):
            created_timeouts.append(kwargs.get("timeout", 30))

        def get_signing_key_from_jwt(self, token: str):
            raise auth.jwt.PyJWTError

    monkeypatch.setattr(auth, "PyJWKClient", FakeJWKClient)
    monkeypatch.setattr(
        auth,
        "load_settings",
        lambda: SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_jwt_secret="unused",
        ),
    )
    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda token: {"alg": "ES256"})
    auth._get_cached_jwks_client.cache_clear()

    validation_request = _request()
    validation_request.state.validation_deadline = time.monotonic() + 0.5
    with pytest.raises(HTTPException):
        asyncio.run(auth.get_current_user(validation_request, "Bearer token"))

    normal_request = _request("/api/v1/me")
    with pytest.raises(HTTPException):
        asyncio.run(auth.get_current_user(normal_request, "Bearer token"))

    assert 0 < created_timeouts[0] <= 0.5
    assert created_timeouts[1] == 30
    auth._get_cached_jwks_client.cache_clear()


def test_expired_validation_budget_skips_jwks_fetch(monkeypatch: pytest.MonkeyPatch):
    client = Mock()
    monkeypatch.setattr(auth, "PyJWKClient", client)
    monkeypatch.setattr(
        auth,
        "load_settings",
        lambda: SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_jwt_secret="unused",
        ),
    )
    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda token: {"alg": "ES256"})
    request = _request()
    request.state.validation_deadline = time.monotonic() - 0.01

    with pytest.raises(HTTPException):
        asyncio.run(auth.get_current_user(request, "Bearer token"))

    client.assert_not_called()


def test_expired_validation_budget_skips_hs256_decode(monkeypatch: pytest.MonkeyPatch):
    decode = Mock()
    monkeypatch.setattr(auth.jwt, "decode", decode)
    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda token: {"alg": "HS256"})
    monkeypatch.setattr(
        auth,
        "load_settings",
        lambda: SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_jwt_secret="unused",
        ),
    )
    request = _request()
    request.state.validation_deadline = time.monotonic() - 0.01

    with pytest.raises(HTTPException):
        asyncio.run(auth.get_current_user(request, "Bearer token"))

    decode.assert_not_called()


def test_validation_budget_bounds_total_jwks_work(monkeypatch: pytest.MonkeyPatch):
    class SlowJWKClient:
        def __init__(self, uri: str, **kwargs):
            pass

        def get_signing_key_from_jwt(self, token: str):
            time.sleep(0.2)
            raise auth.jwt.PyJWTError

    async def slow_to_thread(function, *args):
        await asyncio.sleep(0.2)
        return function(*args)

    monkeypatch.setattr(auth, "PyJWKClient", SlowJWKClient)
    monkeypatch.setattr(asyncio, "to_thread", slow_to_thread)
    monkeypatch.setattr(
        auth,
        "load_settings",
        lambda: SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_jwt_secret="unused",
        ),
    )
    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda token: {"alg": "ES256"})
    request = _request()
    request.state.validation_deadline = time.monotonic() + 0.1
    started = time.monotonic()

    with pytest.raises(HTTPException):
        asyncio.run(auth.get_current_user(request, "Bearer token"))

    assert time.monotonic() - started < 0.5


BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
KEY_ID = UUID("33333333-3333-3333-3333-333333333333")
REQUEST_ID = UUID("44444444-4444-4444-4444-444444444444")
RAW_KEY = "contract-provider-secret-A1B2"


def _safe_key(**updates) -> ProviderKey:
    values = {
        "id": KEY_ID,
        "provider": "openai",
        "label": "Production Key",
        "key_hint": "***A1B2",
        "is_active": True,
        "is_valid": None,
        "last_validated_at": None,
        "last_validation_error": None,
        "cleanup_state": "normal",
        "created_at": datetime(2026, 7, 26, 11, tzinfo=UTC),
    }
    values.update(updates)
    return ProviderKey.model_validate(values)


@dataclass
class FakeProviderKeyStore:
    keys: list[ProviderKey] = field(default_factory=list)
    error: Exception | None = None
    add_calls: list[tuple[str, UUID, ProviderKeyAdd, UUID]] = field(default_factory=list)

    def list_keys(self, user_id: str, brand_id: UUID) -> list[ProviderKey]:
        if self.error:
            raise self.error
        return self.keys

    def add_key(
        self,
        user_id: str,
        brand_id: UUID,
        payload: ProviderKeyAdd,
        idempotency_key: UUID,
    ) -> ProviderKey:
        self.add_calls.append((user_id, brand_id, payload, idempotency_key))
        if self.error:
            raise self.error
        return self.keys[0] if self.keys else _safe_key(is_active=payload.make_active)


@pytest.fixture
def provider_key_client():
    store = FakeProviderKeyStore()
    main.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="redacted",
    )
    main.app.dependency_overrides[get_provider_key_store] = lambda: store
    try:
        with TestClient(main.app) as client:
            yield client, store
    finally:
        main.app.dependency_overrides.clear()


def test_list_keys_returns_exact_empty_and_populated_safe_shapes(provider_key_client):
    client, store = provider_key_client
    empty = client.get(f"/api/v1/brands/{BRAND_ID}/keys")
    store.keys = [_safe_key()]
    populated = client.get(f"/api/v1/brands/{BRAND_ID}/keys")

    assert empty.status_code == 200
    assert empty.json() == {"keys": []}
    assert populated.status_code == 200
    assert populated.json() == {
        "keys": [
            {
                "id": str(KEY_ID),
                "provider": "openai",
                "label": "Production Key",
                "key_hint": "***A1B2",
                "is_active": True,
                "is_valid": None,
                "last_validated_at": None,
                "last_validation_error": None,
                "cleanup_state": "normal",
                "created_at": "2026-07-26T11:00:00Z",
            }
        ]
    }
    forbidden = {"brand_id", "vault_secret_id", "lifecycle", "validation_token", "updated_at"}
    assert forbidden.isdisjoint(populated.json()["keys"][0])


@pytest.mark.parametrize("make_active", [None, True, False])
def test_add_key_defaults_active_and_returns_only_safe_shape(provider_key_client, make_active):
    client, store = provider_key_client
    body = {"provider": "openai", "key": RAW_KEY, "label": "Production Key"}
    if make_active is not None:
        body["make_active"] = make_active

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys",
        headers={"Idempotency-Key": str(REQUEST_ID)},
        json=body,
    )

    expected_active = True if make_active is None else make_active
    assert response.status_code == 201
    assert response.json()["is_active"] is expected_active
    assert response.json()["key_hint"] == "***A1B2"
    assert RAW_KEY not in response.text
    assert store.add_calls[0][2].key == RAW_KEY
    assert store.add_calls[0][2].make_active is expected_active
    assert store.add_calls[0][3] == REQUEST_ID


@pytest.mark.parametrize("header", [None, "not-a-uuid"])
def test_add_key_requires_uuid_idempotency_header(provider_key_client, header):
    client, store = provider_key_client
    headers = {} if header is None else {"Idempotency-Key": header}
    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys",
        headers=headers,
        json={"provider": "openai", "key": RAW_KEY},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
    assert store.add_calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "unsupported", "key": RAW_KEY},
        {"provider": "openai", "key": ""},
        {"provider": "openai", "key": "     "},
        {"provider": "openai", "key": "abcd"},
        {"provider": "openai", "key": "secret-ab!?"},
        {"provider": "openai", "key": RAW_KEY, "label": "x" * 101},
        {"provider": "openai", "key": RAW_KEY, "label": f"contains {RAW_KEY}"},
    ],
)
def test_add_key_rejects_invalid_raw_request_before_store(provider_key_client, body):
    client, store = provider_key_client
    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys",
        headers={"Idempotency-Key": str(REQUEST_ID)},
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert RAW_KEY not in response.text
    assert store.add_calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code", "message"),
    [
        (LookupError(), 404, "BRAND_NOT_FOUND", "Brand not found."),
        (
            BrandCleanupRequiredError(),
            409,
            "BRAND_CLEANUP_REQUIRED",
            "Brand cleanup is required. Retry deletion.",
        ),
        (
            IdempotencyKeyRetiredError(),
            409,
            "IDEMPOTENCY_KEY_RETIRED",
            "This add request was already completed and deleted. Use a new request ID.",
        ),
        (
            VaultUnavailableError(),
            502,
            "VAULT_UNAVAILABLE",
            "Secure key storage is unavailable right now.",
        ),
    ],
)
def test_provider_key_errors_use_exact_safe_envelopes(
    provider_key_client, error, status_code, code, message
):
    client, store = provider_key_client
    store.error = error
    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys",
        headers={"Idempotency-Key": str(REQUEST_ID)},
        json={"provider": "gemini", "key": RAW_KEY},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
    assert RAW_KEY not in response.text


def test_opaque_brand_error_is_identical_for_list_and_add(provider_key_client):
    client, store = provider_key_client
    store.error = LookupError()
    list_response = client.get(f"/api/v1/brands/{BRAND_ID}/keys")
    add_response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys",
        headers={"Idempotency-Key": str(REQUEST_ID)},
        json={"provider": "openai", "key": RAW_KEY},
    )

    for response in (list_response, add_response):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BRAND_NOT_FOUND"
        assert response.json()["error"]["message"] == "Brand not found."


def test_response_model_filters_internal_store_fields(provider_key_client):
    client, store = provider_key_client
    store.keys = [
        {
            **_safe_key().model_dump(),
            "brand_id": BRAND_ID,
            "vault_secret_id": UUID("55555555-5555-5555-5555-555555555555"),
            "lifecycle": "normal",
            "raw_key": RAW_KEY,
        }
    ]
    response = client.get(f"/api/v1/brands/{BRAND_ID}/keys")

    assert response.status_code == 200
    assert RAW_KEY not in response.text
    assert "vault_secret_id" not in response.text


def test_add_uses_no_provider_client_dependency(provider_key_client):
    client, _ = provider_key_client
    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys",
        headers={"Idempotency-Key": str(REQUEST_ID)},
        json={"provider": "openai", "key": RAW_KEY},
    )
    assert response.status_code == 201
