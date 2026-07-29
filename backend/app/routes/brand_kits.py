from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import CurrentUserDep
from ..models.brand_kit import BrandKit, BrandKitUpsert
from ..services.brand_kit_store import (
    BrandKitStore,
    get_brand_kit_store,
)
from ..services.brand_store import BrandCleanupRequiredError, BrandNameTakenError


router = APIRouter(prefix="/api/v1/brands", tags=["brand-kits"])
logger = logging.getLogger(__name__)

BrandKitStoreDep = Annotated[BrandKitStore, Depends(get_brand_kit_store)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "BRAND_NOT_FOUND", "message": "Brand not found."},
    )


def _cleanup_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BRAND_CLEANUP_REQUIRED",
            "message": "Brand cleanup is required. Retry deletion.",
        },
    )


def _name_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BRAND_NAME_TAKEN",
            "message": "You already have a brand with this name.",
        },
    )


def _map_access_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BrandCleanupRequiredError):
        return _cleanup_required()
    return _not_found()


@router.get("/{brand_id}/kit", response_model=BrandKit)
def get_brand_kit(
    request: Request,
    brand_id: UUID,
    current_user: CurrentUserDep,
    brand_kit_store: BrandKitStoreDep,
) -> BrandKit:
    try:
        kit = brand_kit_store.get_kit(current_user.user_id, brand_id)
    except (LookupError, BrandCleanupRequiredError) as exc:
        raise _map_access_error(exc) from exc

    logger.info(
        "brand_kits.get_success",
        extra={
            "event": "brand_kits.get_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return kit


@router.put("/{brand_id}/kit", response_model=BrandKit)
def put_brand_kit(
    request: Request,
    brand_id: UUID,
    payload: BrandKitUpsert,
    current_user: CurrentUserDep,
    brand_kit_store: BrandKitStoreDep,
) -> BrandKit:
    try:
        kit = brand_kit_store.upsert_kit(current_user.user_id, brand_id, payload)
    except BrandNameTakenError as exc:
        raise _name_taken() from exc
    except (LookupError, BrandCleanupRequiredError) as exc:
        raise _map_access_error(exc) from exc

    logger.info(
        "brand_kits.put_success",
        extra={
            "event": "brand_kits.put_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return kit
