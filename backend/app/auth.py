from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
import asyncio
import time

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
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
def _get_cached_jwks_client() -> PyJWKClient:
    settings = load_settings()
    return PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")


def _get_jwks_client(request: Request) -> PyJWKClient:
    deadline = getattr(request.state, "validation_deadline", None)
    if deadline is None:
        return _get_cached_jwks_client()

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _unauthorized()
    settings = load_settings()
    return PyJWKClient(
        f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
        timeout=min(2, remaining),
    )


def _decode_access_token(request: Request, token: str, settings) -> dict:
    algorithm = jwt.get_unverified_header(token).get("alg", "HS256")

    if algorithm == "HS256":
        # Legacy shared-secret signing, still used by some projects.
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    # Newer Supabase projects sign access tokens with an asymmetric
    # key (e.g. ES256), published via the project's JWKS endpoint.
    signing_key = _get_jwks_client(request).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[algorithm],
        audience="authenticated",
    )


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _unauthorized()

    settings = load_settings()

    try:
        deadline = getattr(request.state, "validation_deadline", None)
        if deadline is None:
            payload = _decode_access_token(request, token, settings)
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _unauthorized()
            try:
                payload = await asyncio.wait_for(
                    asyncio.to_thread(_decode_access_token, request, token, settings),
                    timeout=remaining,
                )
            except TimeoutError:
                raise _unauthorized() from None
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
