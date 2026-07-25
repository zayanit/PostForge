from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

from ..auth import CurrentUserDep
from ..models.brand import Brand, BrandCreate, BrandDelete, BrandListResponse
from ..services.brand_storage import (
    BrandStorage,
    BrandStorageError,
    get_brand_storage,
)
from ..services.brand_store import BrandNameTakenError, BrandStore, get_brand_store


router = APIRouter(prefix="/api/v1/brands", tags=["brands"])
logger = logging.getLogger(__name__)

BrandStoreDep = Annotated[BrandStore, Depends(get_brand_store)]
BrandStorageDep = Annotated[BrandStorage, Depends(get_brand_storage)]

MAX_LOGO_BYTES = 5 * 1024 * 1024
LOGO_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _name_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BRAND_NAME_TAKEN",
            "message": "You already have a brand with this name.",
        },
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "BRAND_NOT_FOUND", "message": "Brand not found."},
    )


def _confirmation_mismatch() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "CONFIRMATION_MISMATCH",
            "message": "The confirmation name does not match the brand name.",
        },
    )


def _unsupported_media_type() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "UNSUPPORTED_MEDIA_TYPE",
            "message": "Logo must be a PNG, JPEG, or WebP image.",
        },
    )


def _file_too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail={
            "code": "FILE_TOO_LARGE",
            "message": "Logo must be 5 MB or smaller.",
        },
    )


def _storage_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "STORAGE_UNAVAILABLE",
            "message": "Unable to update the logo right now.",
        },
    )


def _has_valid_signature(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


@router.get("", response_model=BrandListResponse)
def list_brands(
    request: Request,
    current_user: CurrentUserDep,
    brand_store: BrandStoreDep,
) -> BrandListResponse:
    brands = brand_store.list_brands(current_user.user_id)
    logger.info(
        "brands.list_success",
        extra={
            "event": "brands.list_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return BrandListResponse(brands=brands)


@router.get("/{brand_id}", response_model=Brand)
def get_brand(
    request: Request,
    brand_id: UUID,
    current_user: CurrentUserDep,
    brand_store: BrandStoreDep,
) -> Brand:
    try:
        brand = brand_store.get_brand(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc

    logger.info(
        "brands.get_success",
        extra={
            "event": "brands.get_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return brand


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


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    request: Request,
    brand_id: UUID,
    current_user: CurrentUserDep,
    brand_store: BrandStoreDep,
    brand_storage: BrandStorageDep,
    payload: BrandDelete | None = None,
) -> Response:
    try:
        brand = brand_store.get_brand(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc

    if payload is None or payload.confirm_name != brand.name:
        raise _confirmation_mismatch()

    try:
        logo_path = brand_store.get_logo_path(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc

    if logo_path:
        try:
            await brand_storage.delete_logo(logo_path)
        except BrandStorageError:
            logger.warning(
                "brands.delete_logo_cleanup_failed",
                extra={
                    "event": "brands.delete_logo_cleanup_failed",
                    "request_id": getattr(request.state, "request_id", "unknown"),
                },
            )

    try:
        brand_store.delete_brand(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc

    logger.info(
        "brands.delete_success",
        extra={
            "event": "brands.delete_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{brand_id}/logo", response_model=Brand)
async def upload_brand_logo(
    request: Request,
    brand_id: UUID,
    current_user: CurrentUserDep,
    brand_store: BrandStoreDep,
    brand_storage: BrandStorageDep,
    file: Annotated[UploadFile, File()],
) -> Brand:
    try:
        old_path = brand_store.get_logo_path(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc

    content_type = file.content_type or ""
    extension = LOGO_TYPES.get(content_type)
    if extension is None:
        await file.close()
        raise _unsupported_media_type()

    try:
        data = await file.read(MAX_LOGO_BYTES + 1)
    finally:
        await file.close()

    if len(data) > MAX_LOGO_BYTES:
        raise _file_too_large()
    if not _has_valid_signature(content_type, data):
        raise _unsupported_media_type()

    new_path = f"brands/{brand_id}/logo.{extension}"
    try:
        await brand_storage.upload_logo(new_path, data, content_type)
    except BrandStorageError as exc:
        raise _storage_unavailable() from exc

    try:
        brand = brand_store.update_logo_path(
            current_user.user_id,
            brand_id,
            new_path,
        )
    except Exception as exc:
        if new_path != old_path:
            try:
                await brand_storage.delete_logo(new_path)
            except BrandStorageError:
                logger.warning(
                    "brands.logo_rollback_failed",
                    extra={
                        "event": "brands.logo_rollback_failed",
                        "request_id": getattr(request.state, "request_id", "unknown"),
                    },
                )
        if isinstance(exc, LookupError):
            raise _not_found() from exc
        raise

    if old_path and old_path != new_path:
        try:
            await brand_storage.delete_logo(old_path)
        except BrandStorageError:
            logger.warning(
                "brands.logo_cleanup_failed",
                extra={
                    "event": "brands.logo_cleanup_failed",
                    "request_id": getattr(request.state, "request_id", "unknown"),
                },
            )

    logger.info(
        "brands.logo_upload_success",
        extra={
            "event": "brands.logo_upload_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return brand


@router.delete("/{brand_id}/logo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand_logo(
    request: Request,
    brand_id: UUID,
    current_user: CurrentUserDep,
    brand_store: BrandStoreDep,
    brand_storage: BrandStorageDep,
) -> Response:
    try:
        old_path = brand_store.get_logo_path(current_user.user_id, brand_id)
    except LookupError as exc:
        raise _not_found() from exc

    if old_path is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        brand_store.update_logo_path(current_user.user_id, brand_id, None)
    except LookupError as exc:
        raise _not_found() from exc
    try:
        await brand_storage.delete_logo(old_path)
    except BrandStorageError:
        logger.warning(
            "brands.logo_cleanup_failed",
            extra={
                "event": "brands.logo_cleanup_failed",
                "request_id": getattr(request.state, "request_id", "unknown"),
            },
        )

    logger.info(
        "brands.logo_delete_success",
        extra={
            "event": "brands.logo_delete_success",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
