from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from ..auth import CurrentUserDep
from ..models.provider_key import (
    IdempotencyKey,
    Provider,
    ProviderKey,
    ProviderKeyAdd,
    ProviderKeyListResponse,
    ProviderKeyValidationResponse,
    ProviderValidationCode,
    ProviderValidationOutcome,
)
from ..services.brand_store import BrandCleanupRequiredError
from ..services.provider_key_store import (
    IdempotencyKeyRetiredError,
    KeyActivationConflictError,
    KeyCleanupRequiredError,
    KeyInvalidError,
    ProviderKeyStore,
    VaultUnavailableError,
    get_provider_key_store,
)
from ..services.provider_validation import ProviderValidator, get_provider_validator


router = APIRouter(prefix="/api/v1/brands", tags=["provider-keys"])
logger = logging.getLogger(__name__)

ProviderKeyStoreDep = Annotated[ProviderKeyStore, Depends(get_provider_key_store)]
ProviderValidatorDep = Annotated[ProviderValidator, Depends(get_provider_validator)]
IdempotencyKeyHeader = Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]
_T = TypeVar("_T")


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _not_found() -> HTTPException:
    return _error(status.HTTP_404_NOT_FOUND, "BRAND_NOT_FOUND", "Brand not found.")


def _validation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return _error(
            status.HTTP_404_NOT_FOUND,
            "PROVIDER_KEY_NOT_FOUND",
            "Provider key not found.",
        )
    if isinstance(exc, BrandCleanupRequiredError):
        return _error(
            status.HTTP_409_CONFLICT,
            "BRAND_CLEANUP_REQUIRED",
            "Brand cleanup is required. Retry deletion.",
        )
    if isinstance(exc, KeyCleanupRequiredError):
        return _error(
            status.HTTP_409_CONFLICT,
            "KEY_CLEANUP_REQUIRED",
            "Key cleanup is required. Retry deletion.",
        )
    return _error(
        status.HTTP_502_BAD_GATEWAY,
        "VAULT_UNAVAILABLE",
        "Secure key storage is unavailable right now.",
    )


def _activation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return _error(
            status.HTTP_404_NOT_FOUND,
            "PROVIDER_KEY_NOT_FOUND",
            "Provider key not found.",
        )
    if isinstance(exc, BrandCleanupRequiredError):
        return _error(
            status.HTTP_409_CONFLICT,
            "BRAND_CLEANUP_REQUIRED",
            "Brand cleanup is required. Retry deletion.",
        )
    if isinstance(exc, KeyCleanupRequiredError):
        return _error(
            status.HTTP_409_CONFLICT,
            "KEY_CLEANUP_REQUIRED",
            "Key cleanup is required. Retry deletion.",
        )
    if isinstance(exc, KeyInvalidError):
        return _error(
            status.HTTP_409_CONFLICT,
            "KEY_INVALID",
            "Validate this key successfully before activating it.",
        )
    return _error(
        status.HTTP_409_CONFLICT,
        "BRAND_MUTATION_IN_PROGRESS",
        "A brand update is in progress. Retry shortly.",
    )


async def _within_deadline(awaitable: Awaitable[_T], deadline: float) -> _T:
    remaining = max(0.0, deadline - time.monotonic())
    return await asyncio.wait_for(awaitable, timeout=remaining)


def _validation_message(provider: Provider | str, outcome: str) -> str:
    provider_name = "OpenAI" if Provider(provider) is Provider.OPENAI else "Gemini"
    if outcome == ProviderValidationOutcome.VALID.value:
        return f"{provider_name} accepted this API key."
    if outcome == ProviderValidationOutcome.INVALID.value:
        return f"{provider_name} rejected this API key."
    return f"{provider_name} could not validate the key right now."


def _validation_response(
    *,
    claim,
    outcome: ProviderValidationOutcome | str,
    code: ProviderValidationCode | str,
    key: ProviderKey,
) -> ProviderKeyValidationResponse:
    outcome_value = (
        outcome.value if isinstance(outcome, ProviderValidationOutcome) else outcome
    )
    return ProviderKeyValidationResponse(
        outcome=outcome,
        attempted_at=claim.attempted_at,
        code=code,
        message=_validation_message(claim.provider, outcome_value),
        key=key,
    )


def _log_validation(
    request: Request,
    provider: Provider | str,
    code: ProviderValidationCode | str,
    started: float,
    provider_request_id: str | None = None,
) -> None:
    extra = {
        "event": "provider_keys.validation_complete",
        "request_id": getattr(request.state, "request_id", "unknown"),
        "provider": provider.value if isinstance(provider, Provider) else provider,
        "code": code.value if isinstance(code, ProviderValidationCode) else code,
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
    }
    if provider_request_id is not None:
        extra["provider_request_id"] = provider_request_id
    logger.info("provider_keys.validation_complete", extra=extra)


