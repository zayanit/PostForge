from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import CurrentUserDep
from ..models.profile import Profile, ProfileUpdate
from ..services.profile_store import ProfileStore, get_profile_store


router = APIRouter(tags=["me"])
logger = logging.getLogger(__name__)

ProfileStoreDep = Annotated[ProfileStore, Depends(get_profile_store)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PROFILE_NOT_FOUND", "message": "Profile not found."},
    )


@router.get("/api/v1/me", response_model=Profile)
def get_me(request: Request, current_user: CurrentUserDep, profile_store: ProfileStoreDep) -> Profile:
    if not current_user.email:
        raise _not_found()

    try:
        profile = profile_store.get_profile(current_user.user_id, current_user.email)
        logger.info("me.get_success", extra={"event": "me.get_success", "request_id": getattr(request.state, "request_id", "unknown")})
        return profile
    except LookupError as exc:
        raise _not_found() from exc


@router.patch("/api/v1/me", response_model=Profile)
def patch_me(
    request: Request,
    payload: ProfileUpdate,
    current_user: CurrentUserDep,
    profile_store: ProfileStoreDep,
) -> Profile:
    if not current_user.email:
        raise _not_found()

    try:
        profile = profile_store.update_profile(current_user.user_id, current_user.email, payload)
        logger.info("me.patch_success", extra={"event": "me.patch_success", "request_id": getattr(request.state, "request_id", "unknown")})
        return profile
    except LookupError as exc:
        raise _not_found() from exc
