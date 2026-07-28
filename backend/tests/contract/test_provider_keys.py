from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from starlette.responses import Response

from backend.app import auth, config, main
from backend.app.auth import CurrentUser, get_current_user
from backend.app.models.provider_key import ProviderKey, ProviderKeyAdd
from backend.app.routes import provider_keys as provider_key_routes
from backend.app.routes.provider_keys import get_provider_key_store
from backend.app.services.brand_store import BrandCleanupRequiredError
from backend.app.services.provider_key_store import (
    IdempotencyKeyRetiredError,
    VaultUnavailableError,
)
from backend.app.services import provider_key_store as provider_key_store_module


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


@dataclass(frozen=True)
class FakeValidationClaim:
    attempted_at: datetime
    key: ProviderKey
    provider: str
    secret: str
    token: UUID
    in_progress: bool = False


@dataclass(frozen=True)
class FakeProviderResult:
    outcome: str
    code: str
    provider_request_id: str | None = None


@dataclass(frozen=True)
class FakeValidationCompletion:
    key: ProviderKey
    superseded: bool


@dataclass
class FakeClock:
    current: float = 10_000.0

    def monotonic(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass
class FakeValidationScenario:
    before: ProviderKey = field(default_factory=_safe_key)
    outcome: str = "valid"
    code: str = "VALID"
    attempted_at: datetime = datetime(2026, 7, 26, 12, tzinfo=UTC)
    raw_key: str = RAW_KEY
    token: UUID = UUID("66666666-6666-6666-6666-666666666666")
    provider_request_id: str | None = "provider-request-id"
    in_progress: bool = False
    superseded: bool = False
    claim_error: Exception | None = None
    clock: FakeClock | None = None
    pool_delay: float = 0
    lock_delay: float = 0
    vault_delay: float = 0
    provider_delay: float = 0
    completion_delay: float = 0
    consumed_stages: list[tuple[str, float]] = field(default_factory=list)

    def consume(self, stage: str, delay: float, deadline: float) -> None:
        self.consumed_stages.append((stage, deadline))
        if self.clock is not None:
            self.clock.advance(delay)

    def consume_claim_budget(self, deadline: float) -> None:
        self.consume("pool", self.pool_delay, deadline)
        self.consume("lock", self.lock_delay, deadline)
        self.consume("vault", self.vault_delay, deadline)

    def completed_key(self, result: FakeProviderResult) -> ProviderKey:
        if result.outcome == "valid":
            return self.before.model_copy(
                update={
                    "is_valid": True,
                    "last_validated_at": self.attempted_at,
                    "last_validation_error": None,
                }
            )
        if result.outcome == "invalid":
            return self.before.model_copy(
                update={
                    "is_active": False,
                    "is_valid": False,
                    "last_validated_at": self.attempted_at,
                    "last_validation_error": "INVALID_CREDENTIAL",
                }
            )
        return self.before


@dataclass
class FakeProviderValidator:
    scenario: FakeValidationScenario
    calls: list[tuple[str, str, float]] = field(default_factory=list)

    async def validate(
        self, provider: str, secret: str, deadline: float
    ) -> FakeProviderResult:
        self.calls.append((provider, secret, deadline))
        self.scenario.consume("provider", self.scenario.provider_delay, deadline)
        return FakeProviderResult(
            outcome=self.scenario.outcome,
            code=self.scenario.code,
            provider_request_id=self.scenario.provider_request_id,
        )


@dataclass
class FakeProviderKeyStore:
    keys: list[ProviderKey] = field(default_factory=list)
    error: Exception | None = None
    add_calls: list[tuple[str, UUID, ProviderKeyAdd, UUID]] = field(default_factory=list)
    activate_calls: list[tuple[str, UUID, UUID]] = field(default_factory=list)
    validation: FakeValidationScenario | None = None
    claim_calls: list[tuple[str, UUID, UUID, float]] = field(default_factory=list)
    complete_calls: list[tuple[str, UUID, UUID, UUID, Any, float]] = field(
        default_factory=list
    )

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

    def activate_key(
        self,
        user_id: str,
        brand_id: UUID,
        key_id: UUID,
    ) -> ProviderKey:
        self.activate_calls.append((user_id, brand_id, key_id))
        if self.error:
            raise self.error
        target = next((key for key in self.keys if key.id == key_id), None)
        if target is None:
            target = _safe_key(id=key_id, is_active=False)
        activated = target.model_copy(update={"is_active": True})
        self.keys = [
            activated
            if key.id == key_id
            else key.model_copy(update={"is_active": False})
            if key.provider == target.provider
            else key
            for key in self.keys
        ]
        return activated

    def claim_validation(
        self,
        user_id: str,
        brand_id: UUID,
        key_id: UUID,
        deadline: float,
    ) -> FakeValidationClaim:
        self.claim_calls.append((user_id, brand_id, key_id, deadline))
        assert self.validation is not None
        self.validation.consume_claim_budget(deadline)
        if self.validation.claim_error:
            raise self.validation.claim_error
        return FakeValidationClaim(
            attempted_at=self.validation.attempted_at,
            key=self.validation.before,
            provider=self.validation.before.provider.value,
            secret=self.validation.raw_key,
            token=self.validation.token,
            in_progress=self.validation.in_progress,
        )

    def complete_validation(
        self,
        user_id: str,
        brand_id: UUID,
        key_id: UUID,
        token: UUID,
        result: FakeProviderResult,
        deadline: float,
    ) -> FakeValidationCompletion:
        self.complete_calls.append(
            (user_id, brand_id, key_id, token, result, deadline)
        )
        assert self.validation is not None
        self.validation.consume("completion", self.validation.completion_delay, deadline)
        if self.validation.superseded:
            return FakeValidationCompletion(self.validation.before, superseded=True)
        return FakeValidationCompletion(self.validation.completed_key(result), superseded=False)


@pytest.fixture
def provider_key_client():
    store = FakeProviderKeyStore()
    scenario = FakeValidationScenario()
    validator = FakeProviderValidator(scenario)
    store.validation = scenario
    store.validator = validator
    main.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="11111111-1111-1111-1111-111111111111",
        email="owner@example.com",
        access_token="redacted",
    )
    main.app.dependency_overrides[get_provider_key_store] = lambda: store
    provider_dependency = getattr(
        provider_key_routes, "get_provider_validator", None
    )
    if provider_dependency is not None:
        main.app.dependency_overrides[provider_dependency] = lambda: store.validator
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


