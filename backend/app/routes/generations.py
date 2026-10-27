from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from ..auth import CurrentUserDep
from ..models.generation import (
    GenerateRequest,
    Generation,
    GenerationList,
    GenerationStatus,
)
from ..presets import PRESETS
from ..services.brand_storage import BrandStorageError
from ..services.brand_store import BrandCleanupRequiredError
from ..services.generation_storage import GenerationStorage, get_generation_storage
from ..services.generation_store import (
    GenerationConflict,
    GenerationStore,
    generation_asset_guard,
    get_generation_store,
)

router = APIRouter(prefix="/api/v1/brands", tags=["generations"])
StoreDep = Annotated[GenerationStore, Depends(get_generation_store)]
StorageDep = Annotated[GenerationStorage, Depends(get_generation_storage)]

MESSAGES = {
    "OPENAI_KEY_REQUIRED": (
        "Add or activate an OpenAI key in this brand's pro" "vider settings."
    ),
    "IDEMPOTENCY_CONFLICT": "This submission ID was already used for different input.",
    "GENERATION_PROCESSING": "This image is still processing. Wait before deleting it.",
    "GENERATION_ASSET_BUSY": "Image storage is busy. Please try again shortly.",
    "BRAND_CLEANUP_REQUIRED": "Brand cleanup is in progress. Retry brand deletion.",
    "STORAGE_UNAVAILABLE": "Image storage is unavailable. Please try again shortly.",
}


def mapped_error(exc):
    if isinstance(exc, GenerationConflict):
        code, status = exc.code, 409
    elif isinstance(exc, BrandCleanupRequiredError):
        code, status = "BRAND_CLEANUP_REQUIRED", 409
    elif isinstance(exc, BrandStorageError):
        code, status = "STORAGE_UNAVAILABLE", 503
    else:
        code, status = "GENERATION_NOT_FOUND", 404
    return HTTPException(
        status,
        detail={
            "code": code,
            "message": MESSAGES.get(code, "Brand or generation not found."),
        },
    )


async def present(row, storage):
    result = Generation.model_validate(row)
    if row["status"] == "succeeded" and not row["cleanup_required"]:
        result.image_url = await storage.sign(row["image_path"])
        result.image_url_expires_at = datetime.now(UTC) + timedelta(seconds=300)
    return result


@router.get("/generation-presets")
def generation_presets(current_user: CurrentUserDep):
    return {
        "presets": [
            {"id": key, "width": value[0], "height": value[1], "label": value[2]}
            for key, value in PRESETS.items()
        ]
    }


@router.post("/{brand_id}/generate", response_model=Generation, status_code=202)
async def submit(
    brand_id: UUID,
    payload: GenerateRequest,
    current_user: CurrentUserDep,
    store: StoreDep,
    storage: StorageDep,
    request_id: Annotated[UUID, Header(alias="Idempotency-Key")],
):
    try:
        return await present(
            store.submit(current_user.user_id, brand_id, payload, request_id), storage
        )
    except (
        LookupError,
        GenerationConflict,
        BrandCleanupRequiredError,
        BrandStorageError,
    ) as exc:
        raise mapped_error(exc) from exc


@router.get("/{brand_id}/generations", response_model=GenerationList)
async def history(
    brand_id: UUID,
    current_user: CurrentUserDep,
    store: StoreDep,
    storage: StorageDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    provider: Literal["openai", "gemini"] | None = None,
    status: GenerationStatus | None = None,
):
    try:
        rows, total = store.list(
            current_user.user_id, brand_id, page, per_page, provider, status
        )
        return GenerationList(
            generations=[await present(row, storage) for row in rows],
            page=page,
            per_page=per_page,
            total=total,
        )
    except (LookupError, BrandStorageError) as exc:
        raise mapped_error(exc) from exc


@router.get("/{brand_id}/generations/{generation_id}", response_model=Generation)
async def detail(
    brand_id: UUID,
    generation_id: UUID,
    current_user: CurrentUserDep,
    store: StoreDep,
    storage: StorageDep,
):
    try:
        return await present(
            store.get(current_user.user_id, brand_id, generation_id), storage
        )
    except (LookupError, BrandStorageError) as exc:
        raise mapped_error(exc) from exc


@router.delete("/{brand_id}/generations/{generation_id}", status_code=204)
async def delete(
    brand_id: UUID,
    generation_id: UUID,
    current_user: CurrentUserDep,
    store: StoreDep,
    storage: StorageDep,
):
    try:
        # Resolve ownership before taking a shared asset lock or touching storage.
        store.get(current_user.user_id, brand_id, generation_id)
        with generation_asset_guard(store.engine, brand_id):
            store.fence_delete(current_user.user_id, brand_id, generation_id)
            await storage.delete(storage.path(brand_id, generation_id))
            store.finish_delete(current_user.user_id, brand_id, generation_id)
        return Response(status_code=204)
    except (LookupError, GenerationConflict, BrandStorageError) as exc:
        raise mapped_error(exc) from exc
