from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import load_settings


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str
    email: str | None = None
    access_token: str | None = None


def _unauthorized(message: str = "Sign in required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": message},
    )


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _unauthorized()

    settings = load_settings()

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise _unauthorized() from None

    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized()

    return CurrentUser(
        user_id=user_id,
        email=payload.get("email"),
        access_token=token,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
