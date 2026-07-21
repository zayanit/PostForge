from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

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


@lru_cache(maxsize=1)
def _get_jwks_client() -> PyJWKClient:
    settings = load_settings()
    return PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")


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
        algorithm = jwt.get_unverified_header(token).get("alg", "HS256")

        if algorithm == "HS256":
            # Legacy shared-secret signing, still used by some projects.
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            # Newer Supabase projects sign access tokens with an asymmetric
            # key (e.g. ES256), published via the project's JWKS endpoint.
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
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
