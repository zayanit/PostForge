from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException, Request
from starlette.responses import Response

from backend.app import auth, config, main


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
            supabase_url="http://127.0.0.1:54321",
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
    request.state.validation_deadline = time.monotonic() + 0.03
    started = time.monotonic()

    with pytest.raises(HTTPException):
        asyncio.run(auth.get_current_user(request, "Bearer token"))

    assert time.monotonic() - started < 0.15