def test_activate_returns_exact_safe_shape_and_accepts_unvalidated_key(
    provider_key_client,
):
    client, store = provider_key_client
    store.keys = [_safe_key(is_active=False, is_valid=None)]

    response = client.patch(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/activate"
    )

    assert response.status_code == 200
    assert response.json() == _safe_key_json(_safe_key(is_active=True, is_valid=None))
    assert store.activate_calls == [
        ("11111111-1111-1111-1111-111111111111", BRAND_ID, KEY_ID)
    ]
    assert store.validator.calls == []
    assert {
        "brand_id",
        "vault_secret_id",
        "lifecycle",
        "validation_token",
        "updated_at",
    }.isdisjoint(response.json())


def test_activate_deactivates_only_prior_key_for_same_provider(provider_key_client):
    client, store = provider_key_client
    prior_id = UUID("77777777-7777-7777-7777-777777777777")
    gemini_id = UUID("88888888-8888-8888-8888-888888888888")
    store.keys = [
        _safe_key(id=KEY_ID, is_active=False),
        _safe_key(id=prior_id, is_active=True),
        _safe_key(id=gemini_id, provider="gemini", is_active=True),
    ]

    response = client.patch(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/activate"
    )

    assert response.status_code == 200
    states = {key.id: key.is_active for key in store.keys}
    assert states == {KEY_ID: True, prior_id: False, gemini_id: True}


