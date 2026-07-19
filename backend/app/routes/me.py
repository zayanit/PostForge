from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import CurrentUserDep
from ..models.profile import Profile, ProfileUpdate
from ..services.profile_store import ProfileStore, get_profile_store


router = APIRouter(tags=["me"])

ProfileStoreDep = Annotated[ProfileStore, Depends(get_profile_store)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PROFILE_NOT_FOUND", "message": "Profile not found."},
    )


@router.get("/api/v1/me", response_model=Profile)
def get_me(current_user: CurrentUserDep, profile_store: ProfileStoreDep) -> Profile:
    try:
        return profile_store.get_profile(current_user.user_id, current_user.email or "")
    except LookupError as exc:
        raise _not_found() from exc


@router.patch("/api/v1/me", response_model=Profile)
def patch_me(
    payload: ProfileUpdate,
    current_user: CurrentUserDep,
    profile_store: ProfileStoreDep,
) -> Profile:
    try:
        return profile_store.update_profile(current_user.user_id, current_user.email or "", payload)
    except LookupError as exc:
        raise _not_found() from exc
