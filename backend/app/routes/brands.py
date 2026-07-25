from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import CurrentUserDep
from ..models.brand import Brand, BrandCreate
from ..services.brand_store import BrandNameTakenError, BrandStore, get_brand_store


router = APIRouter(prefix="/api/v1/brands", tags=["brands"])
logger = logging.getLogger(__name__)

BrandStoreDep = Annotated[BrandStore, Depends(get_brand_store)]


def _name_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BRAND_NAME_TAKEN",
            "message": "You already have a brand with this name.",
        },
    )


@router.post("", response_model=Brand, status_code=status.HTTP_201_CREATED)
def create_brand(
    request: Request,
    payload: BrandCreate,
    current_user: CurrentUserDep,
    brand_store: BrandStoreDep,
) -> Brand:
    try:
        brand = brand_store.create_brand(current_user.user_id, payload)
    except BrandNameTakenError as exc:
        raise _name_taken() from exc

    logger.info(
        "brands.create_success",
        extra={
            "event": "brands.create_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return brand
