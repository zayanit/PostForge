from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx

from ..models.provider_key import (
    Provider,
    ProviderValidationCode,
    ProviderValidationOutcome,
)


_OPENAI_URL = "https://api.openai.com/v1/models"
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
)
_ERROR_INFO_TYPE = "type.googleapis.com/google.rpc.ErrorInfo"
_GEMINI_INVALID_REASONS = frozenset(
    {
        "API_KEY_INVALID",
        "API_KEY_EXPIRED",
        "API_KEY_NOT_FOUND",
        "INVALID_CREDENTIAL",
    }
)


@dataclass(frozen=True, slots=True, repr=False)
class ProviderValidationResult:
    outcome: ProviderValidationOutcome
    code: ProviderValidationCode
    message: str
    provider_request_id: str | None = None

    def __repr__(self) -> str:
        return (
            "ProviderValidationResult("
            f"outcome={self.outcome.value!r}, code={self.code.value!r}, "
            f"message={self.message!r}, "
            f"provider_request_id={self.provider_request_id!r})"
        )


def _provider_details(provider: Provider) -> tuple[str, str, dict[str, str], str]:
    if provider is Provider.OPENAI:
        return "OpenAI", _OPENAI_URL, {}, "data"
    return "Gemini", _GEMINI_URL, {}, "models"


def _result(
    provider_name: str,
    outcome: ProviderValidationOutcome,
    code: ProviderValidationCode,
    provider_request_id: str | None = None,
) -> ProviderValidationResult:
    if outcome is ProviderValidationOutcome.VALID:
        message = f"{provider_name} accepted this API key."
    elif outcome is ProviderValidationOutcome.INVALID:
        message = f"{provider_name} rejected this API key."
    else:
        message = f"{provider_name} could not validate the key right now."
    return ProviderValidationResult(outcome, code, message, provider_request_id)


def _request_id(response: httpx.Response, raw_key: str) -> str | None:
    value = response.headers.get("x-request-id")
    if value is None or raw_key in value or len(value) > 512:
        return None
    # Provider headers are untrusted. Preserve correlation without logging raw content.
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _is_openai_invalid(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    error = body.get("error")
    return isinstance(error, dict) and error.get("code") == "invalid_api_key"


def _is_gemini_invalid(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    error = body.get("error")
    if not isinstance(error, dict):
        return False
    details = error.get("details")
    if not isinstance(details, list):
        return False
    return any(
        isinstance(detail, dict)
        and detail.get("@type") == _ERROR_INFO_TYPE
        and detail.get("reason") in _GEMINI_INVALID_REASONS
        for detail in details
    )


async def validate_provider_key(
    provider: Provider | str,
    raw_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 10.0,
) -> ProviderValidationResult:
    selected_provider = Provider(provider)
    provider_name, url, headers, list_field = _provider_details(selected_provider)
    if selected_provider is Provider.OPENAI:
        headers["Authorization"] = f"Bearer {raw_key}"
    else:
        headers["x-goog-api-key"] = raw_key

    request_timeout = min(10.0, timeout)
    if request_timeout <= 0:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.PROVIDER_TIMEOUT,
        )

    try:
        async with httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=request_timeout,
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.PROVIDER_TIMEOUT,
        )
    except httpx.RequestError:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.PROVIDER_UNAVAILABLE,
        )

    provider_request_id = _request_id(response, raw_key)
    try:
        body = response.json()
    except ValueError:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.VALIDATION_UNDETERMINED,
            provider_request_id,
        )

    if 200 <= response.status_code < 300:
        if isinstance(body, dict) and isinstance(body.get(list_field), list):
            return _result(
                provider_name,
                ProviderValidationOutcome.VALID,
                ProviderValidationCode.VALID,
                provider_request_id,
            )
    elif selected_provider is Provider.OPENAI and _is_openai_invalid(body):
        return _result(
            provider_name,
            ProviderValidationOutcome.INVALID,
            ProviderValidationCode.INVALID_CREDENTIAL,
            provider_request_id,
        )
    elif selected_provider is Provider.GEMINI and _is_gemini_invalid(body):
        return _result(
            provider_name,
            ProviderValidationOutcome.INVALID,
            ProviderValidationCode.INVALID_CREDENTIAL,
            provider_request_id,
        )
    elif response.status_code in {403, 412}:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.PROVIDER_PERMISSION,
            provider_request_id,
        )
    elif response.status_code == 429:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.PROVIDER_RATE_LIMITED,
            provider_request_id,
        )
    elif response.status_code in {500, 502, 503, 504}:
        return _result(
            provider_name,
            ProviderValidationOutcome.TEMPORARY,
            ProviderValidationCode.PROVIDER_UNAVAILABLE,
            provider_request_id,
        )

    return _result(
        provider_name,
        ProviderValidationOutcome.TEMPORARY,
        ProviderValidationCode.VALIDATION_UNDETERMINED,
        provider_request_id,
    )


@dataclass(frozen=True, slots=True, repr=False)
class ProviderValidator:
    transport: httpx.AsyncBaseTransport | None = None

    def __repr__(self) -> str:
        return "<ProviderValidator redacted>"

    async def validate(
        self, provider: Provider | str, secret: str, deadline: float
    ) -> ProviderValidationResult:
        remaining = deadline - time.monotonic()
        return await validate_provider_key(
            provider,
            secret,
            transport=self.transport,
            # Leave time for the fenced database completion and serialization.
            timeout=min(10.0, remaining - 2.25),
        )


@lru_cache(maxsize=1)
def get_provider_validator() -> ProviderValidator:
    return ProviderValidator()
