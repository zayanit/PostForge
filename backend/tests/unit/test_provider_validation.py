from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections.abc import Callable, Container

import httpx
import pytest

from backend.app.services.provider_validation import validate_provider_key


OPENAI_URL = "https://api.openai.com/v1/models"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
)
RAW_KEY = "unit-test-provider-secret-A1B2"


def _assert_not_exposed(
    observable: Container[str], *prohibited_values: str
) -> None:
    if any(value in observable for value in prohibited_values):
        raise AssertionError("sensitive value was exposed")


def _validate(
    provider: str,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    timeout: float = 10.0,
):
    return asyncio.run(
        validate_provider_key(
            provider,
            RAW_KEY,
            transport=httpx.MockTransport(handler),
            timeout=timeout,
        )
    )


def _assert_result(
    result,
    outcome: str,
    code: str,
    message: str,
    provider_request_id: str | None = None,
) -> None:
    assert result.outcome == outcome
    assert result.code == code
    assert result.message == message
    assert result.provider_request_id == provider_request_id


def _provider_name(provider: str) -> str:
    return "OpenAI" if provider == "openai" else "Gemini"


def _temporary_message(provider: str) -> str:
    return f"{_provider_name(provider)} could not validate the key right now."


@pytest.mark.parametrize(
    ("provider", "expected_url", "auth_header", "success_body", "provider_name"),
    [
        (
            "openai",
            OPENAI_URL,
            ("authorization", f"Bearer {RAW_KEY}"),
            {"data": []},
            "OpenAI",
        ),
        (
            "gemini",
            GEMINI_URL,
            ("x-goog-api-key", RAW_KEY),
            {"models": []},
            "Gemini",
        ),
    ],
)
def test_uses_exact_official_models_url_and_only_provider_auth_header(
    provider: str,
    expected_url: str,
    auth_header: tuple[str, str],
    success_body: dict[str, list],
    provider_name: str,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=success_body)

    result = _validate(provider, handler)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == expected_url
    assert hmac.compare_digest(request.headers[auth_header[0]], auth_header[1])
    assert ("x-goog-api-key" in request.headers) is (provider == "gemini")
    assert ("authorization" in request.headers) is (provider == "openai")
    _assert_not_exposed(
        request.headers, "openai-organization", "openai-project"
    )
    _assert_not_exposed(str(request.url), RAW_KEY)
    _assert_result(
        result,
        "valid",
        "VALID",
        f"{provider_name} accepted this API key.",
    )


@pytest.mark.parametrize(
    ("provider", "body"),
    [
        ("openai", {"data": {}}),
        ("openai", {"object": "list"}),
        ("gemini", {"models": {}}),
        ("gemini", {"nextPageToken": "next"}),
    ],
)
def test_200_requires_the_provider_specific_list_structure(
    provider: str, body: dict[str, object]
):
    result = _validate(provider, lambda _: httpx.Response(200, json=body))

    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("status_code", [200, 401, 500])
def test_malformed_json_is_temporary(status_code: int):
    result = _validate(
        "openai",
        lambda _: httpx.Response(
            status_code,
            content=b"not-json-provider-secret",
            headers={"content-type": "application/json"},
        ),
    )

    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        "OpenAI could not validate the key right now.",
    )


def test_openai_invalid_requires_exact_nested_error_code_predicate():
    result = _validate(
        "openai",
        lambda _: httpx.Response(
            401,
            json={
                "error": {
                    "message": "Never expose this provider response.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        ),
    )

    _assert_result(
        result,
        "invalid",
        "INVALID_CREDENTIAL",
        "OpenAI rejected this API key.",
    )


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"message": "Incorrect API key provided"}},
        {"error": {"type": "invalid_api_key"}},
        {"error": {"code": "INVALID_API_KEY"}},
        {"error": {"code": "invalid_api_key "}},
        {"code": "invalid_api_key"},
        {"error": "invalid_api_key"},
    ],
)
def test_openai_near_misses_never_invalidate(body: object):
    result = _validate("openai", lambda _: httpx.Response(401, json=body))

    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        "OpenAI could not validate the key right now.",
    )


@pytest.mark.parametrize(
    "reason",
    [
        "API_KEY_INVALID",
        "API_KEY_EXPIRED",
        "API_KEY_NOT_FOUND",
        "INVALID_CREDENTIAL",
    ],
)
def test_gemini_invalid_accepts_every_exact_documented_error_info_reason(reason: str):
    result = _validate(
        "gemini",
        lambda _: httpx.Response(
            400,
            json={
                "error": {
                    "details": [
                        {"@type": "type.googleapis.com/google.rpc.Help"},
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": reason,
                        },
                    ]
                }
            },
        ),
    )

    _assert_result(
        result,
        "invalid",
        "INVALID_CREDENTIAL",
        "Gemini rejected this API key.",
    )