@router.get("/{brand_id}/keys", response_model=ProviderKeyListResponse)
def list_provider_keys(
    request: Request,
    brand_id: UUID,
    current_user: CurrentUserDep,
    provider_key_store: ProviderKeyStoreDep,
) -> ProviderKeyListResponse:
    try:
        keys = provider_key_store.list_keys(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc
    logger.info(
        "provider_keys.list_success",
        extra={
            "event": "provider_keys.list_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return ProviderKeyListResponse(keys=keys)


@router.post(
    "/{brand_id}/keys",
    response_model=ProviderKey,
    status_code=status.HTTP_201_CREATED,
)
def add_provider_key(
    request: Request,
    brand_id: UUID,
    payload: ProviderKeyAdd,
    idempotency_key: IdempotencyKeyHeader,
    current_user: CurrentUserDep,
    provider_key_store: ProviderKeyStoreDep,
) -> ProviderKey:
    try:
        key = provider_key_store.add_key(
            current_user.user_id, brand_id, payload, idempotency_key
        )
    except LookupError as exc:
        raise _not_found() from exc
    except BrandCleanupRequiredError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "BRAND_CLEANUP_REQUIRED",
            "Brand cleanup is required. Retry deletion.",
        ) from exc
    except IdempotencyKeyRetiredError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "IDEMPOTENCY_KEY_RETIRED",
            "This add request was already completed and deleted. Use a new request ID.",
        ) from exc
    except VaultUnavailableError as exc:
        raise _error(
            status.HTTP_502_BAD_GATEWAY,
            "VAULT_UNAVAILABLE",
            "Secure key storage is unavailable right now.",
        ) from exc

    logger.info(
        "provider_keys.add_success",
        extra={
            "event": "provider_keys.add_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "provider": key.provider.value,
        },
    )
    return key


@router.patch(
    "/{brand_id}/keys/{key_id}/activate",
    response_model=ProviderKey,
)
def activate_provider_key(
    request: Request,
    brand_id: UUID,
    key_id: UUID,
    current_user: CurrentUserDep,
    provider_key_store: ProviderKeyStoreDep,
) -> ProviderKey:
    try:
        key = provider_key_store.activate_key(
            current_user.user_id, brand_id, key_id
        )
    except (
        LookupError,
        BrandCleanupRequiredError,
        KeyCleanupRequiredError,
        KeyInvalidError,
        KeyActivationConflictError,
    ) as exc:
        raise _activation_error(exc) from exc

    logger.info(
        "provider_keys.activate_success",
        extra={
            "event": "provider_keys.activate_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "provider": key.provider.value,
        },
    )
    return key


@router.post(
    "/{brand_id}/keys/{key_id}/validate",
    response_model=ProviderKeyValidationResponse,
)
async def validate_provider_key(
    request: Request,
    brand_id: UUID,
    key_id: UUID,
    current_user: CurrentUserDep,
    provider_key_store: ProviderKeyStoreDep,
    provider_validator: ProviderValidatorDep,
) -> ProviderKeyValidationResponse:
    started = time.monotonic()
    deadline = getattr(request.state, "validation_deadline", started + 15.0)

    try:
        claim = await _within_deadline(
            run_in_threadpool(
                provider_key_store.claim_validation,
                current_user.user_id,
                brand_id,
                key_id,
                deadline,
            ),
            deadline,
        )
    except (
        LookupError,
        BrandCleanupRequiredError,
        KeyCleanupRequiredError,
        VaultUnavailableError,
    ) as exc:
        raise _validation_error(exc) from exc
    except TimeoutError as exc:
        raise _validation_error(VaultUnavailableError()) from exc

    if claim.in_progress:
        code = ProviderValidationCode.VALIDATION_IN_PROGRESS
        response = _validation_response(
            claim=claim,
            outcome=ProviderValidationOutcome.TEMPORARY,
            code=code,
            key=claim.key,
        )
        _log_validation(request, claim.provider, code, started)
        return response

    assert claim.secret is not None
    assert claim.token is not None
    try:
        result = await _within_deadline(
            provider_validator.validate(claim.provider, claim.secret, deadline),
            deadline,
        )
    except TimeoutError:
        code = ProviderValidationCode.PROVIDER_TIMEOUT
        response = _validation_response(
            claim=claim,
            outcome=ProviderValidationOutcome.TEMPORARY,
            code=code,
            key=claim.key,
        )
        _log_validation(request, claim.provider, code, started)
        return response

    try:
        completion = await _within_deadline(
            run_in_threadpool(
                provider_key_store.complete_validation,
                current_user.user_id,
                brand_id,
                key_id,
                claim.token,
                result,
                deadline,
            ),
            deadline,
        )
    except (
        LookupError,
        BrandCleanupRequiredError,
        KeyCleanupRequiredError,
        VaultUnavailableError,
    ) as exc:
        raise _validation_error(exc) from exc
    except TimeoutError:
        code = ProviderValidationCode.PROVIDER_TIMEOUT
        response = _validation_response(
            claim=claim,
            outcome=ProviderValidationOutcome.TEMPORARY,
            code=code,
            key=claim.key,
        )
        _log_validation(request, claim.provider, code, started)
        return response

    if completion.superseded:
        outcome = ProviderValidationOutcome.TEMPORARY
        code = ProviderValidationCode.VALIDATION_SUPERSEDED
        provider_request_id = None
    else:
        outcome = result.outcome
        code = result.code
        provider_request_id = result.provider_request_id

    response = _validation_response(
        claim=claim,
        outcome=outcome,
        code=code,
        key=completion.key,
    )
    _log_validation(
        request,
        claim.provider,
        code,
        started,
        provider_request_id,
    )
    return response
