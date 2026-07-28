from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from ..auth import CurrentUserDep
from ..models.provider_key import (
    IdempotencyKey,
    ProviderKey,
    ProviderKeyAdd,
    ProviderKeyListResponse,
)
from ..services.brand_store import BrandCleanupRequiredError
from ..services.provider_key_store import (
    IdempotencyKeyRetiredError,
    ProviderKeyStore,
    VaultUnavailableError,
    get_provider_key_store,
)


router = APIRouter(prefix="/api/v1/brands", tags=["provider-keys"])
logger = logging.getLogger(__name__)

ProviderKeyStoreDep = Annotated[ProviderKeyStore, Depends(get_provider_key_store)]
IdempotencyKeyHeader = Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _not_found() -> HTTPException:
    return _error(status.HTTP_404_NOT_FOUND, "BRAND_NOT_FOUND", "Brand not found.")


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