@pytest.mark.parametrize(
    ("error_name", "fallback", "code", "message"),
    [
        (
            "KeyInvalidError",
            RuntimeError,
            "KEY_INVALID",
            "Validate this key successfully before activating it.",
        ),
        (
            "KeyCleanupRequiredError",
            RuntimeError,
            "KEY_CLEANUP_REQUIRED",
            "Key cleanup is required. Retry deletion.",
        ),
        (
            "BrandCleanupRequiredError",
            BrandCleanupRequiredError,
            "BRAND_CLEANUP_REQUIRED",
            "Brand cleanup is required. Retry deletion.",
        ),
        (
            "KeyActivationConflictError",
            RuntimeError,
            "BRAND_MUTATION_IN_PROGRESS",
            "A brand update is in progress. Retry shortly.",
        ),
    ],
)
def test_activate_conflicts_use_fixed_safe_envelopes(
    provider_key_client,
    error_name: str,
    fallback: type[Exception],
    code: str,
    message: str,
):
    client, store = provider_key_client
    error_type = (
        BrandCleanupRequiredError
        if error_name == "BrandCleanupRequiredError"
        else getattr(provider_key_store_module, error_name, fallback)
    )
    store.error = error_type()

    response = client.patch(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/activate"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
    assert store.validator.calls == []


@pytest.mark.parametrize("hidden_case", ["missing", "wrong_brand", "not_owned"])
def test_activate_path_membership_is_opaque(provider_key_client, hidden_case: str):
    client, store = provider_key_client
    store.error = LookupError(hidden_case)

    response = client.patch(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/activate"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROVIDER_KEY_NOT_FOUND"
    assert response.json()["error"]["message"] == "Provider key not found."
    assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
    assert store.validator.calls == []


def test_activate_rejects_malformed_path_before_store(provider_key_client):
    client, store = provider_key_client

    response = client.patch(
        f"/api/v1/brands/{BRAND_ID}/keys/not-a-uuid/activate"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert store.activate_calls == []


def _safe_key_json(key: ProviderKey) -> dict[str, Any]:
    return {
        "id": str(key.id),
        "provider": key.provider.value,
        "label": key.label,
        "key_hint": key.key_hint,
        "is_active": key.is_active,
        "is_valid": key.is_valid,
        "last_validated_at": (
            key.last_validated_at.isoformat().replace("+00:00", "Z")
            if key.last_validated_at
            else None
        ),
        "last_validation_error": key.last_validation_error,
        "cleanup_state": key.cleanup_state.value,
        "created_at": key.created_at.isoformat().replace("+00:00", "Z"),
    }


VALIDATION_MATRIX = [
    ("valid", "VALID"),
    ("invalid", "INVALID_CREDENTIAL"),
    ("temporary", "PROVIDER_TIMEOUT"),
    ("temporary", "PROVIDER_UNAVAILABLE"),
    ("temporary", "PROVIDER_RATE_LIMITED"),
    ("temporary", "PROVIDER_PERMISSION"),
    ("temporary", "VALIDATION_UNDETERMINED"),
]


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize(("outcome", "code"), VALIDATION_MATRIX)
def test_validate_returns_exact_outcome_matrix_and_complete_snapshot(
    provider_key_client,
    provider: str,
    outcome: str,
    code: str,
):
    client, store = provider_key_client
    display_name = "OpenAI" if provider == "openai" else "Gemini"
    before = _safe_key(
        provider=provider,
        is_active=True,
        is_valid=False,
        last_validated_at=datetime(2026, 7, 25, 9, tzinfo=UTC),
        last_validation_error="INVALID_CREDENTIAL",
    )
    store.validation = FakeValidationScenario(
        before=before,
        outcome=outcome,
        code=code,
    )
    store.validator.scenario = store.validation

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    expected_message = {
        "valid": f"{display_name} accepted this API key.",
        "invalid": f"{display_name} rejected this API key.",
        "temporary": f"{display_name} could not validate the key right now.",
    }[outcome]
    result = FakeProviderResult(outcome, code)
    expected_key = store.validation.completed_key(result)
    assert response.status_code == 200
    assert response.json() == {
        "outcome": outcome,
        "attempted_at": "2026-07-26T12:00:00Z",
        "code": code,
        "message": expected_message,
        "key": _safe_key_json(expected_key),
    }
    assert store.claim_calls == [
        (
            "11111111-1111-1111-1111-111111111111",
            BRAND_ID,
            KEY_ID,
            store.claim_calls[0][3],
        )
    ]
    assert store.validator.calls[0][:2] == (provider, RAW_KEY)
    assert len(store.complete_calls) == 1
    assert RAW_KEY not in response.text


def test_invalid_validation_deactivates_without_replacement(provider_key_client):
    client, store = provider_key_client
    store.validation = FakeValidationScenario(
        before=_safe_key(is_active=True),
        outcome="invalid",
        code="INVALID_CREDENTIAL",
    )
    store.validator.scenario = store.validation

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == 200
    assert response.json()["key"] == _safe_key_json(
        store.validation.completed_key(
            FakeProviderResult("invalid", "INVALID_CREDENTIAL")
        )
    )
    assert response.json()["key"]["is_active"] is False


@pytest.mark.parametrize(
    "code",
    [
        "PROVIDER_TIMEOUT",
        "PROVIDER_UNAVAILABLE",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_PERMISSION",
        "VALIDATION_UNDETERMINED",
    ],
)
def test_temporary_validation_preserves_complete_snapshot_byte_for_byte(
    provider_key_client, code: str
):
    client, store = provider_key_client
    before = _safe_key(
        is_active=True,
        is_valid=True,
        last_validated_at=datetime(2026, 7, 20, 8, 30, tzinfo=UTC),
        last_validation_error=None,
    )
    store.validation = FakeValidationScenario(
        before=before, outcome="temporary", code=code
    )
    store.validator.scenario = store.validation

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == 200
    assert response.json()["key"] == _safe_key_json(before)
    assert store.complete_calls[0][4].code == code


@pytest.mark.parametrize("hidden_case", ["missing", "wrong_brand", "not_owned"])
def test_validate_path_membership_is_opaque(provider_key_client, hidden_case: str):
    client, store = provider_key_client
    store.validation.claim_error = LookupError(hidden_case)

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROVIDER_KEY_NOT_FOUND"
    assert response.json()["error"]["message"] == "Provider key not found."
    assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
    assert store.validator.calls == []
    assert store.complete_calls == []


@pytest.mark.parametrize(
    ("error_name", "fallback", "status_code", "code", "message"),
    [
        (
            "BrandCleanupRequiredError",
            BrandCleanupRequiredError,
            409,
            "BRAND_CLEANUP_REQUIRED",
            "Brand cleanup is required. Retry deletion.",
        ),
        (
            "KeyCleanupRequiredError",
            RuntimeError,
            409,
            "KEY_CLEANUP_REQUIRED",
            "Key cleanup is required. Retry deletion.",
        ),
        (
            "VaultUnavailableError",
            VaultUnavailableError,
            502,
            "VAULT_UNAVAILABLE",
            "Secure key storage is unavailable right now.",
        ),
    ],
)
def test_validate_prelease_failures_use_fixed_safe_envelopes(
    provider_key_client,
    error_name: str,
    fallback: type[Exception],
    status_code: int,
    code: str,
    message: str,
):
    client, store = provider_key_client
    error_type = getattr(provider_key_store_module, error_name, fallback)
    store.validation.claim_error = error_type()

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    assert response.headers["X-Request-Id"] == response.json()["error"]["request_id"]
    assert store.validator.calls == []
    assert store.complete_calls == []


def test_overlapping_validation_returns_in_progress_without_provider_call(
    provider_key_client,
):
    client, store = provider_key_client
    before = _safe_key(
        is_valid=True,
        last_validated_at=datetime(2026, 7, 24, 10, tzinfo=UTC),
    )
    store.validation = FakeValidationScenario(before=before, in_progress=True)
    store.validator.scenario = store.validation

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "temporary",
        "attempted_at": "2026-07-26T12:00:00Z",
        "code": "VALIDATION_IN_PROGRESS",
        "message": "OpenAI could not validate the key right now.",
        "key": _safe_key_json(before),
    }
    assert store.validator.calls == []
    assert store.complete_calls == []


def test_stale_completion_returns_superseded_latest_snapshot(provider_key_client):
    client, store = provider_key_client
    latest = _safe_key(
        is_active=False,
        is_valid=False,
        last_validated_at=datetime(2026, 7, 26, 11, 59, tzinfo=UTC),
        last_validation_error="INVALID_CREDENTIAL",
    )
    store.validation = FakeValidationScenario(
        before=latest,
        outcome="valid",
        code="VALID",
        superseded=True,
    )
    store.validator.scenario = store.validation

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == 200
    assert response.json() == {
        "outcome": "temporary",
        "attempted_at": "2026-07-26T12:00:00Z",
        "code": "VALIDATION_SUPERSEDED",
        "message": "OpenAI could not validate the key right now.",
        "key": _safe_key_json(latest),
    }
    assert len(store.validator.calls) == 1
    assert len(store.complete_calls) == 1


def test_validation_consumes_one_absolute_budget_across_all_route_stages(
    provider_key_client, monkeypatch: pytest.MonkeyPatch
):
    client, store = provider_key_client
    clock = FakeClock()
    scenario = FakeValidationScenario(
        clock=clock,
        pool_delay=0.7,
        lock_delay=0.8,
        vault_delay=0.9,
        provider_delay=8.5,
        completion_delay=0.8,
    )
    store.validation = scenario
    store.validator.scenario = scenario
    monkeypatch.setattr(main.time, "monotonic", clock.monotonic)

    async def consume_auth_budget(request: Request) -> CurrentUser:
        clock.advance(0.6)
        return CurrentUser(
            user_id="11111111-1111-1111-1111-111111111111",
            email="owner@example.com",
            access_token="redacted",
        )

    main.app.dependency_overrides[get_current_user] = consume_auth_budget
    started = clock.monotonic()
    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate"
    )

    assert response.status_code == 200
    assert clock.monotonic() - started < 15
    deadlines = [deadline for _, deadline in scenario.consumed_stages]
    assert deadlines == [started + 15] * 5
    assert store.claim_calls[0][3] == started + 15
    assert store.validator.calls[0][2] == started + 15
    assert store.complete_calls[0][5] == started + 15


def test_validation_response_and_logs_exclude_every_sensitive_stage_value(
    provider_key_client, caplog: pytest.LogCaptureFixture
):
    client, store = provider_key_client
    sensitive = {
        RAW_KEY,
        "Production Key",
        "***A1B2",
        "77777777-7777-7777-7777-777777777777",
        "secret SQL bind",
        "provider body secret",
        "Bearer secret-token",
        "secret exception text",
        "66666666-6666-6666-6666-666666666666",
        "11111111-1111-1111-1111-111111111111",
        "owner@example.com",
    }
    store.validation.claim_error = VaultUnavailableError(
        "secret exception text; secret SQL bind; provider body secret"
    )
    caplog.set_level(logging.INFO)

    response = client.post(
        f"/api/v1/brands/{BRAND_ID}/keys/{KEY_ID}/validate",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 502
    rendered_logs = "\n".join(
        main._JsonLogFormatter().format(record) for record in caplog.records
    )
    observable = response.text + rendered_logs + caplog.text
    for value in sensitive:
        assert value not in observable


def test_safe_validation_log_contains_only_fixed_allowlisted_metadata():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(main._JsonLogFormatter())
    logger = logging.getLogger("provider-validation-contract")
    logger.handlers = [handler]
    logger.propagate = False
    logger.info(
        "unsafe %s",
        RAW_KEY,
        extra={
            "event": "provider_keys.validation_complete",
            "request_id": "request-id",
            "provider": "gemini",
            "code": "PROVIDER_TIMEOUT",
            "duration_ms": 14900,
            "provider_request_id": "safe-provider-request-id",
            "label": "Production Key",
            "key_hint": "***A1B2",
            "vault_secret_id": "77777777-7777-7777-7777-777777777777",
            "authorization": "Bearer secret-token",
            "exception": "secret exception text",
            "user_id": "11111111-1111-1111-1111-111111111111",
            "email": "owner@example.com",
        },
    )

    assert json.loads(stream.getvalue()) == {
        "level": "INFO",
        "logger": "provider-validation-contract",
        "event": "provider_keys.validation_complete",
        "request_id": "request-id",
        "provider": "gemini",
        "code": "PROVIDER_TIMEOUT",
        "duration_ms": 14900,
        "provider_request_id": "safe-provider-request-id",
    }