@pytest.mark.parametrize(
    "detail",
    [
        {"reason": "API_KEY_INVALID"},
        {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": "api_key_invalid",
        },
        {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": "API_KEY_INVALID ",
        },
        {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": "ACCESS_TOKEN_EXPIRED",
        },
        {
            "@type": "type.googleapis.com/google.rpc.Help",
            "reason": "API_KEY_INVALID",
        },
    ],
)
def test_gemini_near_misses_never_invalidate(detail: dict[str, str]):
    result = _validate(
        "gemini",
        lambda _: httpx.Response(
            400,
            json={"error": {"message": "API key not valid", "details": [detail]}},
        ),
    )

    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        "Gemini could not validate the key right now.",
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("status_code", [400, 401])
def test_ambiguous_client_statuses_are_undetermined(
    provider: str, status_code: int
):
    result = _validate(
        provider,
        lambda _: httpx.Response(
            status_code,
            json={"error": {"message": "ambiguous provider response"}},
        ),
    )

    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("status_code", [403, 412])
def test_permission_and_precondition_are_not_invalid(
    provider: str, status_code: int
):
    result = _validate(
        provider,
        lambda _: httpx.Response(
            status_code,
            json={"error": {"message": "forbidden", "status": "PERMISSION_DENIED"}},
        ),
    )

    _assert_result(
        result,
        "temporary",
        "PROVIDER_PERMISSION",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("status_code", [429])
def test_quota_and_rate_limit_status_is_temporary_rate_limited(
    provider: str, status_code: int
):
    result = _validate(
        provider,
        lambda _: httpx.Response(
            status_code,
            json={"error": {"code": "insufficient_quota"}},
        ),
    )

    _assert_result(
        result,
        "temporary",
        "PROVIDER_RATE_LIMITED",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_service_statuses_are_temporary_unavailable(
    provider: str, status_code: int
):
    result = _validate(
        provider,
        lambda _: httpx.Response(status_code, json={"error": "service failure"}),
    )

    _assert_result(
        result,
        "temporary",
        "PROVIDER_UNAVAILABLE",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_unknown_status_is_temporary_undetermined(provider: str):
    result = _validate(
        provider,
        lambda _: httpx.Response(418, json={"error": "unknown"}),
    )

    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_redirect_is_not_followed_or_retried(provider: str):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            307,
            headers={"location": "https://attacker.invalid/collect"},
        )

    result = _validate(provider, handler)

    assert len(requests) == 1
    _assert_result(
        result,
        "temporary",
        "VALIDATION_UNDETERMINED",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_network_error_is_unavailable_and_is_not_retried(provider: str):
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ConnectError(
            f"connection failed with {RAW_KEY}", request=request
        )

    result = _validate(provider, handler)

    assert request_count == 1
    _assert_result(
        result,
        "temporary",
        "PROVIDER_UNAVAILABLE",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_timeout_is_classified_separately_and_receives_requested_budget(provider: str):
    observed_timeout: dict[str, float] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeout.update(request.extensions["timeout"])
        raise httpx.ReadTimeout(
            f"timed out while using {RAW_KEY}", request=request
        )

    result = _validate(provider, handler, timeout=3.25)

    assert observed_timeout == {
        "connect": 3.25,
        "read": 3.25,
        "write": 3.25,
        "pool": 3.25,
    }
    _assert_result(
        result,
        "temporary",
        "PROVIDER_TIMEOUT",
        _temporary_message(provider),
    )


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_extracts_provider_request_id_only_from_response_header(provider: str):
    result = _validate(
        provider,
        lambda _: httpx.Response(
            200,
            headers={"x-request-id": "provider-request-123"},
            json={
                "data" if provider == "openai" else "models": [],
                "request_id": "body-request-id-must-be-ignored",
            },
        ),
    )

    _assert_result(
        result,
        "valid",
        "VALID",
        f"{'OpenAI' if provider == 'openai' else 'Gemini'} accepted this API key.",
        f"sha256:{hashlib.sha256(b'provider-request-123').hexdigest()[:16]}",
    )


def test_provider_request_id_cannot_echo_the_raw_key():
    result = _validate(
        "openai",
        lambda _: httpx.Response(
            200,
            headers={"x-request-id": RAW_KEY},
            json={"data": []},
        ),
    )

    assert result.provider_request_id is None
    _assert_not_exposed(repr(result), RAW_KEY)


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_provider_body_headers_key_and_exception_text_are_not_logged_or_returned(
    provider: str, caplog: pytest.LogCaptureFixture
):
    provider_body_secret = "provider-body-secret-Z9Y8"
    authorization_value = f"Bearer {RAW_KEY}"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") in (None, authorization_value)
        return httpx.Response(
            401,
            headers={
                "x-provider-debug": provider_body_secret,
                "x-request-id": "safe-request-id",
            },
            json={
                "error": {
                    "message": provider_body_secret,
                    "debug_authorization": authorization_value,
                }
            },
        )

    with caplog.at_level(logging.DEBUG):
        result = _validate(provider, handler)

    rendered_logs = "\n".join(caplog.messages)
    rendered_result = repr(result)
    _assert_not_exposed(
        rendered_logs, RAW_KEY, authorization_value, provider_body_secret
    )
    _assert_not_exposed(
        rendered_result, RAW_KEY, authorization_value, provider_body_secret
    )
    assert result.provider_request_id == (
        f"sha256:{hashlib.sha256(b'safe-request-id').hexdigest()[:16]}"
    )
