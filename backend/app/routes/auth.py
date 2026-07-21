from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ..config import load_settings
from ..services.login_guard import LoginGuard, get_login_guard


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    email: str
    password: str


class InvalidCredentialsError(Exception):
    pass


class ProviderUnavailableError(Exception):
    pass


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "INVALID_CREDENTIALS",
            "message": "The email or password you entered is incorrect.",
        },
    )


def _provider_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "PROVIDER_UNAVAILABLE",
            "message": "Unable to sign in right now. Please try again.",
        },
    )


def _account_locked() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "ACCOUNT_TEMPORARILY_LOCKED",
            "message": "Too many failed attempts. Try again in a few minutes.",
        },
    )


async def exchange_password_for_token(email: str, password: str) -> dict:
    settings = load_settings()
    url = f"{settings.supabase_url}/auth/v1/token?grant_type=password"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                headers={"apikey": settings.supabase_secret_key},
                json={"email": email, "password": password},
            )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        raise ProviderUnavailableError() from exc

    if response.status_code == status.HTTP_200_OK:
        return response.json()

    if response.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED}:
        raise InvalidCredentialsError()

    if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR or response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        raise ProviderUnavailableError()

    raise ProviderUnavailableError()


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    login_guard: LoginGuard = Depends(get_login_guard),
):
    normalized_email = login_guard.normalize_email(payload.email)
    request_id = getattr(request.state, "request_id", "unknown")

    logger.info("auth.login_attempt", extra={"event": "auth.login_attempt", "request_id": request_id})

    if login_guard.is_locked(normalized_email):
        logger.info("auth.login_locked", extra={"event": "auth.login_locked", "request_id": request_id})
        raise _account_locked()

    try:
        token_response = await exchange_password_for_token(normalized_email, payload.password)
    except InvalidCredentialsError:
        login_guard.record_failed_attempt(normalized_email)
        logger.info("auth.login_invalid_credentials", extra={"event": "auth.login_invalid_credentials", "request_id": request_id})
        raise _invalid_credentials()
    except ProviderUnavailableError:
        logger.info("auth.login_provider_unavailable", extra={"event": "auth.login_provider_unavailable", "request_id": request_id})
        raise _provider_unavailable()

    login_guard.reset(normalized_email)
    logger.info("auth.login_success", extra={"event": "auth.login_success", "request_id": request_id})
    return token_response
